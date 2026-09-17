"""RED step for M2a behaviour 23 — ``DockerBackend.is_running`` on a
vanished container.

See ``plans/m2a-container-backend-seam.md`` behaviour 23 (§5) and the
§4.3 contract decision.  ``is_running(handle) -> bool`` (the signature
is pinned by the ``ContainerBackend`` protocol in
``src/tool_swap/backend/base.py``, behaviour 8) must:

1. **look the container up by the handle's id** — ``client.containers.get``
   (``plan/third-party-docs/docker/containers-list-filters.md`` §5:
   ``get`` at models/containers.py:939 performs a full inspect and
   *raises ``NotFound`` if missing*, lines 950-952);
2. **map the reported state to a bool — only ``running`` is ``True``**;
   every other state the plan names (``created``, ``exited``,
   ``paused``, ``restarting``) maps to ``False``.  The read path is
   ``container.status`` — the one state property the saved reference
   marks [READ] (``plan/third-party-docs/docker/container-attrs-reload.md``
   §3, containers.py:59-67);
3. **swallow not-found and return ``False``** — §4.3: "``is_running``
   swallows not-found and returns ``False`` … Every other method
   raises."  This encodes our half of docker contract test 3 of
   ``plans/m2-docker-testing-recommendation.md``: *"`docker rm -f`
   behind the backend's back, then `is_running` returns `False`", and
   "SDK raises `NotFound`; whether that becomes `False` or propagates
   is our contract."*  The fake half already shipped (behaviour 12,
   ``src/tool_swap/backend/fake_backend.py`` — "A stopped and a
   vanished container are indistinguishable from this call — both
   report ``False`` without raising"), and §6 item 4 explains what
   rests on it: "without it M2b's liveness sweep becomes an unhandled
   traceback in the watchdog."
   ``test_is_running_contract_matches_fake_backend`` runs the same
   three scenarios through both backends and demands the same
   observable outcome.

**The state-string set is open, and the tests say so.**  The plan
names ``created``, ``exited``, ``paused``, ``restarting`` as the
non-running states, but the saved reference is explicit that
**no SDK line enumerates the full set of ``status`` strings**
(``container-attrs-reload.md`` §3.1: the SDK docstring names
``running``/``exited`` only *as examples*; the ``containers.list``
filter names four more; "No SDK line enumerates all of them").  The
table test therefore asserts the mapping as a contract — *only the
running state is ``True``; every other state we can name is
``False``* — and it is stated in the docstrings as an open set, not a
closed one.  The unknown-state case gets **its own test**,
``test_is_running_on_an_unnamed_state_string_maps_to_false``: the
load-bearing direction is that an unrecognised state maps to
``False`` rather than raising or to ``True`` — a liveness sweep that
treated an unrecognised state as "running" would never reap the
container, and one that raised would turn a daemon vocabulary change
into a watchdog traceback.  No saved document names what the daemon
would actually emit for such a state, so the test uses a clearly
synthetic string and claims only the safe direction.

**Daemon-unreachable is NOT not-running.**  A dead daemon surfacing
from this call is a bare ``requests`` connection error (``plan/
third-party-docs/docker/errors.md`` §3, [CORRECTED 2026-09-16]: a
connection failure on a later API call is never wrapped, so it
propagates out of ``requests`` as-is — the table row that
behaviour 19 maps to ``BackendUnavailableError``).  Swallowing it as
``False`` would make a temporary outage read as "every container is
dead", and M2b's sweep would then cheerfully "reap" containers that
are alive behind the unreachable daemon.  A blanket
``except Exception: return False`` passes every other test in this
file and fails exactly these two —
``test_is_running_on_dead_daemon_surfaces_backend_unavailable_not_false``
and ``test_is_running_on_daemon_refusal_is_routed_not_swallowed`` —
with a ``DID NOT RAISE`` failure, because the call returns ``False``
where a taxonomy member must be raised.  The no-op applies to
*state* (missing, non-running), never to *availability*.

**The shell is thin on purpose (plan §4.5).**  ``map_sdk_error``'s
mapping table is behaviour 19's and is *not* re-tested here — only
that ``is_running`` *routes* every exception it does not deliberately
swallow through it, the raw exception chained as ``__cause__`` and
no raw ``docker.errors.DockerException`` escaping.

**The stub's fidelity, and the trap this decision avoids.**  As in
behaviours 21 and 22, the stub records and never fails on its own:
the ``is_running`` path wraps its calls in ``except Exception``
(the committed behaviour-21/22 pattern), so any ``AttributeError``
raised *inside* a stub method would be routed through
``map_sdk_error`` and surface as a ``BackendError`` that looks like
an implementation fault and is a test fault instead.  Construction
is plain (explicit ``__init__``, no dataclass ``__post_init__``), the
signature matches the SDK's (``get(self, container_id)`` —
models/containers.py:939), and the only exceptions that ever leave a
stub method are SDK exceptions *prepared in the test body* — the
stub raises what it is given, verbatim, after recording.  The stub
container exposes exactly ``id`` and ``status`` — **not** ``stop``,
**not** ``attrs``, **not** ``reload``: ``status`` is the only
state-readable property the saved reference marks [READ]
(``container-attrs-reload.md`` §3), while the raw ``attrs`` state
key names are [INFERRED]; and a read-only call must observe, not
mutate, so reaching for ``stop``/``remove`` fails loudly instead of
being waved through.

The ``isinstance(backend, ContainerBackend)`` conformance pin is
deliberately **absent**: ``isinstance`` matches on member *names* and
every one of the six must be present, while ``DockerBackend`` carries
only ``start`` and ``stop`` so far.  The pin is behaviour 26's, where
the class is complete — one behaviour, one cycle.

This file is the RED step: ``DockerBackend`` exists (behaviour 20)
with ``start`` (behaviour 21) and ``stop`` (behaviour 22) but no
``is_running``, so every subject test fails *individually* at the
attribute-level gate with its assertions present and reachable —
never aborting pytest collection.  No ``importorskip``, no skips.

Conventions: pytest, AAA, Google-style docstrings, Black at 88
columns, ruff, ``filterwarnings = "error"`` — no test asserts a
docker fact from memory; each is cited to the saved reference above.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from types import ModuleType
from typing import cast

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

# The runtime id both the handle and the stub container carry, so "look
# the container up by the handle's id" is an identity check.
_CONTAINER_ID = "deadbeef"

# The inspect URL a missing container's 404 would carry — ``get``
# performs a full inspect (containers-list-filters.md §5).
_URL = "http://docker/v1.45/containers/deadbeef"


# ---------------------------------------------------------------------------
# The RED gate (attribute-level, per behaviours 19/20/21/22's pattern)
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
    """Construct ``DockerBackend(stub, …)`` with ``is_running`` present.

    While ``is_running`` is absent this raises ``AssertionError`` naming
    the missing method, so the subject tests fail individually rather
    than aborting the run.

    Args:
        stub: The recording client to inject.

    Returns:
        The constructed backend.

    Raises:
        AssertionError: the module or the ``DockerBackend`` class is
            missing, or the class still defines no ``is_running`` method
            — the GREEN step must add it to
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
    if not hasattr(backend_cls, "is_running"):
        raise AssertionError(
            "DockerBackend.is_running is missing — the GREEN step must add "
            "the is_running method to "
            "src/tool_swap/backend/docker_backend.py (behaviour 23)"
        )
    return backend_cls(stub, label_namespace=_NAMESPACE, container_prefix="ms-")


# ---------------------------------------------------------------------------
# The fixtures
# ---------------------------------------------------------------------------


def _handle() -> ContainerHandle:
    """The handle whose container ``is_running`` must look up by ``id``."""
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
    the runtime id and ``status`` the state property
    (``plan/third-party-docs/docker/container-attrs-reload.md`` §3 — the
    only [READ] state path, ``attrs['State']['Status']``,
    containers.py:59-67).  Only those two members are provided.  Nothing
    else exists — **not** ``stop``, **not** ``attrs``, **not**
    ``reload``:

    - ``status`` is the only state path the saved reference marks
      [READ]; the raw ``attrs`` state key names are [INFERRED], and
      exposing them would let an unverified read path pass against
      fixture keys the test itself wrote.
    - ``is_running`` is a read-only call: it must observe a state, never
      mutate one.  A backend reaching for ``stop`` or ``remove`` on a
      liveness probe fails with ``AttributeError`` rather than being
      waved through.

    ``__init__`` is explicit, not a dataclass: the code under test wraps
    its calls in ``except Exception`` (the behaviour-21/22 pattern), so
    a construction failure raised *inside* ``is_running`` would be routed
    through ``map_sdk_error`` and surface as a ``BackendError`` that
    looks like an implementation fault and is a test fault instead.  A
    recording stub must fail where it is called from — in the test body —
    never inside the seam it records.
    """

    #: The state the daemon reports: ``running``, ``exited``, … — the
    #: values ``container.status`` yields (container-attrs-reload.md §3;
    #: the *set* of strings is open — §3.1).
    status: str

    def __init__(
        self,
        container_id: str = _CONTAINER_ID,
        status: str = "running",
    ) -> None:
        """Store the id and the reported state.

        The parameter is ``container_id`` — not ``id``, which ruff
        forbids as a shadowed builtin — while the attribute it stores
        stays ``id``, the name the SDK's ``Container`` carries.

        Args:
            container_id: The runtime id ``get`` reports.
            status: The state ``container.status`` reports.
        """
        self.id = container_id
        self.status = status


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

    Carries exactly the one attribute the ``is_running`` path touches —
    ``containers`` — and nothing else, so a backend that reaches past
    ``containers.get``/``Container.status`` fails with ``AttributeError``
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
# Behaviour 23 — the state mapping
# ---------------------------------------------------------------------------


def test_is_running_on_running_container_returns_true() -> None:
    """A container the stub reports ``running`` reads ``True``.

    Arrange: a recording stub whose ``get`` returns a container whose
    ``status`` is ``running``, and the handle.
    Act: ``backend.is_running(handle)``.
    Assert: ``True`` — strictly ``is True``, so an implementation
    returning a truthy non-bool fails; and exactly one ``get`` call,
    asking for **the handle's id** (containers-list-filters.md §5 — the
    saved single-container fetch).  The state is read through
    ``container.status``, the only [READ] state property the saved
    reference provides (container-attrs-reload.md §3).
    """
    handle = _handle()
    container = _RecordingContainer(container_id=handle.id, status="running")
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    result = backend.is_running(handle)

    assert result is True
    containers = cast("_RecordingContainers", stub.containers)
    assert containers.get_calls == [_RecordedGet(container_id=handle.id)]


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("running", True),
        ("created", False),
        ("exited", False),
        ("paused", False),
        ("restarting", False),
    ],
    ids=["running", "created", "exited", "paused", "restarting"],
)
def test_is_running_maps_named_states_open_set(state: str, expected: bool) -> None:
    """Only the running state is ``True``; every other named state is
    ``False``.

    The plan names the four non-running states (``created``, ``exited``,
    ``paused``, ``restarting``), and the assertion is deliberately
    phrased as the *open-set* contract — only ``running`` is ``True`` —
    rather than a closed whitelist, because the saved reference is
    explicit that **no SDK line enumerates the full set of ``status``
    strings**: the SDK docstring names ``running``/``exited`` only *as
    examples*, and the ``containers.list`` ``status`` filter names four
    (``container-attrs-reload.md`` §3.1, re-verified 2026-09-16).  The
    strings themselves are [INFERRED] Engine-contract vocabulary; this
    test pins *our* mapping of them, and claims no authority over what
    the daemon can emit.  The unknown-string direction is pinned
    separately by
    ``test_is_running_on_an_unnamed_state_string_maps_to_false``.

    Arrange: a stub whose ``get`` returns a container whose ``status``
    is the parameterised state.
    Act: ``backend.is_running(handle)`` — must not raise for any named
    state.
    Assert: the parameterised expectation, strictly (``is True`` /
    ``is False``); one lookup by id.
    """
    handle = _handle()
    container = _RecordingContainer(container_id=handle.id, status=state)
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    result = backend.is_running(handle)

    assert result is expected
    containers = cast("_RecordingContainers", stub.containers)
    assert containers.get_calls == [_RecordedGet(container_id=handle.id)]


def test_is_running_on_an_unnamed_state_string_maps_to_false() -> None:
    """An unrecognised state string is ``False`` — not a raise, not
    ``True``.

    This is the load-bearing half of the open-set contract and gets its
    own test rather than riding on the named-state table, because it
    pins a direction the table cannot: the safe mapping is
    *``status == "running"`` is ``True``, everything else ``False``*.
    An implementation that instead enumerated the known non-running
    states and raised on anything outside that list would pass the
    table test and still turn a future daemon vocabulary change into a
    watchdog traceback (plan §6 item 4); one that treated an
    unrecognised state as ``True`` would pass the table and never reap
    the container — a liveness sweep that believes a container is
    running will not stop it.  No saved document names what the daemon
    would actually emit beyond the [INFERRED] set
    (container-attrs-reload.md §3.1), so the test uses a clearly
    synthetic string and claims only the safe direction, not a fact
    about the daemon.

    Arrange: a stub whose ``get`` returns a container whose ``status``
    is ``"migrating"`` — a string no saved reference names.
    Act: ``backend.is_running(handle)`` — must not raise.
    Assert: strictly ``False``; one lookup by id.
    """
    handle = _handle()
    container = _RecordingContainer(container_id=handle.id, status="migrating")
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    result = backend.is_running(handle)

    assert result is False
    containers = cast("_RecordingContainers", stub.containers)
    assert containers.get_calls == [_RecordedGet(container_id=handle.id)]


# ---------------------------------------------------------------------------
# Behaviour 23 — the not-found contract (§4.3), paired with FakeBackend
# ---------------------------------------------------------------------------


def test_is_running_on_vanished_container_returns_false_without_raising() -> None:
    """A container the lookup reports missing reads ``False`` — never
    raises.

    §4.3: "``is_running`` swallows not-found and returns ``False``".
    This is our half of docker contract test 3 (``plans/
    m2-docker-testing-recommendation.md``): "the SDK raises
    ``NotFound``; whether that becomes ``False`` or propagates is our
    contract" — and the plan's answer is ``False``, because §6 item 4
    rests on it: without it M2b's liveness sweep becomes an unhandled
    traceback in the watchdog.  The fake half already shipped
    (behaviour 12); ``test_is_running_contract_matches_fake_backend``
    pins the agreement.

    Arrange: a stub whose ``get`` records the call and then raises the
    SDK's ``NotFound`` — the exception ``get`` documents for a missing
    container (containers-list-filters.md §5), built through the
    SDK's own 404 classifier (errors.md §2).
    Act: ``backend.is_running(handle)`` — must **not** raise.
    Assert: strictly ``False``; the lookup happened exactly once, by id
    — the absence was discovered by asking, not assumed.
    """
    handle = _handle()
    container = _RecordingContainer(container_id=handle.id, status="running")
    stub = _RecordingClient(container=container, get_error=_vanished_container_404())
    backend = _backend_with(stub)

    result = backend.is_running(handle)

    assert result is False
    containers = cast("_RecordingContainers", stub.containers)
    assert containers.get_calls == [_RecordedGet(container_id=handle.id)]


def _fake_running(status: str | None) -> bool:
    """Drive ``FakeBackend.is_running`` for one scenario; the observable half.

    Args:
        status: The container's state before the check under test:
            ``"running"``, ``"stopped"`` (stopped once) or ``None``
            (vanished out of band via ``vanish``).

    Returns:
        The ``is_running`` outcome — the observable every seam consumer
        can see without a daemon.
    """
    fake = FakeBackend()
    handle = fake.start(_spec())
    if status == "stopped":
        fake.stop(handle, timeout_s=5.0)
    elif status is None:
        fake.vanish(handle)
    return fake.is_running(handle)


def test_is_running_contract_matches_fake_backend() -> None:
    """Both backends must agree on the §4.3 not-found contract — or the
    fast unit tests rest on a lie.

    ``FakeBackend`` shipped this contract in behaviour 12 ("A stopped
    and a vanished container are indistinguishable from this call —
    both report ``False`` without raising",
    ``src/tool_swap/backend/fake_backend.py``); the plan (§4.3 contract
    decision) says ``DockerBackend`` must implement the *same observable
    contract*.  This test runs the same three scenarios — running,
    stopped, vanished — through both backends and demands agreement on
    the one observable ``is_running`` exposes:

    1. running → ``True``;
    2. stopped → ``False`` (a state, not an error);
    3. vanished → ``False`` **without raising** (the load-bearing half:
       a raise here turns M2b's liveness sweep into an unhandled
       traceback in the watchdog, plan §6 item 4).

    A disagreement in either direction — the docker backend raising or
    reading ``True`` where the fake reads ``False``, or reading
    ``False`` where the fake reads ``True`` — fails this test naming
    the scenario.
    """
    scenarios: tuple[tuple[str, str | None], ...] = (
        ("running", "running"),
        ("stopped", "stopped"),
        ("vanished", None),
    )
    for label, status in scenarios:
        fake_result = _fake_running(status)

        handle = _handle()
        if status is None:
            # Vanished: the lookup itself raises the SDK's NotFound —
            # the docker half of the fake's vanished record.
            container = _RecordingContainer(container_id=handle.id, status="exited")
            get_error: BaseException | None = _vanished_container_404()
        else:
            docker_state = "running" if status == "running" else "exited"
            container = _RecordingContainer(container_id=handle.id, status=docker_state)
            get_error = None
        assert container is not None
        stub = _RecordingClient(container=container, get_error=get_error)
        backend = _backend_with(stub)

        try:
            docker_result = backend.is_running(handle)
        except Exception as exc:
            pytest.fail(
                f"DockerBackend.is_running raised {exc!r} in the {label!r} "
                f"scenario while FakeBackend reads a bool (§4.3: not-found "
                f"returns False, never raises)"
            )

        expected = status == "running"
        assert fake_result is expected, (
            f"Fixture: FakeBackend {label!r} is_running={fake_result}"
        )
        assert docker_result is expected, (
            f"DockerBackend.is_running disagreed with FakeBackend in the "
            f"{label!r} scenario: is_running={docker_result}, "
            f"expected {expected}"
        )


# ---------------------------------------------------------------------------
# Behaviour 23 — availability is not state (a blanket catch must fail)
# ---------------------------------------------------------------------------


def test_is_running_on_dead_daemon_surfaces_backend_unavailable_not_false() -> None:
    """Daemon-unreachable is **not** not-running — it must not be
    swallowed.

    A bare ``requests`` connection error (errors.md §3, [CORRECTED
    2026-09-16]) means the daemon is gone: the container is not *known*
    to have exited, the check simply could not happen.  ``map_sdk_error``
    maps that row to ``BackendUnavailableError`` (behaviour 19), and
    swallowing it as ``False`` would turn every outage into "every
    container is dead" — M2b's sweep would then "reap" containers that
    are alive behind a temporarily unreachable daemon.  The no-op
    applies to *state* (missing, non-running), never to *availability*.

    This is the test a blanket ``except Exception: return False``
    fails: it would return ``False`` where a taxonomy member must be
    raised, and ``pytest.raises`` records that as ``DID NOT RAISE``.

    Arrange: a stub whose ``get`` records the call then raises the
    connection error.
    Act: ``backend.is_running(handle)``, expected to raise.
    Assert: ``BackendUnavailableError`` — **not** ``False`` returned,
    **not** a ``DockerException`` — with the raw error chained as
    ``__cause__``; the lookup happened once.
    """
    handle = _handle()
    error = _daemon_unreachable()
    container = _RecordingContainer(container_id=handle.id, status="running")
    stub = _RecordingClient(container=container, get_error=error)
    backend = _backend_with(stub)

    with pytest.raises(BackendUnavailableError) as excinfo:
        backend.is_running(handle)
    raised = excinfo.value
    assert not isinstance(raised, docker.errors.DockerException)
    assert isinstance(raised, BackendError)
    assert raised.__cause__ is error
    containers = cast("_RecordingContainers", stub.containers)
    assert containers.get_calls == [_RecordedGet(container_id=handle.id)]


def test_is_running_on_daemon_refusal_is_routed_not_swallowed() -> None:
    """A daemon 500 during the lookup is routed through
    ``map_sdk_error`` — it must not become ``False``.

    The 500 is the row that proves *routing*, not *classification*: the
    mapping table is behaviour 19's and is not re-tested here — only
    that whatever ``get`` raises passes through ``map_sdk_error`` and
    the result is raised, the raw SDK exception chained as
    ``__cause__`` and no ``docker.errors.DockerException`` escaping.
    A blanket ``except Exception: return False`` fails this test the
    same way it fails the dead-daemon test: a daemon refusal is an
    availability failure, and reading it as ``False`` tells the sweep
    "gone" about a container the daemon could not even be asked about.

    Arrange: a stub whose ``get`` records the call then raises the 500
    built through the SDK's own classifier (errors.md §2).
    Act: ``backend.is_running(handle)``, expected to raise.
    Assert: a ``BackendError``-family member, not a ``DockerException``,
    with the raw 500 as ``__cause__``; the lookup happened once.
    """
    handle = _handle()
    error = _server_error_500()
    container = _RecordingContainer(container_id=handle.id, status="running")
    stub = _RecordingClient(container=container, get_error=error)
    backend = _backend_with(stub)

    with pytest.raises(BackendError) as excinfo:
        backend.is_running(handle)
    raised = excinfo.value
    assert not isinstance(raised, docker.errors.DockerException)
    assert raised.__cause__ is error
    containers = cast("_RecordingContainers", stub.containers)
    assert containers.get_calls == [_RecordedGet(container_id=handle.id)]
