"""RED step for M2a behaviour 21 — ``DockerBackend.start``.

See ``plans/m2a-container-backend-seam.md`` §4.5 and behaviour 21 (§5,
**amended**): the call pair is ``client.containers.create(**build_run_kwargs(spec))``
then ``.start()`` on the container object the ``create`` call returned.  The
amendment's reasoning — ``run(detach=True)`` returns before any exit check and
**auto-pulls a missing image**, so ``ImageNotFound`` would never surface — is
recorded in behaviour 14's amendment (plan §5) and in the saved reference
``plan/third-party-docs/docker/containers-run-create.md`` §1 "Which call for a
detached start".  A test asserting ``run`` was never called is what keeps that
decision from being quietly undone, so it lives here.

**The shell is thin on purpose (plan §4.5), and this file pins exactly that.**
``build_run_kwargs`` is pure and exhaustively tested by behaviours 14–18, so
``start``'s entire job is: call ``create`` with that function's output, call
``start`` on the result, build a handle, and route every SDK exception through
``map_sdk_error`` (behaviour 19, whose mapping table is *not* re-tested here —
only the routing is).  The expected ``create`` kwargs are therefore **derived**
by calling ``build_run_kwargs(spec, label_namespace=…)`` and compared with the
recorded call; nothing in this file restates the kwargs in a dict, so the two
can never drift apart.  No test here would pass by adding branching to
``start``: every assertion is either a count, an identity, a derived equality
or a type.

**The call shape is cited, not assumed.**  ``create`` returns a
``docker.models.containers.Container`` object on which ``start`` is called —
not on the client.  Cited from the saved reference
``plan/third-party-docs/docker/containers-run-create.md`` §4:
"``create`` (line 921–928): returns ``Container``", re-verified against the
installed docker 7.2.0: ``ContainerCollection.create`` returns
``self.get(resp['Id'])`` (``.venv/lib/python3.11/site-packages/
docker/models/containers.py:914-937``) and ``Container.start`` forwards to
``self.client.api.start(self.id)`` (same file, lines 412-421).

**The stub's fidelity, and the trap this decision avoids.**  The installed
SDK's ``_create_container_args`` raises ``TypeError`` via
``create_unexpected_kwargs_error`` for any kwarg it does not know
(``containers-run-create.md`` §1 "Client-side guards";
``docker/models/containers.py:1123`` ff.), so a real client rejects a typo'd
kwarg that a permissive stub would swallow.  This stub is deliberately
*recording but not validating*: its ``create`` accepts exactly the shape the
call pair has — a single positional ``image`` plus keyword-only kwargs — and
records ``(image, kwargs)`` verbatim.  Validation of the kwarg *names* is not
re-done here: behaviours 14–18 already pin every name against the saved page
(``containers-run-create.md`` §2), and this behaviour's job is the *call
shape* — who is called, how many times, with what object — not a second
snapshot of the names.  Fidelity where it matters:

- ``create`` and ``run`` are separate recorded methods, so the
  "no ``run``" pin (``test_start_makes_no_run_call``) is a real assertion
  rather than an absence check on a permissive stub;
- the returned container object is a distinct object carrying its own
  ``start`` and a fixed ``id``, so "``start`` is called on *the object
  create returned*" (``test_start_calls_start_on_the_created_container``)
  and "the handle carries *the id the stub returned*"
  (``test_start_returns_handle_with_the_stubs_id_and_the_specs_fields``)
  are identity- and value-checks against a stub that cannot satisfy them by
  accident;
- an unexpected attribute on the stub raises ``AttributeError`` — a backend
  that reaches past ``containers.create``/``Container.start`` (for example a
  post-start ``reload()``) fails loudly instead of being waved through.

**The SDK exceptions in the error tests are built the way the SDK builds
them**, following the committed pattern of
``test_docker_backend_map_sdk_error.py``: the 409 runs a synthetic daemon
response through ``docker.errors.create_api_error_from_http_exception`` — the
single classifier every non-2xx response passes through in production
(``plan/third-party-docs/docker/errors.md`` §2) — so its class, ``explanation``
and ``status_code`` derive from the response exactly as in production.  The
image-not-found case uses the classifier's own ``ImageNotFound`` class with
the daemon's "no such image: …" wording that the SDK's own fragment check
matches (same page, §2 "The 404 mapping").

The ``start`` signature is **already pinned** by the ``ContainerBackend``
protocol in ``src/tool_swap/backend/base.py`` (behaviour 8) and is not
re-pinned here; one test asserts the constructed backend satisfies that
runtime-checkable protocol.

This file is the RED step: ``DockerBackend`` exists (behaviour 20) but
defines no ``start`` yet, so every subject test fails *individually* at the
gate helper with its assertions present and reachable — never aborting pytest
collection.  No ``importorskip``, no skips.

Conventions: pytest, AAA, Google-style docstrings, Black at 88 columns,
ruff, ``filterwarnings = "error"`` — no test asserts a docker fact from
memory.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from types import ModuleType
from typing import Any, cast

import docker
import docker.errors
import pytest
import requests

from tool_swap.backend.base import ContainerBackend, ContainerHandle, ContainerSpec
from tool_swap.backend.errors import (
    BackendError,
    ContainerNameConflictError,
    ImageNotFoundError,
)

# Neutral label namespace, deliberately distinct from any configured
# default — this file must not restate one (the discipline of
# test_docker_backend_build_run_kwargs.py, which uses "com.acme").
_NAMESPACE = "com.acme"

# The daemon's container-id for the name-conflict message: the SDK's
# classifier keeps it in the 409's explanation
# (plan/third-party-docs/docker/errors.md §2).
_CONFLICTING_ID = "f00dcafe00000000000000000000000000000000000000000000000000000000"

_URL = "http://docker/v1.45/containers/create?name=ms-llama"


# ---------------------------------------------------------------------------
# The RED gate (attribute-level, per behaviours 19/20's committed pattern)
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
    """Construct ``DockerBackend(stub, …)`` with ``start`` present.

    While ``start`` is absent this raises ``AssertionError`` naming the
    missing method, so the subject tests fail individually rather than
    aborting the run.

    Args:
        stub: The recording client to inject.

    Returns:
        The constructed backend.

    Raises:
        AssertionError: the module or the ``DockerBackend`` class is
            missing, or the class still defines no ``start`` method — the
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
    if not hasattr(backend_cls, "start"):
        raise AssertionError(
            "DockerBackend.start is missing — the GREEN step must add the "
            "start method to src/tool_swap/backend/docker_backend.py "
            "(behaviour 21)"
        )
    return backend_cls(stub, label_namespace=_NAMESPACE, container_prefix="ms-")


# ---------------------------------------------------------------------------
# The spec
# ---------------------------------------------------------------------------


def _spec(**overrides: Any) -> ContainerSpec:
    """A fully-exercising spec with neutral, non-default values.

    Unlike the behaviour-14 snapshot spec, this one sets *every* optional
    field (``mounts``, ``devices``, ``shm_size``, ``cpus``, ``memory``,
    ``published_port``) so the derived-kwarg equality in the happy-path
    tests covers the whole output shape, including the
    ``device_requests`` entry whose elements are ``docker.types.
    DeviceRequest`` objects (``DictType`` subclasses — compared by value).
    Values are deliberately distinct from ``BUILT_IN_DEFAULTS``.
    """
    from tool_swap.backend.base import MountSpec

    defaults: dict[str, Any] = {
        "tool": "llama",
        "name": "ms-llama",
        "image": "example/tool:1.0",
        "gpu_runtime": "cuda",
        "container_port": 8080,
        "env": {"FOO": "bar"},
        "labels": {"app": "test-tool"},
        "network": "llm-network",
        "mounts": (MountSpec(source="/host/data", target="/data"),),
        "devices": (1,),
        "shm_size": "1g",
        "cpus": 1.0,
        "memory": "16g",
        "published_port": 7001,
    }
    defaults.update(overrides)
    return ContainerSpec(**defaults)


# ---------------------------------------------------------------------------
# The recording stub
# ---------------------------------------------------------------------------


@dataclass
class _RecordedCreate:
    """One recorded ``create`` call: the positional image and the kwargs."""

    image: str
    kwargs: dict[str, Any]


class _RecordingContainer:
    """A stand-in for the ``Container`` object ``create`` returns.

    The real object is a ``docker.models.containers.Container`` on which
    ``start`` is a method and ``id`` the runtime id
    (``containers-run-create.md`` §4;
    ``docker/models/containers.py:412-421``).  Only those two members are
    provided, plus a call record for ``start``; anything else raises
    ``AttributeError`` by default.
    """

    #: The runtime id ``create`` reports for this container.
    id: str = "deadbeef"

    def __post_init__(self) -> None:
        """Record every ``start`` call's kwargs, in order."""
        self.start_calls: list[dict[str, Any]] = []

    def start(self, **kwargs: Any) -> None:
        """Record the call; the SDK's ``Container.start(**kwargs)`` shape."""
        self.start_calls.append(kwargs)


class _RecordingContainers:
    """A stand-in for ``client.containers``: ``create`` and ``run`` only.

    ``create`` and ``run`` are *separate* recorded methods — a permissive
    stub that accepted both through one catch-all would make the
    "no ``run``" pin impossible to assert.  Neither method validates its
    kwargs: the kwarg *names* are pinned by behaviours 14–18 against
    ``containers-run-create.md`` §2, and this behaviour owns the *call
    shape*, not a second snapshot (see the module docstring).
    """

    def __init__(
        self,
        result: _RecordingContainer | None = None,
        error: BaseException | None = None,
    ) -> None:
        """Prepare the recorded behaviour of ``create``.

        Args:
            result: The container object ``create`` returns (``None`` when
                ``error`` is set).
            error: Exception ``create`` raises (``None`` for the happy
                path).
        """
        self._result = result
        self._error = error
        self.create_calls: list[_RecordedCreate] = []
        self.run_calls: list[dict[str, Any]] = []

    def create(self, image: str, **kwargs: Any) -> _RecordingContainer:
        """Record the call; return the prepared container or raise."""
        self.create_calls.append(_RecordedCreate(image=image, kwargs=kwargs))
        if self._error is not None:
            raise self._error
        if self._result is None:  # pragma: no cover - fixture misuse
            raise AssertionError("stub.create called but no result prepared")
        return self._result

    def run(self, *args: Any, **kwargs: Any) -> None:
        """Record the call; the real ``run`` is what must never happen."""
        self.run_calls.append({"args": args, "kwargs": kwargs})
        raise AssertionError(
            "stub.run was called — the start path is create + start, not run"
        )


class _RecordingClient:
    """A stand-in for the injected ``docker.DockerClient``.

    Carries exactly the one attribute the call pair touches —
    ``containers`` — and nothing else, so a backend that reaches past the
    call pair fails with ``AttributeError`` rather than being waved
    through by a permissive stub (see the module docstring for the
    fidelity decision).
    """

    def __init__(
        self,
        result: _RecordingContainer | None = None,
        error: BaseException | None = None,
    ) -> None:
        """Build the client around one prepared ``create`` outcome.

        Args:
            result: The container object ``create`` returns.
            error: Exception ``create`` raises.
        """
        self.containers = _RecordingContainers(result=result, error=error)


# ---------------------------------------------------------------------------
# The error fixtures (built the way the SDK builds them)
# ---------------------------------------------------------------------------


def _name_conflict_409(container_name: str) -> docker.errors.APIError:
    """A 409 carrying the daemon's name-conflict phrase.

    Runs the synthetic daemon response through
    ``docker.errors.create_api_error_from_http_exception`` — the single
    classifier every non-2xx response passes through in production
    (``plan/third-party-docs/docker/errors.md`` §2) — with the daemon's
    quoted-name shape ``The container name "/<name>" is already in use by
    container "<id>"`` (the shape ``_conflict_name`` in the seam reads).
    """
    message = (
        f'The container name "/{container_name}" is already in use by '
        f'container "{_CONFLICTING_ID}"'
    )
    response = requests.Response()
    response.status_code = 409
    response.url = _URL
    response.reason = "Conflict"
    response._content = json.dumps({"message": message}).encode("utf-8")
    http_error = requests.exceptions.HTTPError(
        f"409 Client Error: {message} for url: {_URL}",
        response=response,
    )
    with pytest.raises(docker.errors.APIError) as excinfo:
        docker.errors.create_api_error_from_http_exception(http_error)
    return cast("docker.errors.APIError", excinfo.value)


def _image_not_found_404(image_ref: str) -> docker.errors.ImageNotFound:
    """An ``ImageNotFound`` with the daemon's missing-image wording.

    Uses the classifier's own ``ImageNotFound`` class — a 404 subclass
    (``plan/third-party-docs/docker/errors.md`` §2) — with the "no such
    image: …" wording the SDK's fragment check matches, built with the
    same constructor call the classifier makes
    (``cls(http_error, response=…, explanation=…)``).
    """
    message = f"no such image: {image_ref}"
    response = requests.Response()
    response.status_code = 404
    response.url = _URL
    response.reason = "Not Found"
    response._content = json.dumps({"message": message}).encode("utf-8")
    http_error = requests.exceptions.HTTPError(
        f"404 Client Error: {message} for url: {_URL}",
        response=response,
    )
    return docker.errors.ImageNotFound(
        http_error, response=response, explanation=message
    )


def _server_error_500() -> docker.errors.APIError:
    """A generic 500 — a daemon refusal with no dedicated taxonomy row.

    Routed through the same classifier as the other fixtures
    (``errors.md`` §2); ``map_sdk_error`` must turn it into the
    ``BackendError`` family rather than let it escape the seam.
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


# ---------------------------------------------------------------------------
# Behaviour 21 — the call shape
# ---------------------------------------------------------------------------


def test_start_makes_exactly_one_create_with_the_pure_functions_kwargs() -> None:
    """``create`` is called exactly once, with ``build_run_kwargs``'s output.

    Arrange: a recording stub whose ``create`` returns a container, and a
    spec exercising every optional field.
    Act: ``backend.start(spec)``.
    Assert: exactly one ``create`` call; its positional ``image`` is
    ``spec.image``; its kwargs dict **equals the fresh result of calling
    ``build_run_kwargs(spec, label_namespace=…)``** — derived, never
    restated, so this file cannot drift from the behaviour-14–18
    snapshots.  If the backend passes its stored ``label_namespace`` (it
    was constructed with ``_NAMESPACE``), the two agree; any other
    namespace, dropped key or retyped value fails the equality.
    """
    spec = _spec()
    stub = _RecordingClient(result=_RecordingContainer())
    backend = _backend_with(stub)
    backend.start(spec)

    containers = cast("_RecordingContainers", stub.containers)
    assert len(containers.create_calls) == 1
    recorded = containers.create_calls[0]
    assert recorded.image == spec.image
    module = _get_docker_backend_module()
    expected = module.build_run_kwargs(spec, label_namespace=_NAMESPACE)
    assert recorded.kwargs == expected


def test_start_calls_start_on_the_created_container_exactly_once() -> None:
    """The second half of the pair: ``.start()`` on the object ``create`` returned.

    Arrange: a recording stub returning a container with its own ``start``
    and a fixed ``id``.
    Act: ``backend.start(spec)``.
    Assert: exactly one ``start`` call, on the *same object* ``create``
    returned (identity — the SDK's ``Container`` is where ``start`` lives,
    ``containers-run-create.md`` §4), with no arguments (the SDK's
    ``Container.start(**kwargs)`` takes none the seam needs).  ``create``
    still happened exactly once.
    """
    spec = _spec()
    container = _RecordingContainer()
    stub = _RecordingClient(result=container)
    backend = _backend_with(stub)
    backend.start(spec)

    containers = cast("_RecordingContainers", stub.containers)
    assert len(containers.create_calls) == 1
    assert containers.create_calls[0].image == spec.image
    assert container.start_calls == [{}]


def test_start_makes_no_run_call() -> None:
    """``run`` is never called — the amendment's pin, recorded here.

    ``run(detach=True)`` was rejected because it returns before any exit
    check and auto-pulls a missing image (behaviour 14's amendment, plan
    §5; ``containers-run-create.md`` §1).  The stub records ``run`` as a
    separate method, so this is a positive assertion on the record, not
    an absence check on a permissive stub; the stub's ``run`` body also
    raises, so a call would fail even if the record assertion were
    bypassed.
    """
    spec = _spec()
    stub = _RecordingClient(result=_RecordingContainer())
    backend = _backend_with(stub)
    backend.start(spec)

    containers = cast("_RecordingContainers", stub.containers)
    assert containers.run_calls == []
    assert len(containers.create_calls) == 1


# ---------------------------------------------------------------------------
# Behaviour 21 — the returned handle
# ---------------------------------------------------------------------------


def test_start_returns_handle_with_the_stubs_id_and_the_specs_fields() -> None:
    """The handle carries the stub's ``id`` plus the spec's three fields.

    Arrange: a stub whose container reports a fixed runtime id.
    Act: ``backend.start(spec)``.
    Assert: the return value is a ``ContainerHandle`` equal to one built
    from the stub's ``id`` and the spec's ``name``, ``tool`` and
    ``image`` — the handle is the seam's identity unit
    (``base.py`` :class:`ContainerHandle` docstring), so equality of all
    four fields is the whole contract.
    """
    spec = _spec()
    container_id = "deadbeef"
    stub = _RecordingClient(result=_RecordingContainer(id=container_id))
    backend = _backend_with(stub)
    handle = backend.start(spec)

    assert isinstance(handle, ContainerHandle)
    assert handle == ContainerHandle(
        id=container_id, name=spec.name, tool=spec.tool, image=spec.image
    )


def test_start_satisfies_the_container_backend_protocol() -> None:
    """The constructed backend satisfies the behaviour-8 protocol.

    ``start``'s signature is pinned by the runtime-checkable
    ``ContainerBackend`` protocol in ``base.py`` (behaviour 8) — this
    test only pins that the shipped class conforms, so the seam the
    lifecycle components are written against is the one ``start`` lives
    on.
    """
    stub = _RecordingClient(result=_RecordingContainer())
    backend = _backend_with(stub)
    assert isinstance(backend, ContainerBackend)


# ---------------------------------------------------------------------------
# Behaviour 21 — error routing (no raw SDK exception escapes the seam)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error_factory", "expected_type"),
    [
        ("image_not_found", ImageNotFoundError),
        ("server_error_500", BackendError),
    ],
)
def test_start_routes_create_errors_through_map_sdk_error(
    error_factory: str, expected_type: type
) -> None:
    """A ``create`` failure surfaces the taxonomy member, never the raw SDK error.

    Rows:

    - ``image_not_found``: an ``ImageNotFound`` 404 ("no such image: …")
      surfaces as ``ImageNotFoundError`` — the edge case the amended
      call pair exists to keep honest (``run``'s auto-pull would have
      hidden it);
    - ``server_error_500``: a generic daemon refusal surfaces as the
      ``BackendError`` family — the row that proves *every* SDK exception
      passes through ``map_sdk_error`` (behaviour 19), not just the two
      named ones.

    Arrange: a stub whose ``create`` raises the prepared exception.
    Act: ``backend.start(spec)``, expected to raise.
    Assert: the raised exception is the taxonomy member — **not** an
    instance of ``docker.errors.DockerException`` (the base of every SDK
    error, so no raw SDK exception can escape) and not the raw input —
    it is a ``BackendError`` subclass; the raw SDK exception is chained
    as ``__cause__``; and ``container.start`` was never called (the
    container was never created).
    """
    spec = _spec()
    if error_factory == "image_not_found":
        error = _image_not_found_404(spec.image)
    else:
        error = _server_error_500()
    stub = _RecordingClient(result=None, error=error)
    backend = _backend_with(stub)

    with pytest.raises(expected_type) as excinfo:
        backend.start(spec)
    raised = excinfo.value
    assert not isinstance(raised, docker.errors.DockerException)
    assert isinstance(raised, BackendError)
    assert raised.__cause__ is error
    containers = cast("_RecordingContainers", stub.containers)
    assert len(containers.create_calls) == 1
    assert containers.run_calls == []


def test_start_routes_name_conflict_409_to_container_name_conflict_error() -> None:
    """A taken-name 409 surfaces ``ContainerNameConflictError``.

    Arrange: a stub whose ``create`` raises the 409 carrying the daemon's
    quoted-name phrase for ``spec.name``.
    Act: ``backend.start(spec)``, expected to raise.
    Assert: ``ContainerNameConflictError`` — a ``BackendError`` subclass
    and **not** a ``docker.errors.DockerException`` — with the raw 409
    chained as ``__cause__``; ``container.start`` was never called.
    (The *mapping table* that turns the phrase into this class is
    behaviour 19's; this test pins only that ``start`` routes through it.)
    """
    spec = _spec()
    error = _name_conflict_409(spec.name)
    stub = _RecordingClient(result=None, error=error)
    backend = _backend_with(stub)

    with pytest.raises(ContainerNameConflictError) as excinfo:
        backend.start(spec)
    raised = excinfo.value
    assert not isinstance(raised, docker.errors.DockerException)
    assert raised.__cause__ is error
    containers = cast("_RecordingContainers", stub.containers)
    assert len(containers.create_calls) == 1
    assert containers.run_calls == []
