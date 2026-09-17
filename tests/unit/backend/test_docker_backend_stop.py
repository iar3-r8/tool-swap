"""RED step for M2a behaviour 22 — ``DockerBackend.stop``.

See ``plans/m2a-container-backend-seam.md`` behaviour 22 (§5) and the §4.3
contract decision.  ``stop(handle, *, timeout_s)`` (the signature is
already pinned by the ``ContainerBackend`` protocol in
``src/tool_swap/backend/base.py``, behaviour 8) must:

1. **look the container up by the handle's id** — ``client.containers.get``
   (``plan/third-party-docs/docker/containers-list-filters.md`` §5: ``get``
   at models/containers.py:939 accepts a name or ID, performs a full
   inspect and *raises ``NotFound`` if missing*, lines 950-952; it is the
   same call ``list`` uses internally — line 1019 — so its ``NotFound``
   is the documented race);
2. **call ``stop`` once on the identified container** — on the object,
   not on the client — carrying the timeout **in seconds** under the
   SDK's parameter name ``timeout``
   (``plan/third-party-docs/docker/container-stop-wait.md`` §1:
   ``Container.stop(**kwargs)`` at models/containers.py:441-453 forwards
   to ``client.api.stop(self.id, **kwargs)``; ``APIClient.stop(self,
   container, timeout=None)`` at api/container.py:1187 — the docstring
   says "Timeout in **seconds**" and the type is ``int``);
3. **no-op, not error, when the container is missing or already exited**
   — §4.3: "``is_running`` swallows not-found and returns ``False``;
   ``inspect`` returns ``GONE``; ``stop`` on a missing container is a
   no-op. Every other method raises."  This is one half of a pair:
   ``FakeBackend.stop`` already implements the same contract
   (behaviour 12, ``src/tool_swap/backend/fake_backend.py`` — "A no-op —
   not an error — when the container is already exited or has vanished"),
   and the plan says the two must agree or the fast unit tests rest on a
   lie.  ``test_stop_no_op_contract_matches_fake_backend`` runs the same
   three scenarios through both backends and demands the same
   observable outcome.

**The timeout conversion, pinned.**  The protocol takes
``timeout_s: float``; the SDK's parameter is an ``int`` in seconds, and
the API layer drops the parameter **only** on a strict ``None`` check —
``if timeout is None: params = {}`` else ``params = {'t': timeout}``
(``container-stop-wait.md`` §1, re-verified 2026-09-16 against
``.venv/lib/python3.11/site-packages/docker/api/container.py:1202-1206``).
The seam must therefore convert *float seconds → int seconds* and must
**never treat zero as absent**: ``timeout_s=0`` has to reach the SDK as
a real ``0`` (sending ``{'t': 0}``), because a falsy drop (``timeout_s or
None``) would send no ``t`` at all and the daemon's own configured
``StopTimeout`` — up to ten seconds — would apply instead of the
requested immediate stop.
``test_stop_passes_zero_timeout_through_instead_of_dropping_it`` makes
that distinguishable: the recorded value must equal ``0``, be ``is not
None`` and be of type ``int``.  Fractional rounding (e.g. ``2.5``) is
**not** pinned: no saved document names the rounding mode, and pinning
one would invent a fact.

**``stop`` blocks until the daemon reports the container stopped and
returns ``None``** (``container-stop-wait.md`` §1: the POST to
``/containers/{id}/stop`` is awaited, the method has no return
statement, non-2xx raises ``APIError``).  Whether the daemon really
returns before the container exits is the deferred docker test 2 —
**explicitly not claimed here** (behaviour 22, "Verified").

**Daemon-unreachable is NOT not-running.**  A dead daemon surfacing from
an operational call is a bare ``requests`` connection error that
behaviour 19 maps to ``BackendUnavailableError``
(``plan/third-party-docs/docker/errors.md`` §3, [CORRECTED 2026-09-16]:
a connection failure on a later API call is never wrapped, so it
propagates out of ``requests`` as-is) — never a swallowed no-op:
swallowing it would make a dead daemon look like a tidy shutdown.
``test_stop_on_dead_daemon_surfaces_backend_unavailable_not_a_no_op``
pins the distinction.

**The shell is thin on purpose (plan §4.5).**  ``map_sdk_error``'s
mapping table is behaviour 19's and is *not* re-tested here — only that
``stop`` *routes* every SDK exception it catches through it
(``raise map_sdk_error(exc) from exc`` — the behaviour-21 pattern — so
the raw exception is chained as ``__cause__`` and never escapes).

**The stub's fidelity, and the trap this decision avoids.**  As in
behaviour 21, the stub records and never fails on its own: the ``stop``
path wraps its calls in ``except Exception`` (the committed behaviour-21
pattern), so any ``AttributeError``/``TypeError`` raised *inside* a
stub method would be routed through ``map_sdk_error`` and surface as a
``BackendError`` that looks like an implementation fault and is a test
fault instead.  Construction is plain (no dataclass ``__post_init__``),
signatures match the SDK's (``get(self, container_id)`` —
models/containers.py:939; ``Container.stop(self, **kwargs)`` —
models/containers.py:441), and the only exceptions that ever leave a
stub method are SDK exceptions *prepared in the test body* — the
stub raises what it is given, verbatim, after recording.  The stub
container exposes exactly ``id``, ``status`` and ``stop`` plus its call
record — **not** ``attrs`` and **not** ``reload``: ``status`` is the
only state-readable property the saved reference marks [READ]
(``plan/third-party-docs/docker/container-attrs-reload.md`` §3 —
``attrs['State']['Status']``, containers.py:59-67), while the raw
``attrs`` state key names are [INFERRED]; providing ``attrs`` would let
the implementation take an unverified path validated only by fixture
keys the test itself wrote.  An unexpected attribute on the stub
therefore raises ``AttributeError`` — a backend reaching past
``get``/``Container.stop`` fails loudly.

The ``isinstance(backend, ContainerBackend)`` conformance pin is
deliberately **absent**: ``isinstance`` matches on member *names* and
every one of the six must be present, while ``DockerBackend`` carries
only ``start`` so far.  The pin is behaviour 26's, where the class is
complete — one behaviour, one cycle.

This file is the RED step: ``DockerBackend`` exists (behaviour 20) with
``start`` (behaviour 21) but no ``stop``, so every subject test fails
*individually* at the attribute-level gate with its assertions present
and reachable — never aborting pytest collection.  No ``importorskip``,
no skips.

Conventions: pytest, AAA, Google-style docstrings, Black at 88 columns,
ruff, ``filterwarnings = "error"`` — no test asserts a docker fact from
memory; each is cited to the saved reference above.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from types import ModuleType
from typing import Any, cast

import docker.errors
import pytest
import requests

from tool_swap.backend.base import ContainerHandle, ContainerSpec
from tool_swap.backend.errors import BackendError, BackendUnavailableError
from tool_swap.backend.fake_backend import FakeBackend

# Neutral label namespace, deliberately distinct from any configured
# default — the discipline of test_docker_backend_start.py, which uses
# "com.acme".
_NAMESPACE = "com.acme"

# The runtime id both the handle and the stub container carry, so "stop
# the identified container" is an identity check against one object.
_CONTAINER_ID = "deadbeef"

_URL = "http://docker/v1.45/containers/deadbeef/stop"


# ---------------------------------------------------------------------------
# The RED gate (attribute-level, per behaviours 19/20/21's committed pattern)
# ---------------------------------------------------------------------------


def _get_docker_backend_module() -> ModuleType:
    """Import ``tool_swap.backend.docker_backend`` at call time.

    The import is deferred out of module scope via
    ``importlib.import_module`` so a missing module could not abort pytest
    *collection* of this file.  While the module is absent this raises
    ``AssertionError`` naming the missing module, so every test fails
    individually instead of the run being interrupted.

    Raises:
        AssertionError: ``tool_swap.backend.docker_backend`` does not
            exist yet.
    """
    try:
        module: ModuleType = importlib.import_module("tool_swap.backend.docker_backend")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tool_swap.backend.docker_backend is missing — the GREEN step "
            "must create src/tool_swap/backend/docker_backend.py"
        ) from exc
    return module


def _backend_with(stub: _RecordingClient) -> object:
    """Construct ``DockerBackend(stub, …)`` with ``stop`` present.

    While ``stop`` is absent this raises ``AssertionError`` naming the
    missing method, so the subject tests fail individually rather than
    aborting the run.

    Args:
        stub: The recording client to inject.

    Returns:
        The constructed backend.

    Raises:
        AssertionError: the module or the ``DockerBackend`` class is
            missing, or the class still defines no ``stop`` method — the
            GREEN step must add it to
            ``src/tool_swap/backend/docker_backend.py``.
    """
    module = _get_docker_backend_module()
    try:
        backend_cls = module.DockerBackend
    except AttributeError as exc:
        raise AssertionError(
            "tool_swap.backend.docker_backend.DockerBackend is missing — "
            "the GREEN step must define the DockerBackend class in "
            "src/tool_swap/backend/docker_backend.py"
        ) from exc
    backend_cls = cast(type, backend_cls)
    if not hasattr(backend_cls, "stop"):
        raise AssertionError(
            "DockerBackend.stop is missing — the GREEN step must add the "
            "stop method to src/tool_swap/backend/docker_backend.py "
            "(behaviour 22)"
        )
    return backend_cls(stub, label_namespace=_NAMESPACE, container_prefix="ms-")


# ---------------------------------------------------------------------------
# The fixtures
# ---------------------------------------------------------------------------


def _handle() -> ContainerHandle:
    """The handle whose container ``stop`` must identify by ``id``."""
    return ContainerHandle(
        id=_CONTAINER_ID, name="ms-llama", tool="llama", image="example/tool:1.0"
    )


def _spec() -> ContainerSpec:
    """A minimal spec for the ``FakeBackend`` half of the agreement test."""
    return ContainerSpec(
        tool="llama",
        name="ms-llama",
        image="example/tool:1.0",
        gpu_runtime="cuda",
        container_port=8080,
    )


# ---------------------------------------------------------------------------
# The recording stub
# ---------------------------------------------------------------------------


@dataclass
class _RecordedGet:
    """One recorded ``get`` call: the container id it was asked for."""

    container_id: str


class _RecordingContainer:
    """A stand-in for the ``Container`` object ``get`` returns.

    The real object is a ``docker.models.containers.Container``: ``id``
    the runtime id, ``status`` the state property
    (``plan/third-party-docs/docker/container-attrs-reload.md`` §3 — the
    only [READ] state path, ``attrs['State']['Status']``), ``stop(**
    kwargs)`` the stop method (``plan/third-party-docs/docker/
    container-stop-wait.md`` §1, models/containers.py:441-453).  Only
    those members are provided, plus a call record for ``stop``;
    anything else — notably ``attrs`` and ``reload`` — raises
    ``AttributeError`` by default.  ``attrs`` is deliberately *not*
    provided: its state key names are [INFERRED] in the saved reference,
    and exposing them would let an unverified read path pass against
    fixture keys the test itself wrote.

    ``__init__`` is explicit, not a dataclass: the code under test wraps
    its calls in ``except Exception`` (the behaviour-21 pattern), so a
    construction failure raised *inside* ``stop`` would be routed
    through ``map_sdk_error`` and surface as a ``BackendError`` that
    looks like an implementation fault and is a test fault instead.  A
    recording stub must fail where it is called from — in the test body
    — never inside the seam it records.

    When built with ``stop_error``, ``stop`` records the call **and
    then raises that exception, verbatim** — the exception object the
    test body prepared (always an SDK exception, or a subclass of one);
    the stub itself raises nothing it did not receive.
    """

    #: The state the daemon reports: ``running``, ``exited``, … — the
    #: values ``container.status`` yields (container-attrs-reload.md §3).
    status: str

    def __init__(
        self,
        container_id: str = _CONTAINER_ID,
        status: str = "running",
        stop_error: BaseException | None = None,
    ) -> None:
        """Store the id, state and prepared ``stop`` failure; record calls.

        The parameter is ``container_id`` — not ``id``, which ruff
        forbids as a shadowed builtin — while the attribute it stores
        stays ``id``, the name the SDK's ``Container`` carries.

        Args:
            container_id: The runtime id ``get`` reports.
            status: The state ``container.status`` reports.
            stop_error: Exception ``stop`` raises after recording the
                call (``None`` for the happy path) — prepared in the
                test body, never constructed here.
        """
        self.id = container_id
        self.status = status
        self._stop_error = stop_error
        self.stop_calls: list[dict[str, Any]] = []

    def stop(self, **kwargs: Any) -> None:
        """Record the call; the SDK's ``Container.stop(**kwargs)`` shape.

        Returns ``None`` exactly like the SDK method (container-stop-wait.md
        §1: no return statement), unless the prepared ``stop_error`` is
        raised after the record.
        """
        self.stop_calls.append(kwargs)
        if self._stop_error is not None:
            raise self._stop_error


class _RecordingContainers:
    """A stand-in for ``client.containers``: ``get`` only.

    ``get(self, container_id)`` mirrors the SDK signature
    (containers-list-filters.md §5, models/containers.py:939) and records
    the call **on entry, before any prepared exception is raised** — the
    same on-entry journaling ``FakeBackend`` applies to its own calls —
    so a test can assert the lookup happened even when it failed.  No
    other member exists: a backend reaching for ``list``, ``create`` or
    ``run`` hits ``AttributeError``.
    """

    def __init__(
        self,
        container: _RecordingContainer | None,
        error: BaseException | None = None,
    ) -> None:
        """Prepare the recorded behaviour of ``get``.

        Args:
            container: The object ``get`` returns (``None`` when
                ``error`` is set — the container is not there).
            error: Exception ``get`` raises after recording the call
                (``None`` for the happy path) — in practice the SDK's
                ``NotFound`` for the missing case, or a daemon/transport
                error; always prepared in the test body.
        """
        self._container = container
        self._error = error
        self.get_calls: list[_RecordedGet] = []

    def get(self, container_id: str) -> _RecordingContainer:
        """Record the lookup; return the prepared container or raise.

        Raises:
            BaseException: the prepared ``error``, verbatim — an SDK
                exception built in the test body, never a stub-internal
                fault.
        """
        self.get_calls.append(_RecordedGet(container_id=container_id))
        if self._error is not None:
            raise self._error
        if self._container is None:  # pragma: no cover - fixture misuse
            raise AssertionError("stub.get called but no container prepared")
        return self._container


class _RecordingClient:
    """A stand-in for the injected ``docker.DockerClient``.

    Carries exactly the one attribute the ``stop`` path touches —
    ``containers`` — and nothing else, so a backend that reaches past
    ``containers.get``/``Container.stop`` fails with ``AttributeError``
    rather than being waved through by a permissive stub.
    """

    def __init__(
        self,
        container: _RecordingContainer | None,
        get_error: BaseException | None = None,
    ) -> None:
        """Build the client around one prepared ``get`` outcome.

        Args:
            container: The object ``get`` returns (``None`` when
                ``get_error`` is set).
            get_error: Exception ``get`` raises after recording the call.
        """
        self.containers = _RecordingContainers(container=container, error=get_error)


# ---------------------------------------------------------------------------
# The error fixtures (built the way the SDK builds them)
# ---------------------------------------------------------------------------


def _vanished_container_404() -> docker.errors.NotFound:
    """The ``NotFound`` ``containers.get`` raises for a missing container.

    ``get`` performs a full inspect and raises ``NotFound`` if the
    container does not exist (containers-list-filters.md §5,
    models/containers.py:950-952).  Built through the SDK's own
    classifier — ``docker.errors.create_api_error_from_http_exception``,
    the single path every non-2xx response takes in production
    (``plan/third-party-docs/docker/errors.md`` §2 "The 404 mapping") —
    so its class, ``explanation`` and ``status_code`` derive from the
    synthetic response exactly as in production.  The daemon's wording
    for a vanished container names the container, not an image, so it
    matches none of the image fragments and classifies as the plain
    ``NotFound``.
    """
    message = f"404 Client Error: Not Found for url: {_URL} "
    body = json.dumps({"message": message}).encode("utf-8")
    response = requests.Response()
    response.status_code = 404
    response.url = _URL
    response.reason = "Not Found"
    response._content = body
    http_error = requests.exceptions.HTTPError(
        f"404 Client Error: {message} for url: {_URL}",
        response=response,
    )
    with pytest.raises(docker.errors.NotFound) as excinfo:
        docker.errors.create_api_error_from_http_exception(http_error)
    return cast("docker.errors.NotFound", excinfo.value)


def _server_error_500() -> docker.errors.APIError:
    """A generic 500 — a daemon refusal with no dedicated taxonomy row.

    Runs the synthetic daemon response through
    ``docker.errors.create_api_error_from_http_exception`` — the single
    classifier every non-2xx response passes through in production
    (``plan/third-party-docs/docker/errors.md`` §2) — so its class,
    ``explanation`` and ``status_code`` derive from the response exactly
    as in production.
    """
    message = "500 Internal Server Error: driver failed programming external decorator"
    response = requests.Response()
    response.status_code = 500
    response.url = _URL
    response.reason = "Internal Server Error"
    response._content = json.dumps({"message": message}).encode("utf-8")
    http_error = requests.exceptions.HTTPError(
        f"500 Server Error: {message} for url: {_URL}",
        response=response,
    )
    with pytest.raises(docker.errors.APIError) as excinfo:
        docker.errors.create_api_error_from_http_exception(http_error)
    return cast("docker.errors.APIError", excinfo.value)


def _daemon_unreachable() -> requests.exceptions.ConnectionError:
    """A dead daemon, as an operational call sees it.

    A bare ``requests`` connection error from a call against an
    unreachable daemon — the ``BackendUnavailableError`` row of
    behaviour 19's table (``plan/third-party-docs/docker/errors.md`` §3,
    [CORRECTED 2026-09-16]: a connection failure on a later API call is
    never wrapped by docker-py, so it propagates out of ``requests``
    as-is; ``map_sdk_error`` step 2 matches it).  This is what *not*
    running is **not**: the daemon is gone, so the failure is
    availability, not state.
    """
    return requests.exceptions.ConnectionError(
        "Cannot connect to the Docker daemon at unix:///var/run/docker.sock"
    )


# ---------------------------------------------------------------------------
# Behaviour 22 — the call shape
# ---------------------------------------------------------------------------


def test_stop_looks_container_up_by_id_and_stops_it_once_carrying_seconds() -> None:
    """``stop`` = one ``get(handle.id)``, then one ``stop`` with int seconds.

    Arrange: a recording stub whose ``get`` returns a running container
    carrying the handle's id, and the handle.
    Act: ``backend.stop(handle, timeout_s=10.0)``.
    Assert: exactly one ``get`` call, asking for **the handle's id**
    (containers-list-filters.md §5 — the saved single-container fetch);
    exactly one ``stop`` call, on the object ``get`` returned (the stub
    holds one such object, so the record *is* the identity check),
    carrying the timeout under the SDK's parameter name ``timeout``
    (container-stop-wait.md §1), **as an ``int`` in seconds** — the
    protocol's ``float`` converted, since the SDK's parameter is an
    ``int``; and the method returns ``None`` (the SDK's ``stop`` has no
    return statement, container-stop-wait.md §1).
    """
    handle = _handle()
    container = _RecordingContainer(container_id=handle.id, status="running")
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    result = backend.stop(handle, timeout_s=10.0)

    containers = cast("_RecordingContainers", stub.containers)
    assert containers.get_calls == [_RecordedGet(container_id=handle.id)]
    assert container.stop_calls == [{"timeout": 10}]
    recorded = container.stop_calls[0]["timeout"]
    assert recorded == 10
    assert type(recorded) is int
    assert result is None


def test_stop_passes_zero_timeout_through_instead_of_dropping_it() -> None:
    """``timeout_s=0`` reaches the SDK as a real ``0`` — never as absent.

    The API layer drops the parameter **only** on a strict ``None``
    check — ``if timeout is None: params = {}`` else
    ``params = {'t': timeout}`` (container-stop-wait.md §1,
    ``.venv/lib/python3.11/site-packages/docker/api/container.py:1202-
    1206``, re-verified against docker 7.2.0).  An implementation that
    drops falsy values (``timeout_s or None``) would send *no* ``t``
    parameter and the daemon's own configured ``StopTimeout`` — up to
    ten seconds — would apply instead of the requested immediate stop;
    the two are indistinguishable to the caller.  The zero must
    therefore survive the float→int conversion as the integer ``0``.

    Arrange: a stub whose ``get`` returns a running container.
    Act: ``backend.stop(handle, timeout_s=0.0)``.
    Assert: one ``stop`` call whose recorded ``timeout`` equals ``0``,
    is **not** ``None`` and is of type ``int`` — the triple that
    separates "passed through" from "dropped as falsy" (``None``) or
    "retyped as ``0.0``".
    """
    handle = _handle()
    container = _RecordingContainer(container_id=handle.id, status="running")
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    result = backend.stop(handle, timeout_s=0.0)

    containers = cast("_RecordingContainers", stub.containers)
    assert containers.get_calls == [_RecordedGet(container_id=handle.id)]
    assert container.stop_calls == [{"timeout": 0}]
    recorded = container.stop_calls[0]["timeout"]
    assert recorded == 0
    assert recorded is not None
    assert type(recorded) is int
    assert result is None


# ---------------------------------------------------------------------------
# Behaviour 22 — the no-op contract (§4.3), paired with FakeBackend
# ---------------------------------------------------------------------------


def test_stop_on_missing_container_is_a_no_op() -> None:
    """A container the lookup reports missing is a no-op, not an error.

    §4.3: "``stop`` on a missing container is a no-op. Every other method
    raises."  This is the half of the pair ``FakeBackend`` already
    shipped (behaviour 12: "A no-op — not an error — when the container
    is … has vanished").

    Arrange: a stub whose ``get`` records the call and then raises the
    SDK's ``NotFound`` — the exception ``get`` documents for a missing
    container (containers-list-filters.md §5), built through the
    SDK's own 404 classifier (errors.md §2).
    Act: ``backend.stop(handle, timeout_s=5.0)`` — must **not** raise.
    Assert: it returns ``None``; the lookup happened exactly once, by
    id; and no stop call was made on any container — the only
    container object in existence is the stub's, and its record is
    empty.
    """
    handle = _handle()
    container = _RecordingContainer(container_id=handle.id, status="running")
    stub = _RecordingClient(container=container, get_error=_vanished_container_404())
    backend = _backend_with(stub)

    result = backend.stop(handle, timeout_s=5.0)

    assert result is None
    containers = cast("_RecordingContainers", stub.containers)
    assert containers.get_calls == [_RecordedGet(container_id=handle.id)]
    assert container.stop_calls == []


def test_stop_on_already_exited_container_is_a_no_op() -> None:
    """A container the lookup reports already exited is a no-op, too.

    The plan's edge-case list names it separately from the missing case:
    "an already-exited container is also a no-op" — the daemon happily
    exists, it simply has nothing left to stop.  ``FakeBackend`` treats
    both identically (behaviour 12: "already exited or has vanished"),
    so the observable contract is the same: no raise, ``None``, no stop
    call.  The state is read through ``container.status`` — the only
    [READ] state property the saved reference provides
    (container-attrs-reload.md §3) — with the daemon's ``exited`` value
    (container-stop-wait.md §1's sibling ``list`` filter names it;
    containers-list-filters.md §3).

    Arrange: a stub whose ``get`` returns a container whose ``status``
    is ``exited``.
    Act: ``backend.stop(handle, timeout_s=5.0)`` — must not raise.
    Assert: ``None`` returned; one lookup by id; zero ``stop`` calls on
    the container.
    """
    handle = _handle()
    container = _RecordingContainer(container_id=handle.id, status="exited")
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    result = backend.stop(handle, timeout_s=5.0)

    assert result is None
    containers = cast("_RecordingContainers", stub.containers)
    assert containers.get_calls == [_RecordedGet(container_id=handle.id)]
    assert container.stop_calls == []


def test_stop_on_running_container_is_not_a_no_op() -> None:
    """Negative control: a running container *is* stopped.

    The two no-op tests above would pass vacuously against an
    implementation that never stops anything; this one is the pin that
    keeps them honest — the same fixture shape with ``status='running'``
    must produce exactly one ``stop`` call.

    Arrange: a stub whose ``get`` returns a running container.
    Act: ``backend.stop(handle, timeout_s=5.0)``.
    Assert: one lookup by id; exactly one ``stop`` call carrying the
    timeout in int seconds; ``None`` returned.
    """
    handle = _handle()
    container = _RecordingContainer(container_id=handle.id, status="running")
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    result = backend.stop(handle, timeout_s=5.0)

    containers = cast("_RecordingContainers", stub.containers)
    assert containers.get_calls == [_RecordedGet(container_id=handle.id)]
    assert container.stop_calls == [{"timeout": 5}]
    assert result is None


def _fake_outcome(status: str | None) -> tuple[bool, object, bool, bool]:
    """Drive ``FakeBackend.stop`` for one scenario; the observable half.

    Args:
        status: The container's state before the stop under test:
            ``"running"``, ``"exited"`` (already stopped once) or
            ``None`` (vanished out of band via ``vanish``).

    Returns:
        A ``(raised, result, performed, pre_running)`` tuple: whether
        the stop raised, its return value, whether it *did* anything
        (a running container stopped is a transition — ``is_running``
        going ``True`` → ``False``; a no-op leaves the state it found),
        and the pre-stop ``is_running`` — so a fixture that failed to
        prepare "running" as running cannot fake the comparison.
    """
    fake = FakeBackend()
    handle = fake.start(_spec())
    if status == "exited":
        fake.stop(handle, timeout_s=5.0)
    elif status is None:
        fake.vanish(handle)
    pre_running = fake.is_running(handle)
    try:
        result: object = fake.stop(handle, timeout_s=5.0)
    except Exception:
        return True, None, False, pre_running
    performed = pre_running and not fake.is_running(handle)
    return False, result, performed, pre_running


def test_stop_no_op_contract_matches_fake_backend() -> None:
    """Both backends must agree on the §4.3 no-op contract — or the fast
    unit tests rest on a lie.

    ``FakeBackend`` shipped this contract in behaviour 12 ("A no-op —
    not an error — when the container is already exited or has
    vanished", ``src/tool_swap/backend/fake_backend.py``); the plan
    (§4.3 contract decision) says ``DockerBackend`` must implement the
    *same observable contract*.  This test runs the same three
    scenarios — running, already stopped, vanished — through both
    backends and demands agreement on the observables every seam
    consumer can see without a daemon:

    1. the stop **does not raise** (the load-bearing half: a raise here
       turns M2b's liveness sweep into an unhandled traceback);
    2. the stop **returns ``None``** (the protocol's ``-> None``);
    3. the stop **is performed exactly when the container is running** —
       observable on the fake as the ``is_running`` transition and on
       the docker backend as the stub's ``stop`` call record.

    A disagreement in either direction — the docker backend raising
    where the fake no-ops, or no-op'ing where the fake performs — fails
    this test naming the scenario.
    """
    scenarios: tuple[tuple[str, str | None], ...] = (
        ("running", "running"),
        ("already stopped", "exited"),
        ("vanished", None),
    )
    for label, status in scenarios:
        fake_raised, fake_result, fake_performed, pre_running = _fake_outcome(status)
        # Fixture guard: "running" must actually have been running.
        assert pre_running is (status == "running")

        handle = _handle()
        if status is None:
            container = _RecordingContainer(container_id=handle.id, status="exited")
            get_error: BaseException | None = _vanished_container_404()
        else:
            container = _RecordingContainer(container_id=handle.id, status=status)
            get_error = None
        assert container is not None
        stub = _RecordingClient(container=container, get_error=get_error)
        backend = _backend_with(stub)

        try:
            docker_result: object = backend.stop(handle, timeout_s=5.0)
        except Exception as exc:
            pytest.fail(
                f"DockerBackend.stop raised {exc!r} in the {label!r} scenario "
                f"while FakeBackend treats it as a no-op (§4.3)"
            )
        docker_performed = len(container.stop_calls) == 1

        assert fake_raised is False, f"Fixture: FakeBackend {label!r} raised"
        assert fake_result is None, f"Fixture: FakeBackend {label!r} not None"
        assert docker_result is None, (
            f"DockerBackend.stop returned {docker_result!r} in the "
            f"{label!r} scenario — the protocol returns None"
        )
        expected_performed = status == "running"
        assert fake_performed is expected_performed, (
            f"Fixture: FakeBackend {label!r} performed={fake_performed}"
        )
        assert docker_performed is expected_performed, (
            f"DockerBackend.stop disagreed with FakeBackend in the "
            f"{label!r} scenario: performed={docker_performed}, "
            f"expected {expected_performed}"
        )


# ---------------------------------------------------------------------------
# Behaviour 22 — error routing (no raw SDK exception escapes the seam)
# ---------------------------------------------------------------------------


def test_stop_routes_get_error_through_map_sdk_error() -> None:
    """A daemon refusal during the lookup surfaces the taxonomy member.

    The 500 is the row that proves *routing*, not *classification*: the
    mapping table is behaviour 19's and is not re-tested here — only
    that whatever ``get`` raises passes through ``map_sdk_error`` and
    the result is raised, the raw SDK exception chained as
    ``__cause__`` and no ``docker.errors.DockerException`` escaping.

    Arrange: a stub whose ``get`` records the call then raises the 500
    built through the SDK's own classifier (errors.md §2).
    Act: ``backend.stop(handle, timeout_s=5.0)``, expected to raise.
    Assert: a ``BackendError``-family member, not a ``DockerException``,
    with the raw 500 as ``__cause__``; the lookup happened once; no
    stop call was made (the container was never identified).
    """
    handle = _handle()
    error = _server_error_500()
    container = _RecordingContainer(container_id=handle.id, status="running")
    stub = _RecordingClient(container=container, get_error=error)
    backend = _backend_with(stub)

    with pytest.raises(BackendError) as excinfo:
        backend.stop(handle, timeout_s=5.0)
    raised = excinfo.value
    assert not isinstance(raised, docker.errors.DockerException)
    assert raised.__cause__ is error
    containers = cast("_RecordingContainers", stub.containers)
    assert containers.get_calls == [_RecordedGet(container_id=handle.id)]
    assert container.stop_calls == []


def test_stop_on_dead_daemon_surfaces_backend_unavailable_not_a_no_op() -> None:
    """Daemon-unreachable is **not** not-running — it must not be swallowed.

    A bare ``requests`` connection error (errors.md §3, [CORRECTED
    2026-09-16]) means the daemon is gone: the container is not *known*
    to have exited, the stop simply could not happen.  ``map_sdk_error``
    maps that row to ``BackendUnavailableError`` (behaviour 19), and
    swallowing it as a no-op would make a dead daemon look like a tidy
    shutdown — the difference between the §4.3 no-op contract and a bug
    that hides outages.  The no-op applies to *state* (missing,
    exited), never to *availability*.

    Arrange: a stub whose ``get`` records the call then raises the
    connection error.
    Act: ``backend.stop(handle, timeout_s=5.0)``, expected to raise.
    Assert: ``BackendUnavailableError`` — **not** ``None`` returned
    (``pytest.raises`` fails if the call no-ops), **not** a
    ``DockerException`` — with the raw error chained as ``__cause__``;
    no stop call was made.
    """
    handle = _handle()
    error = _daemon_unreachable()
    container = _RecordingContainer(container_id=handle.id, status="running")
    stub = _RecordingClient(container=container, get_error=error)
    backend = _backend_with(stub)

    with pytest.raises(BackendUnavailableError) as excinfo:
        backend.stop(handle, timeout_s=5.0)
    raised = excinfo.value
    assert not isinstance(raised, docker.errors.DockerException)
    assert isinstance(raised, BackendError)
    assert raised.__cause__ is error
    containers = cast("_RecordingContainers", stub.containers)
    assert containers.get_calls == [_RecordedGet(container_id=handle.id)]
    assert container.stop_calls == []


@pytest.mark.parametrize(
    ("error_factory", "expected_type"),
    [
        ("server_error_500", BackendError),
        ("daemon_unreachable", BackendUnavailableError),
    ],
)
def test_stop_routes_stop_call_errors_through_map_sdk_error(
    error_factory: str, expected_type: type
) -> None:
    """Errors from the ``stop`` call itself are routed too, not just
    ``get``'s.

    The container is found and running, then the stop call fails — a
    500 (the daemon refused) or a connection error (the daemon died
    mid-stop).  Both must surface the taxonomy member via behaviour 19,
    never the raw SDK exception.

    Arrange: a stub whose ``get`` returns a running container whose
    ``stop`` raises the prepared exception *after recording the call*
    (the stub's documented failure mode — it raises exactly the
    exception the test body prepared).
    Act: ``backend.stop(handle, timeout_s=5.0)``, expected to raise.
    Assert: the taxonomy member — not a ``DockerException`` — with the
    raw error as ``__cause__``; one lookup; exactly one (failing) stop
    attempt on the identified container.
    """
    handle = _handle()
    if error_factory == "server_error_500":
        error: BaseException = _server_error_500()
    else:
        error = _daemon_unreachable()
    container = _RecordingContainer(
        container_id=handle.id, status="running", stop_error=error
    )
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    with pytest.raises(expected_type) as excinfo:
        backend.stop(handle, timeout_s=5.0)
    raised = excinfo.value
    assert not isinstance(raised, docker.errors.DockerException)
    assert isinstance(raised, BackendError)
    assert raised.__cause__ is error
    containers = cast("_RecordingContainers", stub.containers)
    assert containers.get_calls == [_RecordedGet(container_id=handle.id)]
    assert len(container.stop_calls) == 1
