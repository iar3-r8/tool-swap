"""Docker translation layer for the container backend seam (M2a).

This module holds the pure half of the Docker backend: plan
behaviours 14-19 of ``plans/m2a-container-backend-seam.md``.
:func:`build_run_kwargs` translates a
:class:`~tool_swap.backend.base.ContainerSpec` into the kwargs dict
that ``DockerBackend.start`` (behaviour 21) passes to
``client.containers.create``; :func:`map_sdk_error` translates an SDK
exception — or anything else — into a member of the seven-member
taxonomy of :mod:`tool_swap.backend.errors` for the caller to raise.

Responsibility: every docker-py fact the backend needs — the kwarg
names, the device-request shape, the exception classification —
lives in these functions rather than in a class, so the shell that
will call them stays thin (plan §4.5) and every fact is
table-testable with no client and no daemon.

The thin shell itself — :class:`DockerBackend` — is behaviour 20: a
constructor that takes an **already-built** client and never reads
the ambient environment, plus a ``from_config`` classmethod that is
the only path permitted to build a real one (behaviours 21-27 add
the protocol methods and the import-linter contract on top).

Boundary: this module is the only ``tool_swap`` module that imports
the Docker SDK; the import-linter contract that enforces that is
behaviour 27 and is not in the tree yet.  Nothing here was verified
against a running daemon.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

import docker
import docker.errors
import requests.exceptions
from docker.types import DeviceRequest

from tool_swap.backend.base import (
    ContainerHandle,
    ContainerSpec,
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
from tool_swap.backend.labels import managed_labels

if TYPE_CHECKING:
    # Annotation-only: ``from_config``'s parameter is the only use, and
    # a runtime ``backend -> config`` import would re-couple the
    # backend's import graph to the config layer, which plan §4.2
    # deliberately kept free (the edge is structurally legal per
    # .importlinter contract 3, but still avoided).
    from tool_swap.config.schema import BackendConfig

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


class _BackendContainer(Protocol):
    """The object ``containers.create`` / ``containers.get`` returns,
    as far as ``start`` (behaviour 21) and ``stop`` (behaviour 22)
    touch it.

    A real object is a ``docker.models.containers.Container`` —
    ``id`` the runtime id, ``status`` the state property
    (``running``, ``exited``, …;
    ``plan/third-party-docs/docker/container-attrs-reload.md`` §3),
    ``start`` and ``stop`` methods
    (``plan/third-party-docs/docker/containers-run-create.md`` §4;
    ``plan/third-party-docs/docker/container-stop-wait.md`` §1,
    models/containers.py:441-453); the behaviour-21/22 recording stubs
    carry exactly the members each path uses, so this is also the
    widest shape either stub allows.
    """

    #: The runtime id the container is known by.
    id: str

    #: The state the daemon reports (``running``, ``exited``, …).
    status: str

    def start(self, **kwargs: object) -> None:
        """Start the container; the SDK's ``Container.start(**kwargs)``."""
        ...

    def stop(self, **kwargs: object) -> None:
        """Stop the container; the SDK's ``Container.stop(**kwargs)``."""
        ...


class _BackendContainers(Protocol):
    """The ``client.containers`` collection, as far as ``start`` and
    ``stop`` touch it.

    Two members: ``create`` (behaviour 21) and ``get`` (behaviour 22),
    both returning :class:`_BackendContainer`.  The image is declared
    keyword-only because the behaviour-21 stub records an explicitly
    passed ``image=`` into its kwargs dict, and the SDK's ``create``
    also accepts it as a keyword (it re-sets ``kwargs['image']``
    itself —
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


class _BackendClient(Protocol):
    """The minimal client shape the behaviour-21/22 call pairs call
    through.

    Kept to exactly what those call pairs touch — a ``containers``
    collection, nothing more — **not** a speculative full client
    interface: behaviours 23-26 will force any further members when
    they land.  ``containers`` is a plain attribute member (not a
    property), matching how both a real ``docker.DockerClient`` and
    the behaviour-21/22 recording stubs carry it — set in
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
        above); :meth:`start` and :meth:`stop` cast through it, and any
        later behaviour
        that needs a further member grows that protocol — never a
        speculative full client interface.

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

        1. ``client.containers.get(handle.id)`` — the saved single-container
           fetch, which performs a full inspect and raises ``NotFound`` when
           the container is missing (``plan/third-party-docs/docker/
           containers-list-filters.md`` §5, models/containers.py:939-952);
        2. ``stop(timeout=...)`` on the object ``get`` returned, carrying the
           timeout in **int seconds** under the SDK's parameter name
           ``timeout`` (``plan/third-party-docs/docker/
           container-stop-wait.md`` §1, models/containers.py:441-453) — the
           call blocks until the daemon reports the container stopped.

        **The no-op contract (§4.3).**  A container the lookup reports
        *missing* (``NotFound``) or *already exited* (``status ==
        'exited'``, read through the ``status`` property — the only
        state path the saved reference marks [READ],
        ``plan/third-party-docs/docker/container-attrs-reload.md`` §3)
        is a no-op: ``stop`` returns ``None`` without calling the
        container's ``stop``.  ``FakeBackend.stop`` honours the same
        contract (behaviour 12), and M2b's liveness sweep relies on it.
        The catch is deliberately scoped to ``docker.errors.NotFound``
        — **not** a blanket ``except Exception`` — because a dead daemon
        surfaces from this call pair as a bare ``requests`` connection
        error (``plan/third-party-docs/docker/errors.md`` §3,
        [CORRECTED 2026-09-16]), which must route to
        ``BackendUnavailableError`` rather than masquerade as a tidy
        shutdown: the no-op applies to *state* (missing, exited), never
        to *availability*.  ``NotFound`` is an ``APIError`` and hence a
        ``requests.exceptions.HTTPError`` (errors.py:42, 92), so no
        connection error can ever match it — the scope is
        structurally, not accidentally, safe.

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
        client = cast(_BackendClient, self.client)
        try:
            container = client.containers.get(handle.id)
        except docker.errors.NotFound:
            # The container is gone — a state, not an availability
            # failure: return without touching anything.
            return
        except Exception as exc:
            # Every other failure from the lookup — a daemon refusal, a
            # dead daemon — is routed through map_sdk_error.  A dead
            # daemon raises a requests connection error, which the
            # NotFound clause above cannot match, so it reaches here
            # and surfaces as BackendUnavailableError rather than a
            # swallowed no-op.
            raise map_sdk_error(exc) from exc
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
