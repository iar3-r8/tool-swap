"""Docker backend for the container backend seam (M2a).

This module is the Docker half of the seam: plan behaviours 14-27 of
``plans/m2a-container-backend-seam.md``.  The pure half —
:func:`build_run_kwargs` (behaviours 14-18) and :func:`map_sdk_error`
(behaviour 19) — holds every docker-py fact the backend needs: the
kwarg names, the device-request shape, the exception classification.
Keeping those facts in functions rather than in a class is what lets
the shell stay thin (plan §4.5) and every fact be table-testable with
no client and no daemon.

:class:`DockerBackend` is that thin shell (behaviours 20-26): its
constructor takes an **already-built** client and never reads the
ambient environment, :meth:`DockerBackend.from_config` is the only
path permitted to build a real one, and the six protocol methods are
call pairs over the injected client that route every exception
through :func:`map_sdk_error`, so no raw SDK exception escapes the
seam.

Boundary: this module is the only ``tool_swap`` module that imports
the Docker SDK.  That is enforced, not hoped for — the fifth contract
in ``.importlinter`` (behaviour 27) forbids ``docker`` from every
other module, and the seam's other modules import with the SDK
absent.  Nothing here was verified against a running daemon: M2a
runs no docker tests.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Protocol, cast

import docker
import docker.errors
import requests.exceptions
from docker.types import DeviceRequest

from tool_swap.backend.base import (
    ContainerHandle,
    ContainerSpec,
    ContainerState,
    ContainerStatus,
    MountSpec,
)
from tool_swap.backend.errors import (
    BackendError,
    BackendUnavailableError,
    ContainerNameConflictError,
    ContainerNotFoundError,
    ContainerStartError,
    GpuUnavailableError,
    ImageNotFoundError,
)
from tool_swap.backend.labels import label_selector, managed_labels

if TYPE_CHECKING:
    # Annotation-only: ``from_config``'s parameter is the only use, and
    # a runtime ``backend -> config`` import would re-couple the
    # backend's import graph to the config layer, which plan §4.2
    # deliberately kept free (the edge is structurally legal per
    # .importlinter contract 3, but still avoided).
    from tool_swap.config.schema import BackendConfig

#: Module-level logger; behaviour 24's unknown-state warning goes here
#: — the repository has no logging helper to follow, so it stays plain.
logger = logging.getLogger(__name__)

#: The daemon 404 message fragments that name a missing image.  The
#: SDK's own classifier matches exactly these, lowercased, to choose
#: ``ImageNotFound`` over ``NotFound``
#: (``.venv/lib/python3.11/site-packages/docker/errors.py:3-10``;
#: ``plan/third-party-docs/docker/errors.md`` §2 "The 404 mapping").
#: :func:`map_sdk_error` mirrors them — rather than importing the
#: private ``_image_not_found_explanation_fragments`` — and
#: re-classifies by the daemon's text so an ``ImageNotFound`` that
#: degrades to a plain ``NotFound`` (the daemon's wording stops
#: matching) still maps to ``ImageNotFoundError``.
_IMAGE_NOT_FOUND_FRAGMENTS: tuple[str, ...] = (
    "no such image",
    "not found: does not exist or no pull access",
    "repository does not exist",
    "was found but does not match the specified platform",
)

#: Message fragments that identify an unsatisfiable GPU device request.
#: The SDK has no GPU exception class — the refusal surfaces as a bare
#: ``APIError`` (``plan/third-party-docs/docker/errors.md`` §3), so the
#: daemon's text is the only channel.  **Brittle heuristic, not a
#: stable interface**: the daemon's real wording is recorded nowhere
#: (plan §7 item 12); if it proves wrong, the failure mode is mild —
#: a GPU refusal surfaces as ``ContainerStartError`` with the daemon's
#: text intact.
_GPU_MESSAGE_FRAGMENTS: tuple[str, ...] = ("nvidia", "gpu")

#: The daemon's name-conflict phrase, whose quoted-name shape is
#: ``The container name "/<name>" is already in use by container
#: "<id>"``.
_NAME_CONFLICT_PHRASE = " is already in use"


def build_run_kwargs(spec: ContainerSpec, *, label_namespace: str) -> dict[str, object]:
    """Translate a :class:`ContainerSpec` into ``containers.create`` kwargs.

    Pure function: it reads the spec and nothing else — no client, no
    daemon, no environment — and returns a fresh dict on every call so
    a later caller that ``**kwargs``-unpacks it cannot share mutable
    state with another.

    The output carries exactly the keys ``image``, ``name``, ``labels``
    and, when set, ``environment``, ``network``, ``volumes``,
    ``device_requests``, ``nano_cpus``, ``mem_limit``, ``shm_size`` and
    ``ports``.
    ``labels`` is the full :func:`managed_labels` set for
    *label_namespace* and the spec's tool, with the spec's own labels
    merged in (collision precedence is deliberately not decided by
    behaviour 14; the current order lets spec labels win).
    ``environment`` is the spec's mapping copied as a plain dict,
    ``network`` is the spec's network name, and ``volumes`` is the
    spec's mounts in the documented dict form (behaviour 15).  No
    ``detach`` key: the start path is ``create`` + ``start``, not
    ``run(detach=True)`` (plan §5 behaviour 14, amended).

    Args:
        spec: The fully resolved container spec to translate.
        label_namespace: Resolved label namespace, passed by the
            caller and required; there is no default to fall back on,
            matching the ``DockerBackend`` constructor style of
            plan §4.5.

    Returns:
        A fresh kwargs dict for ``client.containers.create(**kwargs)``:
        always ``image``, ``name`` and ``labels``; ``environment`` only
        when ``spec.env`` is non-empty, ``network`` only when
        ``spec.network`` is not ``None``, ``volumes`` only when
        ``spec.mounts`` is non-empty, ``device_requests`` (one
        ``DeviceRequest``) only when ``spec.devices`` is non-empty,
        ``nano_cpus`` only when ``spec.cpus`` is not ``None``,
        ``mem_limit`` / ``shm_size`` only when the matching spec field
        is not ``None``, and ``ports`` (the container port keyed to the
        host port) only when ``spec.published_port`` is not ``None``.
        Size strings are passed through verbatim — parsing them is the
        SDK's job (``HostConfig`` calls ``parse_bytes``), so no local
        size-string check is made here (plan §5 behaviour 17,
        amended).  Likewise no port *range* check: a host port outside
        ``port_range`` passes through verbatim — range policy is
        config validation's (plan §5 behaviour 18;
        ``plan/01_ARCHITECTURE.md`` §2.1).

    Raises:
        ValueError: ``spec.image`` is empty, a ``spec.devices`` index
            is negative, or ``spec.container_port`` /
            ``spec.published_port`` is not positive — caller
            programming errors, raised before any SDK call, so a plain
            ``ValueError`` rather than a ``tool_swap.backend.errors``
            taxonomy member.
    """
    if not spec.image:
        raise ValueError("container image must not be empty")
    kwargs: dict[str, object] = {
        "image": spec.image,
        "name": spec.name,
        "labels": {**managed_labels(label_namespace, spec.tool), **dict(spec.labels)},
    }
    if spec.env:
        kwargs["environment"] = dict(spec.env)
    if spec.network is not None:
        kwargs["network"] = spec.network
    if spec.mounts:
        kwargs["volumes"] = _volumes_from_mounts(spec.mounts)
    if spec.devices:
        kwargs["device_requests"] = _device_requests_from_devices(spec)
    if spec.cpus is not None:
        # nano_cpus is an int in units of 1e-9 CPUs (models/containers.py:681).
        # round() — not int() — because the float product can land just
        # below the true integer (e.g. 1.001 * 1e9 == 1000999999.9999999),
        # which int() would truncate and drop a whole nano-CPU.
        kwargs["nano_cpus"] = round(spec.cpus * 1e9)
    if spec.memory is not None:
        kwargs["mem_limit"] = spec.memory
    if spec.shm_size is not None:
        kwargs["shm_size"] = spec.shm_size
    ports = _ports_from_spec(spec)
    if ports is not None:
        kwargs["ports"] = ports
    return kwargs


def _device_requests_from_devices(spec: ContainerSpec) -> list[DeviceRequest]:
    """Translate resolved GPU indices into one :class:`DeviceRequest`.

    The canonical GPU form for specific devices is
    ``DeviceRequest(driver=spec.gpu_runtime, device_ids=[...])`` — the
    named indices and the named runtime live in one request
    (``plan/third-party-docs/docker/gpu-device-requests.md`` §1).
    ``device_ids`` is a list of *strings*, so each int index is
    converted with ``str()`` in declaration order, duplicates
    collapsed.  ``count`` is never set: the docstring says to set
    either ``count`` or ``device_ids`` and the SDK does not enforce
    that client-side (same §1), so setting both would encode a request
    only a daemon could reject.

    Raises:
        ValueError: a device index is negative — raised before any
            construction, naming the offending index.
    """
    if any(index < 0 for index in spec.devices):
        offending = next(index for index in spec.devices if index < 0)
        raise ValueError(f"device index must be non-negative, got {offending}")
    device_ids = [str(index) for index in dict.fromkeys(spec.devices)]
    return [DeviceRequest(driver=spec.gpu_runtime, device_ids=device_ids)]


def _ports_from_spec(spec: ContainerSpec) -> dict[int, int] | None:
    """Translate the spec's ports into the ``ports`` mapping, or omit it.

    The mapping is ``{container_port: published_port}`` — the container
    port is the key and the host port the value, because the SDK walks
    the mapping key-first: ``convert_port_bindings`` treats ``k`` as
    the container port and builds the host binding from ``v``
    (``.venv/lib/python3.11/site-packages/docker/utils/utils.py``
    lines 113-123; ``plan/third-party-docs/docker/
    containers-run-create.md`` §2, line 84).  The key stays a bare
    ``int``: the SDK appends ``"/tcp"`` itself when the key holds no
    protocol suffix (``docker/utils/utils.py`` lines 116-118), so
    pre-suffixing would duplicate its normalisation.  No range check:
    a host port outside ``port_range`` passes through verbatim —
    range policy is config validation's (``plan/01_ARCHITECTURE.md``
    §2.1).

    Args:
        spec: The fully resolved container spec.

    Returns:
        The one-entry ``ports`` mapping when ``spec.published_port``
        is set, else ``None`` — ``published_port=None`` means nothing
        is published (D21), so the key is omitted rather than emitted
        empty.

    Raises:
        ValueError: ``spec.container_port`` is not positive, or
            ``spec.published_port`` is set and not positive — raised
            before anything is built, naming the offending field and
            value.
    """
    if spec.container_port <= 0:
        raise ValueError(
            f"container_port must be a positive port, got {spec.container_port}"
        )
    if spec.published_port is None:
        return None
    if spec.published_port <= 0:
        raise ValueError(
            f"published_port must be a positive port, got {spec.published_port}"
        )
    return {spec.container_port: spec.published_port}


def _volumes_from_mounts(mounts: tuple[MountSpec, ...]) -> dict[str, dict[str, str]]:
    """Translate resolved mounts into the ``volumes`` dict form.

    Each entry is ``{source: {"bind": target, "mode": "ro" | "rw"}}``,
    the exact shape documented in
    ``plan/third-party-docs/docker/containers-run-create.md`` §2;
    declaration order is preserved by dict insertion order.  No
    de-duplication: collapsing entries is config-validation's job, not
    the driver's.
    """
    return {
        mount.source: {"bind": mount.target, "mode": "ro" if mount.read_only else "rw"}
        for mount in mounts
    }


def map_sdk_error(exc: BaseException) -> BackendError:
    """Translate an SDK exception — or anything else — into the taxonomy.

    Pure and **total**: it reads the exception and nothing else — no
    client, no daemon, no environment — and it never raises.  It
    *returns* a member of the seven-member taxonomy
    ``tool_swap.backend.errors`` (plan §4.3) for the caller to raise,
    so no raw SDK exception escapes the seam.  When the input is an
    exception, the returned member chains it as ``__cause__``; and for
    every input the ``message`` carries a distinctive part of the
    input's text, so the original is never swallowed.  A non-exception
    input cannot be *chained* — CPython allows an exception's
    ``__cause__`` to be only ``None`` or a ``BaseException`` and raises
    ``TypeError`` for anything else — so for that one input the text
    is preserved in the message instead.

    The mapping (plan §4.3, read against
    ``plan/third-party-docs/docker/errors.md``, re-verified against the
    installed docker 7.2.0):

    - a 404 whose daemon text names a missing image — an
      ``ImageNotFound``, or a ``NotFound`` carrying that text (the SDK
      classifies 404s by string-matching the daemon's message and
      degrades to the parent when the wording stops matching,
      errors.md §2) — maps to ``ImageNotFoundError`` naming the image
      ref;
    - any other 404 (a vanished container) maps to
      ``ContainerNotFoundError``;
    - an ``APIError`` 409 whose daemon text names a taken name maps to
      ``ContainerNameConflictError`` naming the conflicting name;
    - an ``APIError`` whose text matches ``_GPU_MESSAGE_FRAGMENTS``
      case-insensitively maps to ``GpuUnavailableError`` — a brittle
      message heuristic (plan §7 item 12), not a stable interface;
    - any other ``APIError`` maps to ``ContainerStartError`` carrying
      the daemon's text;
    - a dead daemon — a bare ``requests`` connection error from an
      operational call, or the construction-path
      ``DockerException`` "Error while fetching server API version: …"
      (errors.md §3 [CORRECTED 2026-09-16]) — maps to
      ``BackendUnavailableError``;
    - anything else — an unrelated ``DockerException`` included, and a
      non-exception input — maps to the ``BackendError`` fallback,
      preserving the text.

    The ``isinstance`` checks below are **ordered and must stay
    ordered**: ``APIError`` inherits ``requests.exceptions.HTTPError``
    (errors.md §1), so the broad ``requests`` connection check runs
    after it — a broad check placed first would swallow every 4xx/5xx
    API error and turn a 500 into "daemon unavailable"; and a 404 is
    re-classified by the daemon's message *inside* the ``APIError``
    branch, before the 409, so the image/container split (including the
    degraded ``NotFound``) is decided by text rather than by which
    parent class a later check reaches first.  Do not "tidy" this
    order.

    Args:
        exc: The exception to translate — in practice whatever a
            ``DockerBackend`` method caught from an SDK call
            (behaviours 21+).  Any value is accepted, not only
            exceptions.

    Returns:
        The taxonomy member the caller should raise, with ``exc``
        chained as its ``__cause__``.
    """
    # A non-exception (a programming error at the seam) is the fallback:
    # the function stays total.  Its text is preserved in the message;
    # the object itself cannot be chained as ``__cause__`` (CPython
    # restricts that to ``None`` or a ``BaseException``).
    if not isinstance(exc, BaseException):
        return BackendError(text_of(exc))

    # 1. APIError FIRST: it is a requests.exceptions.HTTPError, so any
    #    broader requests check placed earlier would shadow every real
    #    API error (test_api_error_not_swallowed_by_requests_catch).
    if isinstance(exc, docker.errors.APIError):
        # 404: re-classified by the daemon's message, not the SDK's
        #    class — an ImageNotFound that degrades to a plain NotFound
        #    (errors.md §2) must still map as a missing image.
        if exc.status_code == 404:
            return _map_not_found(exc)
        # 409: only a daemon text that names a taken name is a name
        #    conflict; any other 409 is a refused start.
        if exc.status_code == 409 and _conflict_name(exc) is not None:
            return _map_name_conflict(exc)
        # GPU refusal: no SDK class exists, the message is the only
        # channel (brittle heuristic — see _GPU_MESSAGE_FRAGMENTS).
        if _gpu_message(_explanation_or_text(exc)):
            return _map_gpu_unavailable(exc)
        return _map_api_error(exc)

    # 2. Operational dead daemon: a bare requests connection error —
    #    ConnectTimeout included, it is a ConnectionError subclass —
    #    from a call against an unreachable daemon (errors.md §3).
    #    APIError was matched above, so only genuinely non-response
    #    errors reach here.
    if isinstance(exc, requests.exceptions.ConnectionError):
        return _map_unavailable(exc)

    # 3. Construction-path dead daemon: APIClient.__init__ wraps a
    #    connection failure in a DockerException "Error while fetching
    #    server API version: …" with the connection error chained as
    #    __cause__ (api/client.py:221-232).  The match is on that exact
    #    template: the *other* _retrieve_server_version wrap — a
    #    reachable daemon answering without an "ApiVersion" key — is a
    #    different message and must fall through to the fallback, not
    #    be called unavailable.
    if isinstance(exc, docker.errors.DockerException) and str(exc).startswith(
        "Error while fetching server API version: "
    ):
        return _map_unavailable(exc)

    # 4. Fallback: an unrecognised SDK exception (an unrelated
    #    DockerException included) or any non-exception input.
    return _backend_error_from(exc, text_of(exc))


def _map_not_found(exc: docker.errors.APIError) -> BackendError:
    """Map a 404 to the missing-image or vanished-container member.

    The daemon's text decides (errors.md §2 "The 404 mapping"): a
    message naming a missing image maps to ``ImageNotFoundError`` with
    the image ref in the remedy, whatever class the SDK chose; any
    other 404 maps to ``ContainerNotFoundError``.
    """
    explanation = _explanation_or_text(exc)
    error: BackendError
    if any(fragment in explanation.lower() for fragment in _IMAGE_NOT_FOUND_FRAGMENTS):
        image_ref = explanation.split(_IMAGE_NOT_FOUND_FRAGMENTS[0], 1)[-1].lstrip(": ")
        error = ImageNotFoundError(
            f"Image not found: {exc}",
            remedy=f"The image reference {image_ref!r} does not exist — build it "
            "with `tswap build <tool>`.",
        )
    else:
        error = ContainerNotFoundError(f"Container not found: {exc}")
    error.__cause__ = exc
    return error


def _conflict_name(exc: docker.errors.APIError) -> str | None:
    """Extract the conflicting container name from a 409's daemon text.

    The daemon's shape is ``The container name "/<name>" is already in
    use by container "<id>"``.  Returns the name without its leading
    slash, or ``None`` when the text does not carry that shape — such
    a 409 is a refused start, not a name conflict.
    """
    explanation = _explanation_or_text(exc)
    if _NAME_CONFLICT_PHRASE not in explanation:
        return None
    marker = 'The container name "'
    start = explanation.find(marker)
    if start == -1:
        return None
    name_start = start + len(marker)
    name_end = explanation.find('"', name_start)
    if name_end == -1:
        return None
    return explanation[name_start:name_end].lstrip("/")


def _map_name_conflict(exc: docker.errors.APIError) -> ContainerNameConflictError:
    """Map a name-conflict 409, naming the conflicting name in the remedy."""
    name = _conflict_name(exc)
    error = ContainerNameConflictError(
        f"Container name conflict: {exc}",
        remedy=f"The container name {name!r} is already taken — free it with "
        "`tswap down`.",
    )
    error.__cause__ = exc
    return error


def _map_gpu_unavailable(exc: docker.errors.APIError) -> GpuUnavailableError:
    """Map an unsatisfiable GPU device request (message heuristic)."""
    error = GpuUnavailableError(
        f"GPU device request could not be satisfied: {exc}",
        remedy="Install or repair the NVIDIA container toolkit so the requested "
        "GPU device can be satisfied.",
    )
    error.__cause__ = exc
    return error


def _map_api_error(exc: docker.errors.APIError) -> ContainerStartError:
    """Map any other APIError to a refused start, carrying the daemon's text."""
    error = ContainerStartError(f"Daemon refused the start: {exc}")
    error.__cause__ = exc
    return error


def _map_unavailable(exc: BaseException) -> BackendUnavailableError:
    """Map a dead-daemon failure (either hierarchy) to unavailable."""
    error = BackendUnavailableError(f"Container daemon unreachable: {exc}")
    error.__cause__ = exc
    return error


def _backend_error_from(exc: BaseException, message: str) -> BackendError:
    """Build the ``BackendError`` fallback, chaining the input as the cause."""
    error = BackendError(message)
    error.__cause__ = exc
    return error


def _explanation_or_text(exc: docker.errors.APIError) -> str:
    """The daemon's text for an ``APIError``: ``explanation``, else ``str()``."""
    return exc.explanation if exc.explanation is not None else str(exc)


def _gpu_message(text: str) -> bool:
    """Whether an APIError's text matches the GPU refusal heuristic."""
    lowered = text.lower()
    return any(fragment in lowered for fragment in _GPU_MESSAGE_FRAGMENTS)


def text_of(value: object) -> str:
    """The text a taxonomy message should carry for *value*.

    An exception's text (``str(exc)``) — which for an ``APIError``
    includes the daemon's explanation — or ``str(value)`` for a
    non-exception input, so the fallback never swallows anything.
    """
    return str(value)


def _state_block(attrs: Mapping[str, object]) -> Mapping[str, object] | None:
    """The raw inspect dict's ``State`` sub-mapping, or ``None``.

    Shared by the two behaviour-24 attribute reads.  A missing or
    non-mapping ``State`` is a malformed inspect response the saved
    references never describe — logged once at WARNING so a rare case
    is observed rather than guessed, and reported as ``None`` so the
    caller falls back to the ``None`` fields rather than inventing
    values (see :meth:`DockerBackend.inspect`).

    Args:
        attrs: The raw inspect dict ``container.attrs`` carries.

    Returns:
        The ``State`` sub-mapping, or ``None`` when it is absent or
        carries no mapping at all.
    """
    state: object = attrs.get("State")
    if not isinstance(state, Mapping):
        logger.warning(
            "container inspect response carries no State mapping — "
            "exit code and start time are reported as None"
        )
        return None
    return state


def _state_exit_code(attrs: Mapping[str, object]) -> int | None:
    """``attrs['State']['ExitCode']`` as an ``int``, or ``None``.

    The key is **[INFERRED]** — ``container-attrs-reload.md`` §3.1:
    the only ``ExitCode`` in the installed package belongs to
    ``exec_inspect``, so the path rests on the Engine API contract,
    not SDK source.  A missing key, or a value that is not an ``int``,
    reads ``None`` rather than being coerced: the daemon's own number
    is the only authority for this field, and a shape the Engine API
    never names cannot lend one.
    """
    block = _state_block(attrs)
    if block is None:
        return None
    code: object = block.get("ExitCode")
    if isinstance(code, int) and not isinstance(code, bool):
        return code
    return None


def _state_started_at(attrs: Mapping[str, object]) -> str | None:
    """``attrs['State']['StartedAt']`` as a ``str``, or ``None``.

    The key is **[INFERRED]** — ``container-attrs-reload.md`` §3.1:
    zero matches for ``StartedAt`` anywhere in the installed package,
    so the path rests on the Engine API contract, not SDK source.
    A missing key or a non-string value reads ``None``: the seam
    passes the daemon's string through verbatim (no coercion to
    ``datetime`` — base.py), so a value in a shape the Engine API
    never names is dropped rather than transformed.
    """
    block = _state_block(attrs)
    if block is None:
        return None
    started_at: object = block.get("StartedAt")
    if isinstance(started_at, str):
        return started_at
    return None


def _iter_log_lines(stream: Iterator[bytes]) -> Iterator[str]:
    """Reassemble the daemon's byte chunks into decoded log lines.

    The SDK's log stream yields chunks of ``bytes`` whose boundaries
    fall wherever the daemon's frames fall — routinely **inside** a
    line (``plan/third-party-docs/docker/container-logs.md`` §2,
    [READ]: "one or more log frames after header stripping") — so
    decoding and splitting each chunk independently would fragment
    every line a boundary touches.  The buffer therefore accumulates
    the bytes of the incomplete trailing line: on every chunk the
    buffer is split on ``b"\\n"`` only, every fragment except the last
    is a complete line and is decoded with ``errors="replace"`` and
    yielded (one bad byte becomes U+FFFD and the stream continues),
    and the last fragment — with no terminator yet — stays in the
    buffer for the next chunk.  A chunk that leaves the buffer with
    no newline at all — the common first chunk for any line longer
    than a frame — yields nothing and keeps the whole buffer.
    When the stream ends, the remainder
    is yielded as the final line if it is non-empty: the last line of
    a live log routinely has no terminator yet, and a viewer that
    silently drops it swallows exactly the line the operator most
    wants — a silent data-loss bug by this repository's own KISS
    rule.

    The split is on ``b"\\n"`` only — never ``splitlines``: the
    daemon's framing is a fact the saved references never claim, and
    CRLF or lone-``"\\r"`` handling would be a second line concept
    the seam does not need.  The newline contract itself is ours,
    not an SDK fact (same page §2: the caller must ``.decode(...)``
    explicitly) — see :meth:`DockerBackend.logs`.

    Args:
        stream: The daemon's byte-chunk stream, as returned by
            ``container.logs(stream=True, ...)``.

    Yields:
        One decoded line per item, each without its trailing newline;
        a trailing partial line, if any, as the final item.
    """
    buffer = b""
    for chunk in stream:
        buffer += chunk
        if b"\n" not in buffer:
            continue
        complete, buffer = buffer.rsplit(b"\n", 1)
        for line in complete.split(b"\n"):
            yield line.decode("utf-8", errors="replace")
    if buffer:
        yield buffer.decode("utf-8", errors="replace")


class _BackendContainer(Protocol):
    """The object ``containers.create`` / ``containers.get`` /
    ``containers.list`` returns, as far as ``start`` (behaviour 21),
    ``stop`` (behaviour 22), ``is_running`` (behaviour 23),
    ``inspect`` (behaviour 24), ``list_managed`` (behaviour 25) and
    ``logs`` (behaviour 26) touch it.

    A real object is a ``docker.models.containers.Container`` —
    ``id`` the runtime id, ``name`` the daemon's name with its
    leading slash stripped (``container-attrs-reload.md`` §3,
    containers.py:28-34), ``status`` the state property
    (``running``, ``exited``, …;
    ``plan/third-party-docs/docker/container-attrs-reload.md`` §3),
    ``attrs`` the raw inspect dict (``container-attrs-reload.md`` §1,
    [READ]: the raw dict the daemon's inspect returned, cached and
    refreshed only by ``reload()``), ``labels`` the container's label
    map read from ``attrs['Config']['Labels']`` (``container-attrs-
    reload.md`` §3, containers.py:47-58), and ``start`` and ``stop``
    methods (``plan/third-party-docs/docker/containers-run-create.md``
    §4; ``plan/third-party-docs/docker/container-stop-wait.md`` §1,
    models/containers.py:441-453); the behaviour-21/22/23/24/25
    recording stubs carry exactly the members each path uses, so this
    is also the widest shape any stub allows.
    """

    #: The runtime id the container is known by.
    id: str

    #: The daemon's name, leading slash stripped (containers.py:28-34).
    name: str

    #: The state the daemon reports (``running``, ``exited``, …).
    status: str

    #: The raw inspect dict the daemon returned.  A nested mapping of
    #: unknown shape — the Engine API's ``ContainerInspect`` — whose
    #: members this module reads are the ``State`` sub-mapping's
    #: ``ExitCode`` and ``StartedAt`` (both **[INFERRED]** — see
    #: :meth:`DockerBackend.inspect`) and ``Config.Image`` (see
    #: :meth:`DockerBackend.list_managed`), so it is typed honestly as
    #: a mapping of unknown value type rather than a pinned schema.
    attrs: Mapping[str, object]

    #: The container's label map (``attrs['Config']['Labels']``).
    labels: dict[str, str]

    def start(self, **kwargs: object) -> None:
        """Start the container; the SDK's ``Container.start(**kwargs)``."""
        ...

    def stop(self, **kwargs: object) -> None:
        """Stop the container; the SDK's ``Container.stop(**kwargs)``."""
        ...

    def logs(self, stream: bool, *, follow: bool, tail: int) -> Iterator[bytes]:
        """The container's log stream; the SDK's ``Container.logs``.

        ``Container.logs(**kwargs)`` forwards every kwarg to
        ``client.api.logs`` (``plan/third-party-docs/docker/
        container-logs.md`` §1, models/containers.py:294); the streaming
        form (``stream=True``) yields chunks of ``bytes`` — one or more
        log frames after header stripping, never decoded by the SDK
        (same page §2, [READ]).  A real object is a ``CancellableStream``
        (same page §2, types/daemon.py:8) — an iterator that also
        exposes ``close()`` to abort an open follow early — but the
        seam's contract is iteration only, so this protocol member is
        the iterator half, honestly typed as an iterator over byte
        chunks.  The behaviour-26 recording stub returns a plain
        ``Iterator[bytes]`` for the same reason: it carries no
        ``close()`` because the seam never closes.
        """
        ...


class _BackendContainers(Protocol):
    """The ``client.containers`` collection, as far as ``start``,
    ``stop``, ``is_running``, ``inspect`` and ``list_managed`` touch
    it.

    Three members: ``create`` (behaviour 21), ``get`` (behaviours
    22-24) and ``list`` (behaviour 25), the first two returning a
    :class:`_BackendContainer` and ``list`` a list of them.  The image
    is declared keyword-only because the behaviour-21 stub records an
    explicitly passed ``image=`` into its kwargs dict, and the SDK's
    ``create`` also accepts it as a keyword (it re-sets
    ``kwargs['image']`` itself —
    ``.venv/lib/python3.11/site-packages/docker/models/containers.py:
    932``), so the pure function's output unpacks against both.
    """

    def create(self, **kwargs: object) -> _BackendContainer:
        """Create (do not start) the container the kwargs describe."""
        ...

    def get(self, container_id: str) -> _BackendContainer:
        """Fetch one container by id or name; the SDK raises
        ``NotFound`` when it is missing (``plan/third-party-docs/
        docker/containers-list-filters.md`` §5,
        models/containers.py:939-952)."""
        ...

    def list(self, **kwargs: object) -> list[_BackendContainer]:
        """List containers; the SDK's ``ContainerCollection.list``
        (``plan/third-party-docs/docker/containers-list-filters.md``
        §1: ``list(all=False, before=None, filters=None, limit=-1,
        since=None, sparse=False, ignore_removed=False)``)."""
        ...


class _BackendClient(Protocol):
    """The minimal client shape the behaviour-21/22/23 call pairs call
    through.

    Kept to exactly what those call pairs touch — a ``containers``
    collection, nothing more — **not** a speculative full client
    interface: behaviours 24-26 will force any further members when
    they land.  ``containers`` is a plain attribute member (not a
    property), matching how both a real ``docker.DockerClient`` and
    the behaviour-21/22/23 recording stubs carry it — set in
    ``__init__``.
    """

    #: The container collection; the only attribute the call pairs read.
    containers: _BackendContainers


class DockerBackend:
    """The thin shell over :func:`build_run_kwargs` / :func:`map_sdk_error`.

    Behaviour 20 of ``plans/m2a-container-backend-seam.md`` (§4.5):
    the constructor takes an **already-built** client and stores exactly
    that object, while :meth:`from_config` is the only path that builds
    a real one.  The two paths are split so the seam is testable with no
    daemon and no ambient state — see behaviour 20's guard test.
    """

    def __init__(
        self, client: object, *, label_namespace: str, container_prefix: str
    ) -> None:
        """Store an already-built client; never build one from the environment.

        **This constructor must never read the ambient environment, touch
        ``~/.docker/config.json`` or build a client** — it takes what it is
        given.  That is the point of the seam: it is what lets behaviours
        21-26 be tested against a stub with no daemon.  Do not add a
        convenience default that would construct a client here.

        The ``client`` parameter is typed ``object`` on purpose: no
        client protocol is in the constructor's signature, because the
        guard test pins the constructor's *names and positions*, never
        its annotations, and both a stub and a real ``DockerClient``
        satisfy ``object``.  Behaviour 21 has since forced the one
        minimal protocol its call pair touches (``_BackendClient``,
        above); :meth:`start`, :meth:`stop` and :meth:`is_running`
        cast through it, and any later behaviour that needs a further
        member grows that protocol — never a speculative full client
        interface.

        Args:
            client: The already-built Docker client (or a test stand-in).
                Stored exactly as given — no wrapping, copying or
                re-derivation.
            label_namespace: Resolved label namespace, required and
                keyword-only; no default is re-stated here, matching the
                style of :func:`build_run_kwargs` and behaviours 6 and 7.
            container_prefix: Resolved container-name prefix, required and
                keyword-only; likewise no default.

        Raises:
            TypeError: ``client`` is ``None`` — a programming error at the
                seam, refused loudly rather than let through to an SDK call.
        """
        if client is None:
            raise TypeError("client must not be None")
        self.client = client
        self.label_namespace = label_namespace
        self.container_prefix = container_prefix

    def _fetch_container(self, container_id: str) -> _BackendContainer | None:
        """Look one container up by id, classifying the lookup's failures.

        Shared by :meth:`stop` (behaviour 22) and :meth:`is_running`
        (behaviour 23): both look the container up by its runtime id
        through ``client.containers.get`` — the saved single-container
        fetch, a full inspect that reports a missing container by
        raising ``NotFound`` (``plan/third-party-docs/docker/
        containers-list-filters.md`` §5,
        models/containers.py:939-952).

        A missing container is *state*, not an availability failure:
        this returns ``None`` and the caller gives it the no-op's
        shape — ``stop``'s early return, ``is_running``'s ``False`` —
        rather than raising.  The catch is deliberately scoped to
        ``docker.errors.NotFound``, **not** a blanket
        ``except Exception``: a dead daemon surfaces from this call as
        a bare ``requests`` connection error (``plan/
        third-party-docs/docker/errors.md`` §3, [CORRECTED
        2026-09-16]) and a daemon refusal as an ``APIError``, and both
        must route through :func:`map_sdk_error` and be raised rather
        than masquerade as an absent container — the no-op applies to
        *state*, never to *availability*.  ``NotFound`` is an
        ``APIError`` and hence a ``requests.exceptions.HTTPError``
        (errors.py:42, 92), so no connection error can ever match it —
        the scope is structurally, not accidentally, safe.

        Args:
            container_id: The runtime id to look up.

        Returns:
            The container object the daemon returned, or ``None``
            when the lookup reports the container missing.

        Raises:
            BackendError: a taxonomy member routed through
                :func:`map_sdk_error`, for every lookup failure that
                is not ``NotFound``.
        """
        client = cast(_BackendClient, self.client)
        try:
            return client.containers.get(container_id)
        except docker.errors.NotFound:
            # The container is gone — a state, not an availability
            # failure: the caller decides the no-op's shape.
            return None
        except Exception as exc:
            # Every other failure from the lookup — a daemon refusal, a
            # dead daemon — is routed through map_sdk_error.  A dead
            # daemon raises a requests connection error, which the
            # NotFound clause above cannot match, so it reaches here
            # and surfaces as BackendUnavailableError rather than a
            # swallowed no-op.
            raise map_sdk_error(exc) from exc

    def start(self, spec: ContainerSpec) -> ContainerHandle:
        """Start the container described by ``spec`` and return its handle.

        The whole method is the amended call pair (plan §5 behaviour
        21, amended — see behaviour 14's amendment for the why):

        1. ``client.containers.create(**build_run_kwargs(spec, ...))``;
        2. ``start()`` on the container object ``create`` returned;
        3. a :class:`ContainerHandle` carrying that container's ``id``
           plus the spec's ``name``, ``tool`` and ``image``.

        **No ``run`` call — and none may be added.**
        ``run(detach=True)`` returns before any exit check, so a
        container that dies immediately is indistinguishable from a
        clean start, and it auto-pulls a missing image, which would
        stop ``ImageNotFoundError`` from ever surfacing — the edge case
        this seam exists to keep honest
        (``plan/third-party-docs/docker/containers-run-create.md`` §1).
        No post-start ``reload()`` either: M2a claims nothing about
        detecting an immediate death; liveness is M2b's sweep (plan §5
        behaviour 14, amended).

        Every exception a call raises is routed through
        :func:`map_sdk_error` and the result is raised, so no raw SDK
        exception escapes the seam (plan §5 behaviour 21, error
        behaviour).  The mapping table itself is behaviour 19's and is
        not re-tested by this method.

        Args:
            spec: The fully resolved container spec to start.

        Returns:
            A :class:`ContainerHandle` identifying the started
            container.
        """
        client = cast(_BackendClient, self.client)
        try:
            container = client.containers.create(
                **build_run_kwargs(spec, label_namespace=self.label_namespace)
            )
            container.start()
        except Exception as exc:
            # Every SDK exception (all derive from
            # docker.errors.DockerException, an Exception) is routed
            # through map_sdk_error and the result is raised, so no raw
            # SDK exception escapes the seam.  KeyboardInterrupt /
            # SystemExit are deliberately not caught: they keep their
            # normal semantics rather than being re-labelled a backend
            # failure.
            raise map_sdk_error(exc) from exc
        return ContainerHandle(
            id=container.id, name=spec.name, tool=spec.tool, image=spec.image
        )

    def stop(self, handle: ContainerHandle, *, timeout_s: float) -> None:
        """Stop the identified container, or no-op when there is nothing to stop.

        The whole method is the call pair (plan §5 behaviour 22):

        1. the shared lookup :meth:`_fetch_container` for
           ``handle.id`` — ``client.containers.get``, the saved
           single-container fetch, which performs a full inspect,
           reports a missing container as ``None`` rather than raising,
           and routes every other lookup failure through
           :func:`map_sdk_error` (``plan/third-party-docs/docker/
           containers-list-filters.md`` §5,
           models/containers.py:939-952);
        2. ``stop(timeout=...)`` on the object the lookup returned,
           carrying the timeout in **int seconds** under the SDK's
           parameter name ``timeout`` (``plan/third-party-docs/docker/
           container-stop-wait.md`` §1, models/containers.py:441-453)
           — the call blocks until the daemon reports the container
           stopped.

        **The no-op contract (§4.3).**  A container the lookup reports
        *missing* (``NotFound``) or *already exited* (``status ==
        'exited'``, read through the ``status`` property — the only
        state path the saved reference marks [READ],
        ``plan/third-party-docs/docker/container-attrs-reload.md`` §3)
        is a no-op: ``stop`` returns ``None`` without calling the
        container's ``stop``.  ``FakeBackend.stop`` honours the same
        contract (behaviour 12), and M2b's liveness sweep relies on it.
        The ``NotFound`` no-op lives in the shared lookup
        :meth:`_fetch_container`, whose docstring carries the full
        reasoning: the catch is scoped to ``docker.errors.NotFound``,
        **not** a blanket ``except Exception``, so a dead daemon (a
        bare ``requests`` connection error,
        ``plan/third-party-docs/docker/errors.md`` §3, [CORRECTED
        2026-09-16]) routes to ``BackendUnavailableError`` rather than
        masquerade as a tidy shutdown: the no-op applies to *state*
        (missing, exited), never to *availability*.

        **The zero-timeout trap.**  ``timeout_s`` is converted with
        ``round(timeout_s)`` and passed **unconditionally** — there is
        no ``or None`` or any other falsy test.  The API layer drops
        the parameter only on a strict ``is None`` check (``api/
        container.py:1202-1206``), so a falsy drop of ``timeout_s=0``
        would send no ``t`` at all and the daemon's own configured
        ``StopTimeout`` — up to ten seconds — would apply instead of the
        requested immediate stop, indistinguishable to the caller.
        ``round`` (not ``int``) so a fractional ``timeout_s`` that
        lands just below the next whole second (e.g. ``1.9999999999``)
        is not silently truncated — the same reasoning as
        :func:`build_run_kwargs`'s nano-CPU conversion (behaviour 17).

        Every exception a call raises — except the ``NotFound`` no-op —
        is routed through :func:`map_sdk_error` and the result is
        raised, so no raw SDK exception escapes the seam; the mapping
        table itself is behaviour 19's and is not re-tested here.

        Args:
            handle: The container to stop.
            timeout_s: Seconds the daemon is allowed before it kills
                the container; ``0`` means immediate.

        Returns:
            ``None`` — both on a performed stop and on a no-op.
        """
        container = self._fetch_container(handle.id)
        if container is None:
            # The container is gone — a state, not an availability
            # failure: return without touching anything.
            return
        try:
            if container.status == "exited":
                return
            # Passed unconditionally — never `timeout_s or None` — so a
            # real zero reaches the daemon as {'t': 0}.  See the
            # zero-timeout trap in this method's docstring.
            container.stop(timeout=round(timeout_s))
        except Exception as exc:
            # Every SDK exception (all derive from
            # docker.errors.DockerException, an Exception) is routed
            # through map_sdk_error and the result is raised, so no raw
            # SDK exception escapes the seam.  KeyboardInterrupt /
            # SystemExit are deliberately not caught: they keep their
            # normal semantics rather than being re-labelled a backend
            # failure.
            raise map_sdk_error(exc) from exc

    def is_running(self, handle: ContainerHandle) -> bool:
        """Whether the container is running; ``False`` if it is gone.

        The same lookup :meth:`stop` (behaviour 22) performs, with a
        different answer (plan §5 behaviour 23; §4.3 contract
        decision):

        1. the shared lookup :meth:`_fetch_container` for
           ``handle.id`` — ``client.containers.get``, the saved
           single-container fetch (``plan/third-party-docs/docker/
           containers-list-filters.md`` §5,
           models/containers.py:939-952);
        2. read ``container.status`` — the one state property the saved
           reference marks [READ] (``plan/third-party-docs/docker/
           container-attrs-reload.md`` §3, containers.py:59-67) — and
           report whether it is the running state.

        **Only the running state is ``True``; everything else,
        including a state string nobody has enumerated, is ``False``.**
        The daemon's ``status`` vocabulary is an *open* set — no SDK
        line enumerates it (container-attrs-reload.md §3.1) — so the
        comparison is positive, ``status == "running"``, rather than a
        membership test against a list of known non-running states.
        An unrecognised value therefore reads ``False`` instead of
        raising or reading ``True``: the safe direction, since M2b's
        liveness sweep reaps what it believes is dead and must not reap
        a container it cannot read, nor turn a daemon vocabulary change
        into a watchdog traceback (plan §6 item 4).  Do not "tidy" this
        into a known-states list.

        **The not-found contract (§4.3).**  A container the lookup
        reports missing is ``False`` without raising: "``is_running``
        swallows not-found and returns ``False`` … Every other method
        raises."  The no-op is scoped to *state* (missing,
        non-running), never to *availability*: a dead daemon or a
        daemon refusal during the lookup is already raised by
        :meth:`_fetch_container` through :func:`map_sdk_error`, so a
        temporary outage cannot read as "every container is dead".
        ``FakeBackend.is_running`` honours the same contract
        (behaviour 12).

        Args:
            handle: The container to check.

        Returns:
            ``True`` only while the daemon reports the container in the
            running state; ``False`` when it is in any other state or
            has vanished.
        """
        container = self._fetch_container(handle.id)
        if container is None:
            # Vanished: a state, not an availability failure — the
            # §4.3 not-found contract, the same shape as stop's no-op.
            return False
        # Positive comparison against the running state — not a
        # membership test against known non-running states — because
        # the status vocabulary is an open set (container-attrs-reload.
        # md §3.1): an unrecognised value must read False, never raise
        # or read True.
        return container.status == "running"

    def inspect(self, handle: ContainerHandle) -> ContainerStatus:
        """Current status; ``ContainerState.GONE`` if the container is gone.

        The whole method is the behaviour-24 read (plan §5 behaviour 24;
        §4.3 contract decision):

        1. the shared lookup :meth:`_fetch_container` for ``handle.id`` —
           ``client.containers.get``, the saved single-container fetch,
           which performs a full inspect, reports a missing container
           as ``None`` rather than raising, and routes every other
           lookup failure through :func:`map_sdk_error` (``plan/
           third-party-docs/docker/containers-list-filters.md`` §5,
           models/containers.py:939-952).  No ``reload()``: ``get``'s
           returned object already carries a fresh inspect
           (``plan/third-party-docs/docker/container-attrs-reload.md``
           §1-2).
        2. the state is read through ``container.status`` — the one
           state path the saved reference marks **[READ]**
           (container-attrs-reload.md §3, containers.py:59-67), mapped
           onto :class:`ContainerState` below;
        3. the exit code and start time are read from the container's
           ``attrs`` — the raw inspect dict (container-attrs-reload.md
           §1, **[READ]**) — at ``State.ExitCode`` and
           ``State.StartedAt``, both **[INFERRED]** (see
           ``_state_exit_code`` and ``_state_started_at``).

        **The exit-code route, and why not ``wait()``.**  The one
        exit-code path with SDK code behind it is
        ``wait()['StatusCode']`` (container-attrs-reload.md §3.1,
        **[READ]**), but ``wait()`` **blocks until the container
        exits** — for a running container that is unbounded, so an
        inspect built on it would hang M2b's liveness poller on every
        healthy container.  ``inspect`` is a point-in-time reading
        (``ContainerStatus``'s own docstring), and the attrs route is
        the only non-blocking read available; its keys are therefore
        pinned as **[INFERRED]**, to be confirmed by the deferred
        live-daemon test (container-attrs-reload.md §3.1 point 4).

        **The state mapping, and the load-bearing edge.**  The
        daemon's ``status`` vocabulary is an *open* set — no SDK line
        enumerates it (container-attrs-reload.md §3.1) — so only the
        strings with enum members are recognised: ``created`` →
        ``CREATED``, ``running`` → ``RUNNING``, ``exited`` → ``EXITED``.
        **Every other string — ``paused``, ``restarting``, or a value
        nobody has ever seen — maps to ``EXITED`` with a logged warning
        rather than raising**: the safe direction, since a liveness
        sweep that believes an unrecognised container is running will
        never reap it (plan §6 item 4), and the warning keeps the
        misreport visible.  The comparison is a string ``==`` against
        each known value, never an ``Enum[str]``-style lookup, so an
        unknown string cannot raise — behaviour 23's lesson.
        ``GONE`` is reserved for the not-found path: the daemon never
        reports it as a ``status`` string, so no status value maps to
        it.

        **Only the literally-exited state carries the exit code.**
        ``exit_code`` is read from attrs **only when the daemon
        reports ``exited``**: a ``created`` or ``running`` container
        has exited neither successfully nor at all, and passing the
        daemon's ``0`` through for either would report a clean exit
        that never happened — the same reasoning base.py's
        ``None``-rather-than-``0`` default encodes.  An
        **unrecognised** state likewise carries ``exit_code=None``:
        the daemon's own status string is untrusted, so its numeric
        fields cannot carry authority either.  ``started_at`` is
        passed through verbatim as a plain string — no coercion to
        ``datetime`` (base.py) — and is ``None`` for a missing
        container and for an unrecognised state, for the same
        authority reason as the exit code.

        **The not-found contract (§4.3).**  A container the lookup
        reports missing is ``GONE`` with ``exit_code=None`` and
        ``started_at=None``, without raising: the absent container has
        exited neither successfully nor at all, so no field is
        invented about it, and M2b's reconciliation relies on the read
        never turning into a traceback.  ``FakeBackend.inspect``
        honours the same contract (behaviour 12).  The no-op applies
        to *state* (missing), never to *availability*: a dead daemon
        or a daemon refusal during the lookup is already raised by
        :meth:`_fetch_container` through :func:`map_sdk_error`, so a
        temporary outage cannot read as "every container is gone".

        Args:
            handle: The container to inspect.

        Returns:
            A point-in-time status for the handle, or a
            ``ContainerState.GONE`` status carrying the handle as
            given when the lookup reports it missing.

        Raises:
            BackendError: a taxonomy member routed through
                :func:`map_sdk_error`, for every lookup failure that
                is not ``NotFound`` — the mapping table itself is
                behaviour 19's and is not re-tested here.
        """
        container = self._fetch_container(handle.id)
        if container is None:
            # Vanished: a state, not an availability failure — the
            # §4.3 not-found contract, the same shape as stop's no-op
            # and is_running's False.  Nothing is invented about a
            # container no one can ask about.
            return ContainerStatus(handle=handle, state=ContainerState.GONE)
        # Positive string comparisons — not an enum lookup — because
        # the status vocabulary is an open set (container-attrs-reload.
        # md §3.1): an unrecognised value must map to the safe EXITED
        # branch with a warning, never raise.  GONE is deliberately
        # absent: no daemon status value maps to it.
        status = container.status
        if status == "created":
            state = ContainerState.CREATED
            exit_code = None
            started_at = _state_started_at(container.attrs)
        elif status == "running":
            state = ContainerState.RUNNING
            exit_code = None
            started_at = _state_started_at(container.attrs)
        elif status == "exited":
            state = ContainerState.EXITED
            exit_code = _state_exit_code(container.attrs)
            started_at = _state_started_at(container.attrs)
        else:
            # The load-bearing edge: an unrecognised vocabulary value
            # maps to the terminal EXITED state and logs a warning
            # naming it — never raises, never RUNNING (a sweep that
            # believes it is running never reaps it), never CREATED
            # (which would block readiness logic expecting a terminal
            # state).  Its numeric fields are untrusted, so they stay
            # None.
            logger.warning(
                "unrecognised container state %r reported by the "
                "daemon; reporting it as exited with no exit code",
                status,
            )
            state = ContainerState.EXITED
            exit_code = None
            started_at = None
        return ContainerStatus(
            handle=handle,
            state=state,
            exit_code=exit_code,
            started_at=started_at,
        )

    def list_managed(self) -> list[ContainerHandle]:
        """Every managed container, stopped ones included.

        The whole method is the behaviour-25 read (plan §5 behaviour
        25; §6 item 5): one ``client.containers.list`` call with the
        pinned shape, then one :class:`ContainerHandle` per container
        that carries our labels.

        **The pinned call shape**
        (``plan/third-party-docs/docker/containers-list-filters.md``):

        1. ``all=True`` as a **parameter** — only running containers
           are shown by default (§2, lines 27-34), and there is
           **no** ``all=`` in the label-filter dict, so a filter key
           cannot substitute; reconciliation must see an exited
           container (§6 item 5), which is the edge only this
           parameter covers;
        2. ``filters={"label": "key=value"}`` — the one-entry map of
           :func:`label_selector` (behaviour 7) translated into the
           ``label`` filter's ``"key=value"`` string form (§3, line
           47 — one of the three accepted forms, and the one the
           docstring's own example uses).  The entry is derived by
           *calling* ``label_selector`` with the resolved namespace,
           never restated, so the filter cannot drift from the map
           the containers were stamped with;
        3. ``ignore_removed=True`` — the documented remedy for a
           container vanishing between the list call and its per-item
           inspect (§4, lines 87-91);
        4. **no ``sparse``** — ``sparse=True`` skips the per-item
           inspect and the ``labels`` property then raises (§4, lines
           79-99), which would defeat the behaviour: ``tool`` is
           recovered from a label.

        **Not claimed here:** whether the daemon's label selector
        really selects.  The SDK performs no client-side
        interpretation of ``filters`` (§3, lines 65-67) — the daemon
        is the authority, and that half is deferred docker test 1
        (plan §5 behaviour 25).  This method passes the filter; the
        daemon decides what it matches.

        **``tool`` from the label, never from the name.**  The
        handle's ``tool`` is read from the ``{namespace}.model``
        label — the same namespace-derived key
        :func:`managed_labels` stamps (``labels.py``;
        plan/08_REPO_LAYOUT.md §2) — because the name is
        ``prefix + tool`` (behaviour 7) and a container started under
        a different prefix would parse to the wrong tool:
        reconciliation adopts by label (§6 item 5), so a name-derived
        tool would be reconciled against the wrong entry.  The name
        itself is reported verbatim — the SDK's own
        ``attrs['Name'].lstrip('/')`` derivation (container-attrs-
        reload.md §3, containers.py:28-34) — as a field, not a
        source.

        **Ours only, the rest skipped.**  A container is ours when
        every :func:`label_selector` entry matches its labels; a
        foreign container is skipped **silently** — the warning is
        reserved for the next case.  A container that is ours but
        carries no model label (or an empty one) is skipped with a
        logged warning naming it by name and id, and the surviving
        containers are still returned: one malformed container must
        not deny the caller the rest (§6 item 5: reconciliation
        adopts by label at boot, so a crash here takes out
        boot-time reconciliation, and a silent skip would make an
        unadoptable container invisible in production).

        **Daemon errors are routed, not swallowed.**  Every exception
        the call or the reads raise is routed through
        :func:`map_sdk_error` and the result is raised, so no raw SDK
        exception escapes the seam: a dead daemon surfaces
        ``BackendUnavailableError`` (behaviour 19) and a daemon
        refusal its own taxonomy member — returning ``[]`` for either
        would read an outage as "nothing is managed", and
        reconciliation would then adopt nothing and reap live
        containers.  ``KeyboardInterrupt`` / ``SystemExit`` are
        deliberately not caught.  The mapping table itself is
        behaviour 19's and is not re-tested here.

        The handle's ``id`` (``attrs['Id']`` — resource.py:28-40) and
        ``name`` are **[READ]** SDK derivations (container-attrs-
        reload.md §3); the handle's ``image`` is read from
        ``attrs['Config']['Image']`` — **[INFERRED]**, the
        Engine-API sibling of the [READ] ``Config.Labels`` read the
        ``labels`` property just performed (containers-list-filters.
        md §3; container-attrs-reload.md §3): no saved page records
        an SDK image property, so the read rests on the Engine API
        contract, not SDK source, and the red-step stub deliberately
        exposes no ``image`` member so an unrecorded property fails
        loudly here instead of passing on memory.

        Returns:
            A :class:`ContainerHandle` per managed container the
            daemon lists, stopped ones included; ``[]`` when none
            match — a *filtered* empty, the call still carrying the
            pinned filter.

        Raises:
            BackendError: a taxonomy member routed through
                :func:`map_sdk_error`, for every daemon failure —
                the mapping table itself is behaviour 19's and is
                not re-tested here.
        """
        client = cast(_BackendClient, self.client)
        # The one selector entry in the label filter's "key=value"
        # string form (containers-list-filters.md §3).  The unpack
        # makes a changed entry count fail loudly rather than
        # silently change the pinned call shape.
        selector = label_selector(self.label_namespace)
        (label_filter,) = [f"{key}={value}" for key, value in selector.items()]
        try:
            containers = client.containers.list(
                all=True, filters={"label": label_filter}, ignore_removed=True
            )
            handles: list[ContainerHandle] = []
            for container in containers:
                labels = container.labels
                # Ours only when every selector entry matches — a
                # foreign container is skipped silently: the warning
                # below is reserved for one of ours that is malformed.
                if not all(labels.get(key) == value for key, value in selector.items()):
                    continue
                # The model label — the same namespace-derived key
                # managed_labels stamps (labels.py; plan/08_REPO_
                # LAYOUT.md §2): derived from the namespace here,
                # never a restated string, and never parsed from the
                # name.
                tool = labels.get(f"{self.label_namespace}.model")
                if not tool:
                    # Ours but malformed: warn, naming the container
                    # by name and id, and skip — one broken container
                    # must not deny the caller the rest (§6 item 5).
                    logger.warning(
                        "container %s (%s) carries the managed-by label but "
                        "no model label; skipping it",
                        container.name,
                        container.id,
                    )
                    continue
                # The image: **[INFERRED]** — attrs['Config']['Image'],
                # the Engine-API sibling of the [READ] Config.Labels
                # the labels read above already required (containers-
                # list-filters.md §3; container-attrs-reload.md §3);
                # no saved page records an SDK image property.  A
                # shape the daemon never returns falls through to the
                # map_sdk_error route below, never a silent default.
                config = cast(Mapping[str, object], container.attrs["Config"])
                handles.append(
                    ContainerHandle(
                        id=container.id,
                        name=container.name,
                        tool=tool,
                        image=str(config["Image"]),
                    )
                )
            return handles
        except Exception as exc:
            # Every SDK exception (all derive from
            # docker.errors.DockerException, an Exception) is routed
            # through map_sdk_error and the result is raised, so no
            # raw SDK exception escapes the seam and no outage reads
            # as an empty fleet.  KeyboardInterrupt / SystemExit are
            # deliberately not caught: they keep their normal
            # semantics rather than being re-labelled a backend
            # failure.
            raise map_sdk_error(exc) from exc

    def logs(
        self, handle: ContainerHandle, *, follow: bool, tail: int
    ) -> Iterator[str]:
        """Log lines of the container, reassembled and decoded.

        The whole method is the behaviour-26 read (plan §5 behaviour
        26; §4.3 contract decision):

        1. the shared lookup :meth:`_fetch_container` for ``handle.id``
           — ``client.containers.get``, the saved single-container
           fetch (``plan/third-party-docs/docker/
           containers-list-filters.md`` §5,
           models/containers.py:939-952);
        2. ``container.logs(stream=True, follow=follow, tail=tail)`` —
           the pinned call shape below;
        3. the byte chunks the call returns, reassembled into lines by
           :func:`_iter_log_lines`.

        **The pinned call shape.**  ``stream`` is always ``True``:
        only the streaming form yields the chunks the seam
        reassembles into lines — the non-streaming form returns the
        whole log as one ``bytes`` blob, and nothing is left to rejoin
        (``plan/third-party-docs/docker/container-logs.md`` §2,
        [READ]).  ``follow`` is passed **explicitly, never omitted**:
        the SDK's ``follow`` defaults to ``None`` and ``if follow is
        None: follow = stream`` (same page §1, kwarg table), so an
        omitted ``follow`` with ``stream=True`` would turn a
        ``follow=False`` request into a stream that follows forever.
        ``tail`` is passed through **verbatim, ``0`` included** — no
        falsy test: the SDK treats ``0`` as valid while silently
        resetting only *invalid* values (< 0, non-int) to ``'all'``
        (same page §1, lines 860-861), and ``'all'`` is unbounded
        (same page §3) — the same trap class behaviour 22 pinned for
        ``timeout_s=0``.  No ``stdout`` / ``stderr`` / ``timestamps``
        / ``since`` / ``until`` — their defaults (``True`` / ``True``
        / ``False`` / ``None`` / ``None``, same page §1 kwarg table)
        are what the seam wants.

        **The line contract is ours, not an SDK fact.**  The SDK hands
        over raw ``bytes`` and says nothing about line framing (same
        page §2, [READ]: "the caller must ``.decode(...)``
        explicitly") — so :func:`_iter_log_lines` splits on ``b"\\n"``
        only, yields each line stripped of its trailing newline,
        decodes with ``errors="replace"`` so one bad byte cannot kill
        the stream, and flushes a trailing partial line at the end of
        the stream rather than dropping it.

        **The not-found contract (§4.3) inverts here.**  ``is_running``
        (behaviour 23), ``inspect`` (24) and ``stop`` (22) are the
        only methods the not-found no-op is granted; "every other
        method raises", and ``logs`` is one of the others.  A
        container the lookup reports *missing* therefore raises
        :class:`ContainerNotFoundError` — **raised eagerly, on the
        call, not on the first ``next()``**: asking for the log of a
        container that is not there is a caller error to be answered,
        not a state to be absorbed, and ``FakeBackend.logs`` honours
        the same contract (behaviour 13) — the one place in the slice
        where fake/docker parity means *both raise*.  An empty
        iterator instead would read an out-of-band removal as "an
        empty log", the exact behaviour §4.3 forbids for ``logs``.
        The no-op applies to *state* (missing) for the three lenient
        methods, never to *availability*: a dead daemon or a daemon
        refusal during the lookup is already raised by
        :meth:`_fetch_container` through :func:`map_sdk_error` —
        ``BackendUnavailableError`` for a dead daemon (behaviour 19) —
        and ``logs`` lets it through rather than reading the outage
        as "the container is missing".

        **A follow stream can end quietly — recorded, not fixed.**
        The saved page §2 ([CORRECTED 2026-09-16]; ``CancellableStream``
        lives at ``types/daemon.py:8``, not ``utils/socket.py``)
        records that ``__next__`` converts ``ProtocolError`` **and**
        ``OSError`` into ``StopIteration`` (``types/daemon.py:27-33``,
        [READ]): a follow stream broken by a dying daemon **ends
        quietly**, and a truncated log is indistinguishable from a
        complete one.  This method adds no retry, sentinel or error
        detection for it — the hazard is unobservable without a
        daemon (no daemon runs in M2a's test environment), and
        "logs survive a stop" is M7's requirement (plan §1).  M7's
        log collector inherits the hazard from this API; see
        ``plan/third-party-docs/docker/container-logs.md`` §2.

        Args:
            handle: The container to read the log of.
            follow: Whether to follow the log past its current end;
                passed to the daemon verbatim, always explicit.
            tail: How many trailing lines the daemon should return,
                passed verbatim — ``0`` included.

        Returns:
            An iterator over the log, one decoded line per item, each
            without its trailing newline.

        Raises:
            ContainerNotFoundError: the lookup reports the container
                missing — raised on the call, before any line is
                yielded (§4.3: every method other than ``is_running``,
                ``inspect`` and ``stop`` raises).
            BackendError: a taxonomy member routed through
                :func:`map_sdk_error`, for every lookup failure that
                is not ``NotFound`` — the mapping table itself is
                behaviour 19's and is not re-tested here.
        """
        container = self._fetch_container(handle.id)
        if container is None:
            # Vanished: the §4.3 not-found contract, inverted for
            # logs — every method other than is_running / inspect /
            # stop raises.  Raised eagerly, on the call: a missing
            # container is a caller error to be answered, not an
            # empty log to be absorbed, and FakeBackend.logs raises
            # the same member for the same input (behaviour 13).
            raise ContainerNotFoundError(
                f"Container {handle.id} not found — its log cannot be read"
            )
        # The lookup's non-NotFound failures already raised in
        # _fetch_container (a dead daemon surfaces as
        # BackendUnavailableError there), so this branch is reached
        # only for a live daemon and a present container.  The stream
        # is opened on the call — not deferred to the first next() —
        # so a refusal surfaces where the caller holds the call, not
        # part-way through a half-read log.
        stream = container.logs(stream=True, follow=follow, tail=tail)
        return _iter_log_lines(stream)

    @classmethod
    def from_config(cls, cfg: BackendConfig) -> DockerBackend:
        """Build a backend from a :class:`BackendConfig`, creating a real client.

        The **only** path permitted to construct a real client (plan §4.5):
        the injected-client constructor is environment-free, so this factory
        is where the ambient state is read, via ``docker.from_env()`` — the
        SDK's documented env-reading entry point
        (``plan/third-party-docs/docker/client-construction-and-env.md`` §1).

        ``docker.from_env()`` passes no explicit ``version``, so the underlying
        ``APIClient.__init__`` performs a **live daemon round-trip** to
        negotiate the API version (``client-construction-and-env.md`` §4).
        That is inherent to building a real client: there is no
        ``BackendConfig`` field carrying a pinned API version, so the
        round-trip cannot be suppressed without either inventing a config
        field nothing demands or hard-coding a daemon-specific version — both
        worse than the failure this produces.  A dead daemon surfaces that
        round-trip's ``DockerException`` ("Error while fetching server API
        version: …"), which :func:`map_sdk_error` already maps to
        ``BackendUnavailableError``.  Behaviour 20 does not exercise this
        method (it would need a daemon); its behaviour belongs to a later
        ledger entry.

        Args:
            cfg: The resolved backend configuration block; supplies
                ``label_namespace`` and ``container_prefix``.

        Returns:
            A :class:`DockerBackend` whose ``client`` is the real client
            built from the ambient environment.
        """
        return cls(
            docker.from_env(),
            label_namespace=cfg.label_namespace,
            container_prefix=cfg.container_prefix,
        )
