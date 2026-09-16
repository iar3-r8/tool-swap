"""RED step for M2a behaviour 19 — ``map_sdk_error``, SDK exception →
taxonomy.

See ``plans/m2a-container-backend-seam.md`` §5 behaviour 19, §4.3 and
§0.1.2 pull request A: ``map_sdk_error(exc)`` is the pure, total
translation of an SDK exception — or anything else that went wrong —
into a member of the taxonomy
``src/tool_swap/backend/errors.py`` that the caller raises.
``DockerBackend.start`` (behaviour 21) and every other method pass
their SDK exception through it, so no raw SDK exception escapes the
seam.  No client, no daemon, no ``DockerBackend`` class in this
file — those are behaviours 20+.

A new file rather than an addition to
``test_docker_backend_build_run_kwargs.py``: that file is the home
of behaviours 14–18, its docstring names ``map_sdk_error`` as
deliberately out of scope there (line 23), and its fixtures are
``ContainerSpec``s while this behaviour's inputs are exception
instances.  One file per ledger behaviour is also the
``FakeBackend`` slice's convention (behaviours 10–13).

**The signature pinned here.**  The plan names the function and the
file but not the signature:

    def map_sdk_error(exc: BaseException) -> BackendError: ...

- a module-level function in ``tool_swap.backend.docker_backend``
  (behaviour 19's file), pure — no client, no daemon, no
  environment;
- one parameter, ``exc``, no default; the function is **total**: it
  never raises, it *returns* an exception for the caller to raise,
  for any input at all — including an input that is not an
  exception;
- the returned member always chains the original input as
  ``__cause__``, so the diagnostic trail is preserved;
- the original text is never swallowed: the returned member's
  ``message`` carries a distinctive part of the input's text for
  every row of the table.

**The mapping** (plan §4.3, read against the saved reference
``plan/third-party-docs/docker/errors.md``, captured and
re-verified against the installed docker 7.2.0):

- 404 whose daemon message names a missing image — an
  ``ImageNotFound``, or a ``NotFound`` carrying that message —
  maps to ``ImageNotFoundError`` (remedy names the image ref and
  ``tswap build``);
- any other 404 (a vanished container) maps to
  ``ContainerNotFoundError`` (message names the container id);
- a refused start whose message names a taken name (409 "already
  in use") maps to ``ContainerNameConflictError`` (remedy names
  the conflicting name and ``tswap down``);
- an ``APIError`` whose text matches the GPU fragments (decision
  4) maps to ``GpuUnavailableError`` (remedy names the NVIDIA
  container toolkit);
- any other ``APIError`` maps to ``ContainerStartError`` (message
  carries the daemon's text);
- a dead daemon — a bare ``requests`` connection error from an
  operational call, or the construction-path ``DockerException`` —
  maps to ``BackendUnavailableError`` (remedy names the daemon /
  ``DOCKER_HOST`` check);
- anything else — an unrelated ``DockerException`` included, and
  non-exception inputs — maps to ``BackendError``, the fallback,
  preserving the original text.

Four decisions this red step records, each forced by
``plan/third-party-docs/docker/errors.md``:

1. **The ``isinstance`` ordering is pinned by tests, not by
   comment.**  ``APIError`` inherits ``requests.exceptions.HTTPError``
   (§1), a ``requests.exceptions.RequestException``, an ``OSError``
   — so a broad ``requests`` catch placed before the ``APIError``
   check would map every 4xx/5xx to "daemon unreachable".  The test
   ``test_api_error_not_swallowed_by_requests_catch`` sanity-asserts
   that its 500 fixture *is* a ``RequestException`` (the hazard is
   present in the fixture itself) and then demands
   ``ContainerStartError`` — only a wrong order can fail the
   mapping assertion.  Likewise ``ImageNotFound`` is a ``NotFound``
   (§1): ``test_image_not_found_not_shadowed_by_parent_check``
   sanity-asserts the ``isinstance`` overlap and demands the
   child's mapping, so a parent check placed first fails visibly
   rather than shadowing silently.
2. **404s are classified by the daemon's message, not by the SDK's
   class.**  The SDK itself classifies 404s by string-matching the
   daemon's ``message`` (§2 "The 404 mapping") and records that an
   ``ImageNotFound`` **degrades** to a plain ``NotFound`` if the
   daemon's wording ever stops matching — and advises catching the
   parent where either is acceptable.  The mapping therefore
   catches ``NotFound`` (covering both) and re-classifies by the
   same daemon-message fragments: an image message maps to
   ``ImageNotFoundError`` whatever class the SDK chose, any other
   404 maps to ``ContainerNotFoundError``.
   ``test_degraded_image_not_found_classified_by_message`` pins
   that with a ``NotFound`` carrying an image message.
3. **A dead daemon has two shapes** (§3, [CORRECTED 2026-09-16]).
   An *operational* call propagates a bare
   ``requests.exceptions.ConnectionError`` (a ``RequestException``,
   an ``OSError``) with no ``DockerException`` in sight, while
   *construction* — ``APIClient.__init__`` with ``version``
   ``None``/``'auto'`` — wraps ``except Exception`` into a
   ``DockerException`` "Error while fetching server API version:
   …" with the connection error as ``__cause__``
   (``api/client.py:221–232``).  ``BackendUnavailableError`` must
   therefore be reachable from **both** hierarchies, while an
   unrelated ``DockerException`` — a *reachable* daemon that
   answered malformedly — must fall through to the ``BackendError``
   fallback.  The rows ``construction_path_dead_daemon``,
   ``operational_dead_daemon_connection_error``,
   ``operational_dead_daemon_connect_timeout`` and
   ``docker_exception_other_is_fallback`` pin the distinction.
4. **A GPU failure has no dedicated SDK class — the distinction is
   a message heuristic, and this file says so plainly.**
   ``docker.errors`` has no GPU-related class (§1: the complete
   class list was read; §3), and a refused device request surfaces
   as a bare ``APIError`` (§2: ``create`` and ``start`` raise
   ``APIError``), so the daemon's **text** is the only channel that
   separates "the GPU could not be satisfied" from "the daemon
   refused the start for another reason".  The mapping therefore
   matches the ``APIError``'s text, **case-insensitively**, against
   the fragments ``"nvidia"`` and ``"gpu"``.  This is an
   **explicitly brittle heuristic**, legitimate only because no
   stable interface exists — the same kind of string matching the
   SDK itself uses to classify 404s (§2).  The fragments are named
   after the documented shape of the request: ``"nvidia"`` is the
   driver name ``BUILT_IN_DEFAULTS.gpu_runtime`` carries and
   ``GpuUnavailableError``'s own remedy names, and ``"gpu"`` is the
   capability string of the canonical ``DeviceRequest`` form
   (``plan/third-party-docs/docker/gpu-device-requests.md`` §1).
   The rows pin each fragment independently, pin
   case-insensitivity, and pin that a message matching neither
   stays ``ContainerStartError``.  **No saved page records the
   daemon's exact refusal text for a device request**, so the
   fixture messages are representative shapes, not citations — the
   assertions are about *our* mapping, never about the daemon's
   wording.

**Fixture synthesis — no fixture merely has the right class.**
Every ``APIError`` is built by running a synthetic
``requests.Response`` (status code, URL, reason and a JSON body
``{"message": …}``) through the SDK's own
``docker.errors.create_api_error_from_http_exception`` — the single
classifier every non-2xx response passes through in production
(§2).  So the class chosen (including the 404 image-vs-container
split), ``explanation``, ``status_code`` and
``is_client_error``/``is_server_error`` all derive from the
response exactly as they would in production, and a fixture whose
``status_code`` did not work could not be built this way.  The
degraded ``NotFound`` uses the same constructor call the
classifier makes, choosing the parent class — the exact shape §2
describes when the daemon's wording stops matching.  The
construction-path ``DockerException`` reproduces
``APIClient._retrieve_server_version``'s exact message template and
``from`` chaining (``api/client.py:221–232``, as recorded in
errors.md §3).  The operational dead-daemon fixtures are real
``requests`` connection errors — the shape §3's corrected table
records for every operational call.

This file is the RED step: ``map_sdk_error`` does not exist in
``src/tool_swap/backend/docker_backend.py`` yet (the module exists
— behaviour 14's GREEN created it — so the gate is attribute-level,
with a module-level fallback).  Every access is deferred out of
module scope into call-time helpers via
``importlib.import_module`` (the precedent:
``test_docker_backend_build_run_kwargs.py``), so every test fails
*individually* at the gate with its assertions present and
reachable.  No ``importorskip``, no skips — a skipped test is not a
red step.

Conventions: pytest, AAA, Google-style docstrings, table-driven
over constructed exception instances, ``filterwarnings = "error"``
— no fixture emits a warning.
"""

from __future__ import annotations

import importlib
import inspect
import json
from collections.abc import Callable
from types import ModuleType
from typing import cast

import docker.errors
import pytest
import requests
import requests.exceptions

from tool_swap.backend.errors import (
    BackendError,
    BackendUnavailableError,
    ContainerNameConflictError,
    ContainerNotFoundError,
    ContainerStartError,
    GpuUnavailableError,
    ImageNotFoundError,
)

#: The URL a synthetic daemon response pretends to come from — the
#: ``create`` endpoint, where behaviour 21's start path (this
#: behaviour's main consumer) lives.
_URL = "http://docker/v1.45/containers/create?name=ms-llama"

#: Distinctive fixture values, so a containment assertion can fail
#: only on a real mapping defect, never on a generic ``str()``.
IMAGE_REF = "example/tool:1.0"
CONTAINER_NAME = "ms-llama"
CONTAINER_ID = "abc123def456"

_REASONS = {404: "Not Found", 409: "Conflict", 500: "Internal Server Error"}

#: One row of the mapping table: input factory, expected taxonomy
#: class, required ``message`` substrings, required ``remedy``
#: substrings.
Row = tuple[Callable[[], object], type[BackendError], tuple[str, ...], tuple[str, ...]]


def _get_docker_backend_module() -> ModuleType:
    """Import ``tool_swap.backend.docker_backend`` at call time, RED-safely.

    The import is deferred out of module scope — via
    ``importlib.import_module`` so that a missing module cannot
    abort pytest *collection* of this file (and thereby of the whole
    suite).  While the module is absent this raises
    ``AssertionError`` naming the missing module, so every test
    fails individually instead of the run being interrupted.

    Raises:
        AssertionError: ``tool_swap.backend.docker_backend`` does
            not exist yet — the GREEN step must create
            ``src/tool_swap/backend/docker_backend.py``.
    """
    try:
        module: ModuleType = importlib.import_module("tool_swap.backend.docker_backend")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tool_swap.backend.docker_backend is missing — the GREEN step "
            "must create src/tool_swap/backend/docker_backend.py"
        ) from exc
    return module


def _map_sdk_error() -> Callable[..., BackendError]:
    """Import and return the ``map_sdk_error`` function, RED-safely.

    Raises:
        AssertionError: the module does not exist yet (see
            :func:`_get_docker_backend_module`), or it does not
            define ``map_sdk_error`` yet — the GREEN step must
            define it as a module-level function.
    """
    module = _get_docker_backend_module()
    try:
        fn = module.map_sdk_error
    except AttributeError as exc:
        raise AssertionError(
            "tool_swap.backend.docker_backend.map_sdk_error is missing — "
            "the GREEN step must define map_sdk_error in "
            "src/tool_swap/backend/docker_backend.py"
        ) from exc
    return cast("Callable[..., BackendError]", fn)


def _daemon_response(status_code: int, message: str) -> requests.Response:
    """A synthetic daemon response: status, URL, reason and JSON body.

    The body shape ``{"message": …}`` is what
    ``create_api_error_from_http_exception`` reads for
    ``explanation`` (errors.md §1: "the daemon's ``message`` field,
    extracted in ``create_api_error_from_http_exception``").
    """
    response = requests.Response()
    response.status_code = status_code
    response.url = _URL
    response.reason = _REASONS[status_code]
    response._content = json.dumps({"message": message}).encode("utf-8")
    return response


def _api_error(status_code: int, message: str) -> docker.errors.APIError:
    """Build an ``APIError`` the way the SDK builds it.

    Runs the synthetic response through
    ``docker.errors.create_api_error_from_http_exception`` — the
    single classifier every non-2xx response passes through in
    production (errors.md §2) — and returns the exception it
    raises.  The class chosen (including the 404 image-vs-container
    split), ``explanation``, ``status_code`` and
    ``is_client_error``/``is_server_error`` therefore derive from
    the response exactly as in production; a fixture whose
    ``status_code`` did not work could not be built this way.
    """
    response = _daemon_response(status_code, message)
    http_error = requests.exceptions.HTTPError(
        f"{status_code} Client Error: {message} for url: {_URL}",
        response=response,
    )
    with pytest.raises(docker.errors.APIError) as excinfo:
        docker.errors.create_api_error_from_http_exception(http_error)
    return cast("docker.errors.APIError", excinfo.value)


def _degraded_image_not_found() -> docker.errors.NotFound:
    """A 404 the classifier *would* have called ``ImageNotFound``.

    The daemon's wording is matched by the SDK's own fragment
    check, but the fixture chooses the parent ``NotFound`` with the
    **same constructor call the classifier makes** (``cls(http_error,
    response=…, explanation=…)``) — the exact degradation errors.md
    §2 warns about when the daemon's wording stops matching, in
    every respect identical except for the class.
    """
    message = f"no such image: {IMAGE_REF}"
    response = _daemon_response(404, message)
    http_error = requests.exceptions.HTTPError(
        f"404 Client Error: {message} for url: {_URL}",
        response=response,
    )
    return docker.errors.NotFound(http_error, response=response, explanation=message)


def _construction_dead_daemon(
    cause: BaseException,
) -> docker.errors.DockerException:
    """A dead daemon seen at client construction time.

    Replicates ``APIClient._retrieve_server_version``'s exact wrap
    (``api/client.py:221–232``, as recorded in errors.md §3
    [CORRECTED 2026-09-16]): the connection error re-raised as a
    ``DockerException`` "Error while fetching server API version:
    …" with the original chained as ``__cause__``.
    """
    error = docker.errors.DockerException(
        f"Error while fetching server API version: {cause}"
    )
    error.__cause__ = cause
    return error


def _docker_exception_malformed_response() -> docker.errors.DockerException:
    """A ``DockerException`` that is **not** a dead daemon.

    The *other* wrap of ``APIClient._retrieve_server_version``
    (``api/client.py:221–228``, as recorded in errors.md §3): a
    reachable daemon answered without an ``ApiVersion`` key.  The
    daemon is up — the response is malformed — and the mapping must
    not call that unavailable.
    """
    cause = KeyError("ApiVersion")
    error = docker.errors.DockerException(
        'Invalid response from docker daemon: key "ApiVersion" is missing.'
    )
    error.__cause__ = cause
    return error


#: The mapping table: (row id, input factory, expected taxonomy
#: class, substrings the returned ``message`` must carry,
#: substrings the returned ``remedy`` must carry — compared
#: case-insensitively).  An empty remedy tuple leaves that row's
#: remedy to the class default, which §4.3 already names.
_RAW_ROWS: list[tuple[str, Row]] = [
    (
        "image_not_found_404",
        lambda: _api_error(404, f"no such image: {IMAGE_REF}"),
        ImageNotFoundError,
        (IMAGE_REF,),
        (IMAGE_REF, "tswap build"),
    ),
    (
        "image_not_found_degraded_to_not_found",
        _degraded_image_not_found,
        ImageNotFoundError,
        (IMAGE_REF,),
        (IMAGE_REF, "tswap build"),
    ),
    (
        "container_vanished_404",
        lambda: _api_error(404, f"No such container: {CONTAINER_ID}"),
        ContainerNotFoundError,
        (CONTAINER_ID,),
        (),
    ),
    (
        "name_conflict_409",
        lambda: _api_error(
            409,
            f'Conflict. The container name "/{CONTAINER_NAME}" is already '
            f'in use by container "{CONTAINER_ID}"',
        ),
        ContainerNameConflictError,
        (CONTAINER_NAME,),
        (CONTAINER_NAME, "tswap down"),
    ),
    (
        "conflict_409_without_name_message",
        lambda: _api_error(
            409, "Conflict. the container is pinned to a different host"
        ),
        ContainerStartError,
        ("pinned to a different host",),
        (),
    ),
    (
        "gpu_unavailable_driver_named",
        lambda: _api_error(
            500,
            "Error response from daemon: could not select device driver "
            '"nvidia" with capabilities: [[gpu]]',
        ),
        GpuUnavailableError,
        ("could not select device driver",),
        ("nvidia",),
    ),
    (
        "gpu_unavailable_toolkit_named_mixed_case",
        lambda: _api_error(
            500,
            "Error response from daemon: OCI runtime exec failed: "
            "NVIDIA-container-cli: initialization error",
        ),
        GpuUnavailableError,
        ("NVIDIA-container-cli",),
        ("nvidia",),
    ),
    (
        "gpu_unavailable_capability_named",
        lambda: _api_error(
            500,
            "Error response from daemon: device request failed: no "
            'device with capability "gpu" available',
        ),
        GpuUnavailableError,
        ("no device with capability",),
        ("nvidia",),
    ),
    (
        "generic_500_api_error",
        lambda: _api_error(
            500,
            "Error response from daemon: driver failed programming "
            "external connectivity",
        ),
        ContainerStartError,
        ("external connectivity",),
        (),
    ),
    (
        "construction_path_dead_daemon",
        lambda: _construction_dead_daemon(
            requests.exceptions.ConnectionError(
                "Max retries exceeded (caused by NewConnectionError)"
            )
        ),
        BackendUnavailableError,
        ("Error while fetching server API version",),
        ("DOCKER_HOST",),
    ),
    (
        "operational_dead_daemon_connection_error",
        lambda: requests.exceptions.ConnectionError(
            "Max retries exceeded (caused by NewConnectionError)"
        ),
        BackendUnavailableError,
        ("Max retries exceeded",),
        ("DOCKER_HOST",),
    ),
    (
        "operational_dead_daemon_connect_timeout",
        lambda: requests.exceptions.ConnectTimeout(
            "timed out connecting to the daemon"
        ),
        BackendUnavailableError,
        ("timed out connecting",),
        ("DOCKER_HOST",),
    ),
    (
        "docker_exception_other_is_fallback",
        _docker_exception_malformed_response,
        BackendError,
        ('key "ApiVersion" is missing',),
        (),
    ),
    (
        "unrecognised_value_error",
        lambda: ValueError("some caller bug"),
        BackendError,
        ("some caller bug",),
        (),
    ),
    (
        "unrecognised_runtime_error",
        lambda: RuntimeError("stream parse failed"),
        BackendError,
        ("stream parse failed",),
        (),
    ),
]

_ROWS = [
    pytest.param((factory, expected, message_parts, remedy_parts), id=row_id)
    for row_id, factory, expected, message_parts, remedy_parts in _RAW_ROWS
]


def test_map_sdk_error_is_module_level_function() -> None:
    """Behaviour 19: a pure function — no client, no daemon, no class.

    The function lives at module level in
    ``tool_swap.backend.docker_backend`` (the plan's file for
    behaviour 19) rather than as a method of a class that carries a
    client — that is what makes it table-testable with no stub.
    """
    # Act
    fn = _map_sdk_error()
    # Assert
    assert inspect.isfunction(fn)


def test_map_sdk_error_signature_single_parameter_no_default() -> None:
    """The pinned contract: ``map_sdk_error(exc)`` — pure and total.

    One parameter named ``exc`` and nothing else: no label
    namespace, no client, no keyword-only extras — the mapping reads
    nothing but the exception itself (plan §5 behaviour 19,
    "Pure; no daemon"), and a default would invent a "no error"
    input the seam never has.
    """
    # Arrange
    fn = _map_sdk_error()
    # Act
    params = inspect.signature(fn).parameters
    # Assert
    assert list(params) == ["exc"]
    assert params["exc"].default is inspect.Parameter.empty
    assert params["exc"].kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.POSITIONAL_ONLY,
    )


@pytest.mark.parametrize("row", _ROWS)
def test_map_sdk_error_maps_sdk_exception_to_taxonomy(row: object) -> None:
    """Table-driven: each constructed SDK exception maps to its §4.3 member.

    The rows, in ``_RAW_ROWS`` with their citations: the 404
    image/container split (including the degraded ``NotFound`` —
    errors.md §2), the 409 name conflict, the GPU message heuristic
    and its generic negative (decision 4), the two dead-daemon
    hierarchies plus the reachable-daemon ``DockerException``
    negative (decision 3), and the ``BackendError`` fallback for
    unrecognised exceptions.  Every row asserts the *exact*
    taxonomy member (the taxonomy is flat — a sibling would be a
    wrong remedy), that the original text survives in
    ``message``, that the remedy names the actionable thing
    (§4.3's remedy column), and that the original input is chained
    as ``__cause__``.
    """
    factory, expected, message_parts, remedy_parts = cast("Row", row)
    # Arrange
    original = factory()
    fn = _map_sdk_error()
    # Act
    result = fn(original)
    # Assert: the exact taxonomy member, not a sibling.
    assert type(result) is expected, (
        f"expected {expected.__name__}, got {type(result).__name__}: {result!r}"
    )
    # The original text is never swallowed.
    for part in message_parts:
        assert part in result.message
    # The remedy names the actionable thing (case-insensitive: the
    # remedy's capitalisation is the taxonomy's, not the fixture's).
    for part in remedy_parts:
        assert part.lower() in result.remedy.lower()
    # The original exception is chained as __cause__.
    assert result.__cause__ is original


def test_map_sdk_error_never_raises_on_any_input() -> None:
    """Error behaviour: ``map_sdk_error`` *returns*; it never raises.

    Pinned for every row of the table (every SDK shape) and for an
    input that is not an exception at all: the function is total, so
    a programming error at the seam — a string where an exception
    was expected — becomes a ``BackendError`` the caller can raise,
    with the text preserved and the object chained, rather than a
    ``TypeError`` escaping the seam.
    """
    # Arrange
    fn = _map_sdk_error()
    non_exception: object = "a bare string that is not an exception"
    # Act / Assert: every input returns a taxonomy member, chained.
    for _row_id, factory, *_rest in _RAW_ROWS:
        original = factory()
        result = fn(original)
        assert isinstance(result, BackendError), (
            f"expected a BackendError, got {type(result).__name__}"
        )
        assert result.__cause__ is original
    # Act
    result = fn(non_exception)
    # Assert: the non-exception's text is preserved, never swallowed.
    assert isinstance(result, BackendError)
    assert result.__cause__ is non_exception
    assert "a bare string" in result.message


def test_api_error_not_swallowed_by_requests_catch() -> None:
    """Ordering pin: an ``APIError`` *is* a ``requests`` error.

    Cited from ``plan/third-party-docs/docker/errors.md`` §1
    (``APIError`` inherits ``requests.exceptions.HTTPError``) and
    §3's consequence ("order the handlers so ``APIError`` is
    matched first"): a broad ``requests`` catch placed before the
    ``APIError`` check would map this very fixture to
    ``BackendUnavailableError``.  The sanity assertion proves the
    shadowing hazard is present in the fixture itself, so only a
    wrong *order* can fail the mapping assertion.
    """
    # Arrange
    original = _api_error(
        500,
        "Error response from daemon: driver failed programming external connectivity",
    )
    assert isinstance(original, requests.exceptions.RequestException)
    fn = _map_sdk_error()
    # Act
    result = fn(original)
    # Assert
    assert type(result) is ContainerStartError


def test_image_not_found_not_shadowed_by_parent_check() -> None:
    """Ordering pin: an ``ImageNotFound`` *is* a ``NotFound``.

    Cited from ``plan/third-party-docs/docker/errors.md`` §1
    (``ImageNotFound(NotFound)``): a parent check placed first would
    shadow the child and hand a missing image to the
    vanished-container mapping.  The sanity assertions prove the
    overlap, so only a wrong order can fail the mapping assertion.
    """
    # Arrange
    original = _api_error(404, f"no such image: {IMAGE_REF}")
    assert type(original) is docker.errors.ImageNotFound
    assert isinstance(original, docker.errors.NotFound)
    fn = _map_sdk_error()
    # Act
    result = fn(original)
    # Assert
    assert type(result) is ImageNotFoundError


def test_degraded_image_not_found_classified_by_message() -> None:
    """The 404 mapping follows the daemon's message, not the SDK's class.

    ``plan/third-party-docs/docker/errors.md`` §2 records that the
    SDK classifies 404s by string-matching the daemon's message,
    and that an ``ImageNotFound`` degrades to a plain ``NotFound``
    if the daemon's wording stops matching — and advises catching
    the parent where either is acceptable.  The mapping therefore
    re-classifies by the daemon's message: this fixture is a
    ``NotFound`` (sanity-asserted, not an ``ImageNotFound``)
    carrying an image message, and must still map to
    ``ImageNotFoundError`` naming the ref.
    """
    # Arrange
    original = _degraded_image_not_found()
    assert type(original) is docker.errors.NotFound
    assert not isinstance(original, docker.errors.ImageNotFound)
    fn = _map_sdk_error()
    # Act
    result = fn(original)
    # Assert
    assert type(result) is ImageNotFoundError
    assert IMAGE_REF in result.remedy
