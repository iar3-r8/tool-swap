"""RED step for M2a behaviour 24 — ``DockerBackend.inspect``.

See ``plans/m2a-container-backend-seam.md`` behaviour 24 (§5) and the
§4.3 contract decision.  ``inspect(handle) -> ContainerStatus`` (the
signature is pinned by the ``ContainerBackend`` protocol in
``src/tool_swap/backend/base.py``, behaviour 8) must:

1. **look the container up by the handle's id** — the shared lookup the
   committed ``stop`` and ``is_running`` use (behaviours 22-23),
   ``client.containers.get`` (``plan/third-party-docs/docker/
   containers-list-filters.md`` §5: ``get`` at models/containers.py:939
   performs a full inspect and *raises ``NotFound`` if missing*,
   lines 950-952) — so the attrs it returns are already a fresh
   inspect, and no ``reload()`` is needed in this call;
2. **return a ``ContainerStatus`` with state, exit code and start
   time** read from the attribute paths named in the saved reference
   (``plan/third-party-docs/docker/container-attrs-reload.md`` §3):
   state through ``container.status`` **[READ]** (containers.py:59-67),
   exit code from ``attrs['State']['ExitCode']`` **[INFERRED]** and
   start time from ``attrs['State']['StartedAt']`` **[INFERRED]**;
3. **return ``ContainerState.GONE`` with ``exit_code=None`` for a
   missing container** — §4.3: "``inspect`` returns
   ``ContainerState.GONE``" — and **let a daemon-unreachable failure
   raise through ``map_sdk_error``**, never swallowed into ``GONE``:
   a missing container and an unreachable daemon are different facts.

**The evidence ceiling, stated plainly (§3.1 of the saved reference,
written specifically for this behaviour).**  The stub returns canned
attribute dicts, so the test author *chooses* the keys: a test whose
fixture writes ``attrs['State']['ExitCode']`` and asserts the result
carries that value **proves only that the code reads the key the
fixture wrote** — it would pass unchanged against a wrong key name.
The only state path with SDK code behind it is ``container.status``
**[READ]**; ``State.ExitCode`` (one SDK match, ``exec_inspect``'s — an
*exec* result, not a container inspect) and ``State.StartedAt`` (zero
SDK matches) are **[INFERRED from the Engine API contract]** (§3.1
table).  These tests are therefore *anti-drift pins*, worth having,
and their docstrings say exactly what they rest on — never claiming
SDK authority for the [INFERRED] paths.  Promoting them to [READ] is
possible only by one live-daemon inspect, deferred with the §7 daemon
tests.

**The exit-code route, and why not ``wait()``.**  §3.1 marks
``wait()['StatusCode']`` as the one exit-code path with SDK code
behind it **[READ]** (named in the ``wait`` docstring and consumed by
the SDK's own ``run``, containers.py:897) and recommends it "wherever
the exit code is needed at a moment the code controls".  ``inspect``
is the opposite moment: it is a point-in-time reading
(``ContainerStatus``'s own docstring says so), and ``wait()``
**blocks until the container exits** — for a running container that
is unbounded, so an inspect that called ``wait()`` would hang M2b's
liveness poller on every healthy container.  The attrs route is
therefore the only non-blocking read available, and the tests pin it
as [INFERRED]: the stub deliberately exposes **no** ``wait`` member,
so a blocking implementation cannot pass here — the missing member
surfaces through ``map_sdk_error`` as a ``BackendError`` and fails.

**The state mapping, and the load-bearing edge.**  ``ContainerState``
has four members: ``CREATED``, ``RUNNING``, ``EXITED``, ``GONE``
(``src/tool_swap/backend/base.py``).  ``GONE`` is reserved for the
§4.3 not-found path — the daemon never reports it as a ``status``
string — so the daemon's open string vocabulary (§3.1: *no SDK line
enumerates all of them*) maps as: ``created`` → ``CREATED``,
``running`` → ``RUNNING``, ``exited`` → ``EXITED``, and **every other
string — ``paused``, ``restarting``, or a value nobody has ever seen
— maps to ``EXITED`` with a logged warning rather than raising**.
The unknown-state case is what makes the incomplete set safe:
without it, an unrecognised state is either a crash (a daemon
vocabulary change turning into a liveness-sweep traceback, plan §6
item 4) or silent (a state no one notices is being misreported).
The warning is asserted with pytest's ``caplog``: a test that omits
the assertion lets the warning be silently dropped, which is exactly
how an unrecognised state becomes invisible in production.  **For a
state the vocabulary does not name, the attrs exit-code read is not
trusted either** — ``exit_code`` stays ``None`` rather than passing
through whatever the fixture wrote: the daemon's own status string is
unrecognised, so its numeric fields cannot carry authority.
``exit_code`` is read from attrs only when the daemon literally
reports ``exited``.

**Daemon-unreachable is NOT gone.**  A bare ``requests`` connection
error (``plan/third-party-docs/docker/errors.md`` §3, [CORRECTED
2026-09-16]) means the daemon is gone: the container is not *known* to
have vanished, the read simply could not happen.  ``map_sdk_error``
maps that row to ``BackendUnavailableError`` (behaviour 19), and
swallowing it as ``GONE`` would make every outage read as "every
container has been removed out of band".  A blanket
``except Exception`` returning a ``GONE`` status passes every other
test in this file and fails exactly these two —
``test_inspect_on_dead_daemon_surfaces_backend_unavailable_not_gone``
and ``test_inspect_on_daemon_refusal_is_routed_not_swallowed`` — with
a ``DID NOT RAISE`` failure.  The no-op applies to *state* (missing),
never to *availability*.  The mapping table itself is behaviour 19's
and is *not* re-tested here — only that ``inspect`` *routes* every
exception it does not deliberately swallow through it.

**The stub's fidelity.**  As in behaviours 21-23, the stub records
and never fails on its own: ``inspect``'s call pair is wrapped in
``except Exception`` by the committed pattern, so an
``AttributeError`` raised *inside* a stub method would be routed
through ``map_sdk_error`` and surface as a ``BackendError`` that
looks like an implementation fault and is a test fault instead.
Construction is plain (explicit ``__init__``, no dataclass
``__post_init__``), the only exceptions that ever leave a stub method
are SDK exceptions *prepared in the test body*, and the stub
container exposes exactly ``id``, ``attrs`` and the derived ``status``
property — **not** ``stop``, **not** ``start``, **not** ``wait``,
**not** ``reload``: a read-only call must observe, never mutate, and
the one read it is not allowed to make is the blocking one (see
above).  The stub's ``status`` derives from
``attrs['State']['Status']`` — the SDK's own [READ] derivation
(containers.py:59-67) — so the single fixture write feeds both the
state and the attrs-based reads exactly as one daemon inspect would.

The ``isinstance(backend, ContainerBackend)`` conformance pin is
deliberately **absent**: ``isinstance`` matches on member *names* and
every one of the six must be present, while ``DockerBackend`` carries
``start``, ``stop`` and ``is_running`` so far.  The pin is behaviour
26's, where the class is complete — one behaviour, one cycle.

This file is the RED step: ``DockerBackend`` exists (behaviour 20)
with ``start`` (21), ``stop`` (22) and ``is_running`` (23) but no
``inspect``, so every subject test fails *individually* at the
attribute-level gate with its assertions present and reachable —
never aborting pytest collection.  No ``importorskip``, no skips.

Conventions: pytest, AAA, Google-style docstrings, Black at 88
columns, ruff, ``filterwarnings = "error"`` — no test asserts a
docker fact from memory; each is cited to the saved reference above.
"""

from __future__ import annotations

import importlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from types import ModuleType
from typing import cast

import docker.errors
import pytest
import requests

from tool_swap.backend.base import (
    ContainerHandle,
    ContainerSpec,
    ContainerState,
    ContainerStatus,
)
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

# A realistic RFC 3339 start time, the shape the saved reference gives
# (container-attrs-reload.md §3: e.g. "2026-09-14T19:40:00.123456789Z").
_STARTED_AT = "2026-09-14T19:40:00.123456789Z"

# The value the Engine API reports before a container has ever started
# (container-attrs-reload.md §3) — [INFERRED], pinned as pass-through.
_NEVER_STARTED = "0001-01-01T00:00:00Z"

# A state string no saved reference names — the synthetic unknown.
_UNNAMED_STATE = "migrating"


# ---------------------------------------------------------------------------
# The RED gate (attribute-level, per behaviours 19/20/21/22/23's pattern)
# ---------------------------------------------------------------------------


def _get_docker_backend_module() -> ModuleType:
    """Import ``tool_swap.backend.docker_backend`` at call time.

    The import is deferred out of module scope via
    ``importlib.import_module`` so a missing module could not abort
    pytest *collection* of this file.  While the module is absent this
    raises ``AssertionError`` naming the missing module, so every test
    fails individually instead of the run being interrupted.

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
    """Construct ``DockerBackend(stub, …)`` with ``inspect`` present.

    While ``inspect`` is absent this raises ``AssertionError`` naming
    the missing method, so the subject tests fail individually rather
    than aborting the run.

    Args:
        stub: The recording client to inject.

    Returns:
        The constructed backend.

    Raises:
        AssertionError: the module or the ``DockerBackend`` class is
            missing, or the class still defines no ``inspect`` method —
            the GREEN step must add it to
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
    if not hasattr(backend_cls, "inspect"):
        raise AssertionError(
            "DockerBackend.inspect is missing — the GREEN step must add "
            "the inspect method to "
            "src/tool_swap/backend/docker_backend.py (behaviour 24)"
        )
    return backend_cls(stub, label_namespace=_NAMESPACE, container_prefix="ms-")


# ---------------------------------------------------------------------------
# The fixtures
# ---------------------------------------------------------------------------


def _handle() -> ContainerHandle:
    """The handle whose container ``inspect`` must look up by ``id``."""
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


def _attrs(
    state: str, *, exit_code: int = 0, started_at: str = _STARTED_AT
) -> dict[str, object]:
    """A canned ``container.attrs`` dict in the Engine API's inspect shape.

    The **key names are the test author's choice**, written to match
    the Engine API contract recorded in
    ``plan/third-party-docs/docker/container-attrs-reload.md`` §3:
    ``State.Status`` **[READ]** (the path the SDK itself reads for
    ``container.status``, containers.py:59-67), ``State.ExitCode`` and
    ``State.StartedAt`` **[INFERRED]** — re-confirmed by grep over the
    installed package as unciteable from SDK source (§3.1).  A test
    asserting the code reads these keys proves only that the code reads
    the keys this fixture writes; it is an anti-drift pin, not a proof
    of the daemon's real key names (see the module docstring).

    Args:
        state: The value of ``State.Status`` the daemon reports.
        exit_code: The value of ``State.ExitCode``; defaults to ``0``,
            the daemon's value while a container has never exited.
        started_at: The value of ``State.StartedAt`` as the daemon
            reports it (an RFC 3339 string).

    Returns:
        A fresh attrs dict; every call returns independent storage.
    """
    return {
        "Id": _CONTAINER_ID,
        "State": {
            "Status": state,
            "ExitCode": exit_code,
            "StartedAt": started_at,
        },
    }


# ---------------------------------------------------------------------------
# The recording stub
# ---------------------------------------------------------------------------


@dataclass
class _RecordedGet:
    """One recorded ``get`` call: the container id it was asked for."""

    container_id: str


class _RecordingContainer:
    """A stand-in for the ``Container`` object ``get`` returns.

    The real object is a ``docker.models.containers.Container``:
    ``id`` the runtime id, ``attrs`` the raw inspect dict (cached —
    §1 of the saved reference) and ``status`` the state property that
    derives from ``attrs['State']['Status']`` (containers.py:59-67,
    **[READ]**).  This stub mirrors that derivation so the single
    fixture write feeds every read path exactly as one daemon inspect
    would.

    Nothing else exists — **not** ``stop``, **not** ``start``, **not**
    ``wait``, **not** ``reload``:

    - ``inspect`` is a read-only call: it must observe a state, never
      mutate one.  A backend reaching for ``stop`` or ``start`` on an
      inspect probe fails with ``AttributeError`` rather than being
      waved through.
    - ``wait`` is the blocking exit-code route (§3.1) and is excluded
      by design: an ``inspect`` that called it would hang on a running
      container, and a stub without it cannot let that implementation
      pass.
    - ``reload`` is unnecessary — ``get`` already performs a full
      inspect, so ``attrs`` is fresh at call time (container-attrs-
      reload.md §1-2) — and an implementation making a second lookup
      would fail the "exactly one ``get``" assertions.

    ``__init__`` is explicit, not a dataclass: the code under test
    wraps its calls in ``except Exception`` (the behaviour-21/22/23
    pattern), so a construction failure raised *inside* ``inspect``
    would be routed through ``map_sdk_error`` and surface as a
    ``BackendError`` that looks like an implementation fault and is a
    test fault instead.  A recording stub must fail where it is called
    from — in the test body — never inside the seam it records.
    """

    def __init__(
        self,
        attrs: dict[str, object],
        container_id: str = _CONTAINER_ID,
    ) -> None:
        """Store the id and the raw inspect dict.

        The parameter is ``container_id`` — not ``id``, which ruff
        forbids as a shadowed builtin — while the attribute it stores
        stays ``id``, the name the SDK's ``Container`` carries.

        Args:
            attrs: The raw inspect dict the daemon returned.
            container_id: The runtime id ``get`` reports.
        """
        self.attrs = attrs
        self.id = container_id

    @property
    def status(self) -> str:
        """The state property, derived as the SDK derives it.

        ``attrs['State']['Status']`` — the [READ] path the SDK's own
        property uses (containers.py:59-67, container-attrs-reload.md
        §3).  The legacy bare-string ``State`` branch the SDK carries
        is not modelled: the fixtures write the dict form, which is
        what a current daemon's inspect returns.
        """
        state: object = self.attrs["State"]
        if isinstance(state, Mapping):
            return str(state["Status"])
        return str(state)


class _RecordingContainers:
    """A stand-in for ``client.containers``: ``get`` only.

    ``get(self, container_id)`` mirrors the SDK signature
    (containers-list-filters.md §5, models/containers.py:939) and
    records the call **on entry, before any prepared exception is
    raised** — the same on-entry journaling ``FakeBackend`` applies to
    its own calls — so a test can assert the lookup happened even when
    it failed.  No other member exists: a backend reaching for
    ``list``, ``create`` or ``run`` hits ``AttributeError``.
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
                ``NotFound`` for the missing case, or a
                daemon/transport error; always prepared in the test
                body.
        """
        self._container = container
        self._error = error
        self.get_calls: list[_RecordedGet] = []

    def get(self, container_id: str) -> _RecordingContainer:
        """Record the lookup; return the prepared container or raise.

        Raises:
            BaseException: the prepared ``error``, verbatim — an SDK
                exception built in the test body, never a
                stub-internal fault.
        """
        self.get_calls.append(_RecordedGet(container_id=container_id))
        if self._error is not None:
            raise self._error
        if self._container is None:  # pragma: no cover - fixture misuse
            raise AssertionError("stub.get called but no container prepared")
        return self._container


class _RecordingClient:
    """A stand-in for the injected ``docker.DockerClient``.

    Carries exactly the one attribute the ``inspect`` path touches —
    ``containers`` — and nothing else, so a backend that reaches past
    ``containers.get``/``Container.attrs``/``Container.status`` fails
    with ``AttributeError`` rather than being waved through by a
    permissive stub.
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
            get_error: Exception ``get`` raises after recording the
                call.
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
    classifier —
    ``docker.errors.create_api_error_from_http_exception``, the single
    path every non-2xx response takes in production (``plan/
    third-party-docs/docker/errors.md`` §2 "The 404 mapping") — so its
    class, ``explanation`` and ``status_code`` derive from the
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
    ``explanation`` and ``status_code`` derive from the response
    exactly as in production.
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
    behaviour 19's table (``plan/third-party-docs/docker/errors.md``
    §3, [CORRECTED 2026-09-16]: a connection failure on a later API
    call is never wrapped by docker-py, so it propagates out of
    ``requests`` as-is; ``map_sdk_error`` step 2 matches it).  This is
    what *not* being there is **not**: the daemon is gone, so the
    failure is availability, not state.
    """
    return requests.exceptions.ConnectionError(
        "Cannot connect to the Docker daemon at unix:///var/run/docker.sock"
    )


# ---------------------------------------------------------------------------
# Behaviour 24 — the state mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "exit_code_in_attrs", "expected_state", "expected_exit_code"),
    [
        # A created container has never exited: the daemon's ExitCode
        # of 0 must not pass through as a "clean exit" that never
        # happened.
        ("created", 0, ContainerState.CREATED, None),
        # The plan's explicit edge: a running container has
        # exit_code=None, **not 0** — base.py's None-rather-than-0
        # default exists precisely so live containers are not reported
        # as clean exits.
        ("running", 0, ContainerState.RUNNING, None),
        # Only the literally-exited state carries the attrs exit code,
        # passed through unmodified — 137 (SIGKILL) so a constant-0
        # implementation cannot pass.
        ("exited", 137, ContainerState.EXITED, 137),
    ],
    ids=["created", "running", "exited"],
)
def test_inspect_maps_named_states(
    state: str,
    exit_code_in_attrs: int,
    expected_state: ContainerState,
    expected_exit_code: int | None,
) -> None:
    """The named daemon states map to their ``ContainerState`` members.

    The state is read through ``container.status`` — the one state
    property the saved reference marks **[READ]** (containers.py:59-
    67).  The *string values* themselves are [INFERRED] Engine-
    contract vocabulary — no SDK line enumerates the full set (§3.1)
    — so this table pins *our* mapping of the three strings that have
    enum members, and claims no authority over what the daemon can
    emit beyond them.  ``GONE`` is absent on purpose: it is the §4.3
    not-found state, reserved for the ``NotFound`` path — the daemon
    never reports it as a ``status`` string.

    ``exit_code`` is carried **only when the daemon literally reports
    ``exited``**: ``created`` and ``running`` have exited neither
    successfully nor at all, and passing the daemon's ``0`` through
    for either would report a clean exit that never happened — the
    same reasoning base.py's ``None``-rather-than-``0`` default
    encodes.

    The exited row's ``ExitCode`` read is **[INFERRED]**
    (container-attrs-reload.md §3.1): it rests on the Engine API
    contract, and it proves only that the code reads the key the
    fixture wrote — an anti-drift pin, not a proof of the daemon's
    real key name.

    Arrange: a stub whose ``get`` returns a container whose canned
    attrs carry the parameterised ``State``.
    Act: ``backend.inspect(handle)`` — must not raise for any named
    state.
    Assert: a ``ContainerStatus`` carrying the handle, the
    parameterised state and exit code (``None`` asserted strictly
    ``is None``); exactly one ``get`` call, asking for **the handle's
    id**.
    """
    handle = _handle()
    container = _RecordingContainer(
        _attrs(state, exit_code=exit_code_in_attrs), container_id=handle.id
    )
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    result = backend.inspect(handle)

    assert isinstance(result, ContainerStatus)
    assert result.handle == handle
    assert result.state is expected_state
    if expected_exit_code is None:
        assert result.exit_code is None
    else:
        assert result.exit_code == expected_exit_code
    containers = cast("_RecordingContainers", stub.containers)
    assert containers.get_calls == [_RecordedGet(container_id=handle.id)]


def test_inspect_on_an_unnamed_state_string_maps_to_exited_and_logs_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unrecognised state string maps to ``EXITED`` and **logs a
    warning** — it does not raise.

    This is the load-bearing half of the open-set contract (§3.1:
    "it is what makes the incomplete string set safe rather than a
    crash") and gets its own test rather than riding on the named-
    state table, because it pins two directions the table cannot:

    - the state is ``EXITED`` — the safe mapping, never a crash and
      never ``RUNNING`` (a liveness sweep that believes an
      unrecognised container is running will never reap it) and never
      ``CREATED`` (which would read as "will run soon" and block
      readiness logic that expects a terminal state);
    - **a warning is actually logged**, naming the unrecognised
      state.  ``caplog`` makes that assertable; a test that omits the
      assertion lets the warning be silently dropped, which is
      exactly how an unrecognised state becomes invisible in
      production.  The assertion checks level and that the state
      string is in the message — not the exact wording, so the GREEN
      step owns the message text.

    ``exit_code`` stays ``None`` for an unrecognised state: the
    daemon's own status string is untrusted here, so its numeric
    fields cannot carry authority either (see the module docstring).

    No saved document names what the daemon would actually emit
    beyond the [INFERRED] set, so the test uses a clearly synthetic
    string and claims only the safe direction, not a fact about the
    daemon.

    Arrange: a stub whose ``get`` returns a container whose ``status``
    is ``_UNNAMED_STATE``.
    Act: ``backend.inspect(handle)`` — must not raise.
    Assert: state ``EXITED``, ``exit_code is None``, and at least one
    logged record at WARNING or above whose message names the state;
    one lookup by id.
    """
    handle = _handle()
    container = _RecordingContainer(_attrs(_UNNAMED_STATE), container_id=handle.id)
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    with caplog.at_level(logging.WARNING):
        result = backend.inspect(handle)

    assert result.state is ContainerState.EXITED
    assert result.exit_code is None
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(_UNNAMED_STATE in record.getMessage() for record in warnings), (
        f"no WARNING naming {_UNNAMED_STATE!r} was logged"
    )
    containers = cast("_RecordingContainers", stub.containers)
    assert containers.get_calls == [_RecordedGet(container_id=handle.id)]


def test_inspect_on_a_named_state_does_not_log_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A recognised state maps without warning — warnings are for the
    unknown, not for every inspect.

    The unknown-state warning earns its place by naming an
    *unexpected* vocabulary; an implementation that warned on every
    call (or on every mapped state) would make the one warning that
    matters indistinguishable from noise.  ``created`` is the state
    used — the named state least likely to be conflated with the
    healthy ``running`` path.

    Arrange: a stub whose ``get`` returns a ``created`` container.
    Act: ``backend.inspect(handle)``.
    Assert: state ``CREATED`` and no record at WARNING or above.
    """
    handle = _handle()
    container = _RecordingContainer(_attrs("created"), container_id=handle.id)
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    with caplog.at_level(logging.WARNING):
        result = backend.inspect(handle)

    assert result.state is ContainerState.CREATED
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


# ---------------------------------------------------------------------------
# Behaviour 24 — the start-time pass-through
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "started_at"),
    [
        # A normal post-start timestamp; the string is the fixture's
        # own, so the assertion is about pass-through, not format.
        ("running", _STARTED_AT),
        # The pre-first-start value the Engine API reports
        # (container-attrs-reload.md §3) — [INFERRED], pinned only as
        # pass-through: the seam does not decide what it means.
        ("created", _NEVER_STARTED),
    ],
    ids=["running", "never-started"],
)
def test_inspect_reports_started_at_verbatim(state: str, started_at: str) -> None:
    """``started_at`` is the daemon's string, passed through **as-is**.

    base.py: "``started_at`` is the runtime-reported start time as a
    plain string; **no coercion to ``datetime`` at the seam**."  The
    read path ``attrs['State']['StartedAt']`` is **[INFERRED]**
    (container-attrs-reload.md §3.1 — *zero* matches for
    ``StartedAt`` anywhere in the installed SDK package): this test
    rests on the Engine API contract, and it proves only that the
    code reads the key this fixture writes — an anti-drift pin, not a
    proof of the daemon's real key name.  The assertions are
    therefore about *our* handling — the value arrives unchanged,
    typed ``str`` — and make no claim the daemon really stores
    anything at that path until a live-daemon inspect closes the gap
    (§3.1 point 4).

    Arrange: a stub whose ``get`` returns a container whose canned
    attrs carry the parameterised ``StartedAt``.
    Act: ``backend.inspect(handle)``.
    Assert: ``result.started_at`` is the fixture string, strictly —
    the ``isinstance(str)`` check is explicit, so a coercion to
    ``datetime`` fails loudly rather than comparing unequal.
    """
    handle = _handle()
    container = _RecordingContainer(
        _attrs(state, started_at=started_at), container_id=handle.id
    )
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    result = backend.inspect(handle)

    assert isinstance(result.started_at, str)
    assert result.started_at == started_at
    containers = cast("_RecordingContainers", stub.containers)
    assert containers.get_calls == [_RecordedGet(container_id=handle.id)]


# ---------------------------------------------------------------------------
# Behaviour 24 — the not-found contract (§4.3), paired with FakeBackend
# ---------------------------------------------------------------------------


def test_inspect_on_vanished_container_returns_gone_without_raising() -> None:
    """A container the lookup reports missing reads ``GONE`` — never
    raises, and carries no exit code.

    §4.3: "``inspect`` returns ``ContainerState.GONE``".  The absent
    container has exited neither successfully nor at all, so the
    status carries ``exit_code=None`` and ``started_at=None`` — a
    ``0`` here would report a clean exit about a container no one can
    ask about.  ``FakeBackend.inspect`` honours the same contract
    (behaviour 12);
    ``test_inspect_contract_matches_fake_backend`` pins the agreement.

    Arrange: a stub whose ``get`` records the call and then raises the
    SDK's ``NotFound`` — the exception ``get`` documents for a missing
    container (containers-list-filters.md §5), built through the SDK's
    own 404 classifier (errors.md §2).
    Act: ``backend.inspect(handle)`` — must **not** raise.
    Assert: ``state is GONE``, ``exit_code is None``,
    ``started_at is None``; the lookup happened exactly once, by id —
    the absence was discovered by asking, not assumed.
    """
    handle = _handle()
    container = _RecordingContainer(_attrs("running"), container_id=handle.id)
    stub = _RecordingClient(container=container, get_error=_vanished_container_404())
    backend = _backend_with(stub)

    result = backend.inspect(handle)

    assert isinstance(result, ContainerStatus)
    assert result.handle == handle
    assert result.state is ContainerState.GONE
    assert result.exit_code is None
    assert result.started_at is None
    containers = cast("_RecordingContainers", stub.containers)
    assert containers.get_calls == [_RecordedGet(container_id=handle.id)]


def _fake_inspect(state: str | None) -> tuple[ContainerState, int | None]:
    """Drive ``FakeBackend.inspect`` for one scenario; the observable half.

    The fake's documented lifecycle (behaviour 12): ``start`` →
    ``RUNNING`` with ``exit_code=None``; ``stop`` → ``EXITED`` with
    exit code ``0`` (its clean stop); ``vanish`` → unknown → ``GONE``
    with ``exit_code=None``.

    Args:
        state: The container's state before the inspect under test:
            ``"running"``, ``"stopped"`` (stopped once) or ``None``
            (vanished out of band via ``vanish``).

    Returns:
        The ``(state, exit_code)`` pair ``inspect`` reports — the
        observable every seam consumer can see without a daemon.
    """
    fake = FakeBackend()
    handle = fake.start(_spec())
    if state == "stopped":
        fake.stop(handle, timeout_s=5.0)
    elif state is None:
        fake.vanish(handle)
    status = fake.inspect(handle)
    return status.state, status.exit_code


def test_inspect_contract_matches_fake_backend() -> None:
    """Both backends must agree on the §4.3 ``inspect`` contract — or
    the fast unit tests rest on a lie.

    ``FakeBackend`` shipped this contract in behaviour 12 (a running
    container reports ``RUNNING`` with ``exit_code=None`` — "it has
    exited neither successfully nor at all"; a stopped one ``EXITED``;
    a vanished one ``GONE`` **without raising**); the plan's §4.3
    contract decision says ``DockerBackend`` must implement the *same
    observable contract*.  This test runs the same three scenarios —
    running, stopped, vanished — through both backends and demands
    agreement on ``(state, exit_code)``:

    1. running → ``RUNNING`` / ``None`` — the "``None``, not ``0``"
       edge on both sides;
    2. stopped → ``EXITED`` / ``0`` — a clean stop is a ``0`` on both
       sides (the docker fixture carries ``ExitCode`` ``0``, the
       daemon's value for a clean stop);
    3. vanished → ``GONE`` / ``None`` **without raising** (the
       load-bearing half: a raise here turns M2b's reconciliation
       into an unhandled traceback).

    ``started_at`` is not compared: the fake has no runtime clock and
    always reports ``None``; the docker half passes the daemon's
    string through (its own dedicated test).  A disagreement in
    either direction fails this test naming the scenario.
    """
    scenarios: tuple[tuple[str, str | None], ...] = (
        ("running", "running"),
        ("stopped", "stopped"),
        ("vanished", None),
    )
    for label, status in scenarios:
        fake_state, fake_exit = _fake_inspect(status)

        handle = _handle()
        if status is None:
            # Vanished: the lookup itself raises the SDK's NotFound —
            # the docker half of the fake's vanished record.
            container = _RecordingContainer(_attrs("running"), container_id=handle.id)
            get_error: BaseException | None = _vanished_container_404()
        elif status == "running":
            container = _RecordingContainer(_attrs("running"), container_id=handle.id)
            get_error = None
        else:
            container = _RecordingContainer(
                _attrs("exited", exit_code=0), container_id=handle.id
            )
            get_error = None
        stub = _RecordingClient(container=container, get_error=get_error)
        backend = _backend_with(stub)

        try:
            docker_result = backend.inspect(handle)
        except Exception as exc:
            pytest.fail(
                f"DockerBackend.inspect raised {exc!r} in the {label!r} "
                f"scenario while FakeBackend returns a ContainerStatus "
                f"(§4.3: not-found returns GONE, never raises)"
            )

        assert (fake_state, fake_exit) == (
            docker_result.state,
            docker_result.exit_code,
        ), (
            f"DockerBackend.inspect disagreed with FakeBackend in the "
            f"{label!r} scenario: {(docker_result.state, docker_result.exit_code)}, "
            f"expected {(fake_state, fake_exit)}"
        )


# ---------------------------------------------------------------------------
# Behaviour 24 — availability is not state (a blanket catch must fail)
# ---------------------------------------------------------------------------


def test_inspect_on_dead_daemon_surfaces_backend_unavailable_not_gone() -> None:
    """Daemon-unreachable is **not** gone — it must not be swallowed.

    A bare ``requests`` connection error (errors.md §3, [CORRECTED
    2026-09-16]) means the daemon is gone: the container is not
    *known* to have vanished, the read simply could not happen.
    ``map_sdk_error`` maps that row to ``BackendUnavailableError``
    (behaviour 19), and swallowing it as ``GONE`` would make every
    outage read as "every container has been removed out of band".
    The no-op applies to *state* (missing), never to *availability*.

    This is the test a blanket ``except Exception`` returning a
    ``GONE`` status fails: it would return where a taxonomy member
    must be raised, and ``pytest.raises`` records that as ``DID NOT
    RAISE``.

    Arrange: a stub whose ``get`` records the call then raises the
    connection error.
    Act: ``backend.inspect(handle)``, expected to raise.
    Assert: ``BackendUnavailableError`` — **not** a ``GONE`` status
    returned, **not** a ``DockerException`` — with the raw error
    chained as ``__cause__``; the lookup happened once.
    """
    handle = _handle()
    error = _daemon_unreachable()
    container = _RecordingContainer(_attrs("running"), container_id=handle.id)
    stub = _RecordingClient(container=container, get_error=error)
    backend = _backend_with(stub)

    with pytest.raises(BackendUnavailableError) as excinfo:
        backend.inspect(handle)
    raised = excinfo.value
    assert not isinstance(raised, docker.errors.DockerException)
    assert isinstance(raised, BackendError)
    assert raised.__cause__ is error
    containers = cast("_RecordingContainers", stub.containers)
    assert containers.get_calls == [_RecordedGet(container_id=handle.id)]


def test_inspect_on_daemon_refusal_is_routed_not_swallowed() -> None:
    """A daemon 500 during the lookup is routed through
    ``map_sdk_error`` — it must not become ``GONE``.

    The 500 is the row that proves *routing*, not *classification*:
    the mapping table is behaviour 19's and is not re-tested here —
    only that whatever ``get`` raises passes through
    ``map_sdk_error`` and the result is raised, the raw SDK exception
    chained as ``__cause__`` and no ``docker.errors.DockerException``
    escaping.  A blanket ``except Exception`` returning a ``GONE``
    status fails this test the same way it fails the dead-daemon test:
    a daemon refusal is an availability failure, and reading it as
    ``GONE`` tells reconciliation "removed out of band" about a
    container the daemon could not even be asked about.

    Arrange: a stub whose ``get`` records the call then raises the 500
    built through the SDK's own classifier (errors.md §2).
    Act: ``backend.inspect(handle)``, expected to raise.
    Assert: a ``BackendError``-family member, not a
    ``DockerException``, with the raw 500 as ``__cause__``; the
    lookup happened once.
    """
    handle = _handle()
    error = _server_error_500()
    container = _RecordingContainer(_attrs("running"), container_id=handle.id)
    stub = _RecordingClient(container=container, get_error=error)
    backend = _backend_with(stub)

    with pytest.raises(BackendError) as excinfo:
        backend.inspect(handle)
    raised = excinfo.value
    assert not isinstance(raised, docker.errors.DockerException)
    assert raised.__cause__ is error
    containers = cast("_RecordingContainers", stub.containers)
    assert containers.get_calls == [_RecordedGet(container_id=handle.id)]
