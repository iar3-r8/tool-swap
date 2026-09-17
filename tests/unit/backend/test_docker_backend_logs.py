"""RED step for M2a behaviour 26 — ``DockerBackend.logs``.

See ``plans/m2a-container-backend-seam.md`` behaviour 26 (§5) and the
§4.3 contract decision.  ``logs(handle, *, follow, tail) ->
Iterator[str]`` (the signature is pinned by the ``ContainerBackend``
protocol in ``src/tool_swap/backend/base.py``, behaviour 8) must:

1. **ask the daemon for a byte stream with the follow decision made
   explicit** — the call is ``container.logs(stream=True,
   follow=<follow>, tail=<tail>)`` on the object the shared lookup
   ``client.containers.get`` (behaviours 22-24) returns.  ``stream``
   is always ``True``: only the streaming form yields the chunks the
   seam reassembles into lines (``plan/third-party-docs/docker/
   container-logs.md`` §2, [READ]: the stream form is a generator of
   bytes).  ``follow`` must be passed **explicitly, never omitted**:
   the SDK's ``follow`` parameter defaults to ``None`` and
   ``if follow is None: follow = stream`` (saved page §1, kwarg
   table — "``follow`` silently equals ``stream``"), so an omitted
   ``follow`` with ``stream=True`` would turn a ``follow=False``
   request into a stream that follows forever.  ``tail`` is passed
   through verbatim, ``0`` included — the saved page §1 records that
   only *invalid* ints (< 0, non-int) are silently reset to
   ``'all'``; a falsy drop such as ``tail or "all"`` would make
   ``tail=0`` read the *entire* log of a long-lived tool container
   (saved page §3: the default ``tail='all'`` is unbounded).  The
   strict equality on the recorded kwargs in
   ``test_logs_pins_call_shape_stream_true_explicit_follow_and_tail``
   is what pins all three, and the absence of ``stdout`` /
   ``stderr`` / ``timestamps`` / ``since`` / ``until`` — their
   defaults (``True`` / ``True`` / ``False`` / ``None`` / ``None``,
   saved page §1 kwarg table) are what the seam wants, and there is
   no reason to pass them.

2. **decode the byte chunks with ``errors="replace"`` and rejoin
   chunks split mid-line** — the output is always ``bytes`` and is
   never decoded by the SDK (saved page §2, [READ]), and a chunk's
   boundary falls wherever the daemon's frames fall — routinely
   inside a line.  Decoding and splitting each chunk independently
   fragments every line a boundary touches; the seam must buffer the
   bytes and yield only reassembled lines (below).

3. **raise ``ContainerNotFoundError`` for a missing container** —
   the *opposite* of behaviours 22-24: §4.3 grants the not-found
   no-op to ``is_running``, ``inspect`` and ``stop`` only, and says
   "every other method raises".  ``FakeBackend.logs`` already raises
   (behaviour 13), and the parity test at the bottom of this file
   pins that this is the one place in the slice where parity means
   *both raise* — a copy-paste of the previous no-op parity test
   would assert the wrong contract here.  The raise is **eager, on
   the call, not on first iteration**: the not-found tests wrap
   *the call* in ``pytest.raises`` and never call ``next()``, so a
   plain generator-function body — where everything runs on the
   first ``next()`` — would surface the error only during
   iteration and fail them with ``DID NOT RAISE``.  Eager is the
   contract: a caller asking for the log of a container that is not
   there must know on the call, and ``FakeBackend.logs`` is eager
   for the same reason (its snapshot note: a lazy generator would
   read the buffer after the call returned).

**The newline contract is ours, not an SDK fact.**  The SDK hands
over raw bytes and says nothing about line framing (saved page §2:
"the caller must ``.decode(...)`` explicitly").  The contract this
file pins, for the GREEN step to implement:

- lines are split on ``b"\\n"`` only, and each yielded line is
  **stripped of its trailing newline** — a log line is the text
  between terminators, and a consumer that must strip newlines
  itself has been handed framing the seam should own;
- a trailing partial line (no terminating newline at the end of the
  stream) is **flushed as the final line** rather than dropped —
  the last line of a live log is the one the operator most wants,
  and a log viewer that silently swallows it is a data-loss bug by
  this repository's own KISS rule ("never a silent bug").

These two are decisions of this seam, stated here because nothing in
the saved reference pins them; they are **not** claims about the
daemon's or the SDK's behaviour.

**The rejoining fixture is the substantive test, and it is designed
to be defeated only by buffering.**  The stub yields three chunks
whose boundaries fall *inside* lines — ``b"line on"``,
``b"e\\nline two"``, ``b"\\nline three\\n"`` (byte offsets 0, 7 and
17 of ``b"line one\\nline two\\nline three\\n"``): the first boundary
splits "line one" mid-word, and the second chunk both *starts* with
the terminator of the previous line and *ends* mid-line.  A
non-buffering implementation that decodes and splits each chunk
independently yields the four fragments ``"line on"``, ``"e"``,
``"line two"``, ``"line three"`` and fails; a stub that yielded one
clean line per chunk would let that implementation pass while
corrupting every real multi-chunk stream.  A correct implementation
— one that accumulates bytes and emits only reassembled lines —
yields exactly the three reassembled lines.

**The evidence ceiling, stated plainly.**  The stub emulates the
daemon's line-based ``tail`` (the saved page §1 kwarg table: "Output
specified number of lines at the end of logs.  Either an integer of
number of lines or the string ``all``") and returns canned byte
chunks, so these tests pin *the call we make* and *our handling of
what comes back*.  Whether the daemon's tail really counts lines, or
what a real follow stream does when the daemon dies, is **not
claimed here** — no daemon runs in this environment, and "logs
survive a stop" is M7's requirement (§1 of the plan).  The tail
application in the stub is **[INFERRED]** from the kwarg docstring:
it is an anti-drift pin of the pass-through, not a proof of the
daemon's counting.

**``CancellableStream`` ends quietly — recorded, not tested.**  The
saved page §2 ([CORRECTED 2026-09-16]; the class lives at
``types/daemon.py:8``, not ``utils/socket.py``) records that
``CancellableStream.__next__`` converts ``ProtocolError`` **and**
``OSError`` into ``StopIteration`` (``types/daemon.py:27-33``,
[READ]): a follow stream broken by a dying daemon **ends quietly**,
and a truncated log looks exactly like a complete one to the caller.
That is a real property of the SDK that M2a cannot fix, and it is
*unobservable* in this environment — there is no daemon, and a stub
pretending to be a broken daemon would assert a property it merely
improvises, not one it demonstrates.  The right treatment is
therefore neither a test (unfalsifiable here) nor silence (M7's log
collector consumes exactly this API and must know its tail can be
truncated without error): it is this note, in the file where the
seam's ``logs`` is tested, so the next reader of behaviour 26 finds
the hazard next to the contract.

**The completeness pin lands here.**  When behaviour 21's tests were
corrected, ``test_start_satisfies_the_container_backend_protocol``
was removed: ``@runtime_checkable`` ``isinstance`` requires *every*
member to be present, and with five of the six methods shipped it
could only fail.  The pin moved to behaviour 26's red step, where the
last member arrives — that is now, and
``test_docker_backend_satisfies_the_container_backend_protocol`` is
the pin.  It asserts that ``DockerBackend`` itself — not a stub —
passes the ``isinstance`` check the moment ``logs`` exists.
**``build``'s absence is deliberately NOT re-asserted here**:
behaviour 8 already pins the protocol's exact member set (including
``build``'s absence, ``test_container_backend_does_not_declare_
build``), and §7 item 2 records the deferral to M5.  A second copy
of the pin against the implementation would be a test M5 must
*delete* when ``build`` legitimately lands, not a guard the seam
keeps — the protocol is the seam's contract, and its member set is
pinned once, at the protocol.

**The stub's fidelity.**  As in behaviours 21-25, the stub records
and never fails on its own: construction is plain (explicit
``__init__``, no dataclass ``__post_init__``), the ``logs`` call is
journaled **on entry, before any work** (so a test can assert the
call happened, and with which kwargs, even when the result was
empty), and the only exception that ever leaves a stub method is the
SDK/transport exception *prepared in the test body* for the
``get`` lookup.  The stub container exposes exactly ``id`` and
``logs`` — **not** ``stop``, **not** ``start``, **not** ``attrs``,
**not** ``status``, **not** ``reload``: a ``logs`` call must fetch
and read, never mutate or re-inspect.  The stream it returns is a
plain ``Iterator[bytes]`` — the plan's "stub yielding byte chunks" —
and carries no ``close()``: the seam's contract is iteration, and
the saved page records ``close()`` as the way to abort an *open*
follow early, which is follow-stream territory this slice does not
claim.

This file is the RED step: ``DockerBackend`` exists (behaviour 20)
with ``start`` (21), ``stop`` (22), ``is_running`` (23), ``inspect``
(24) and ``list_managed`` (25) but no ``logs``, so every subject
test fails *individually* at the attribute-level gate with its
assertions present and reachable — never aborting pytest
collection.  No ``importorskip``, no skips.

Conventions: pytest, AAA, Google-style docstrings, Black at 88
columns, ruff, ``filterwarnings = "error"`` — no test asserts a
docker fact from memory; each is cited to the saved reference
above, and the [INFERRED] claims are marked as such in their
docstrings.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from types import ModuleType
from typing import cast

import docker.errors
import pytest
import requests

from tool_swap.backend.base import ContainerBackend, ContainerHandle
from tool_swap.backend.errors import (
    BackendUnavailableError,
    ContainerNotFoundError,
)
from tool_swap.backend.fake_backend import FakeBackend

# Neutral label namespace, deliberately distinct from any configured
# default — the discipline of test_docker_backend_start.py, which uses
# "com.acme".
_NAMESPACE = "com.acme"

# The runtime id both the handle and the stub container carry, so "look
# the container up by the handle's id" is an identity check.
_CONTAINER_ID = "deadbeef"

# The inspect URL the missing container's 404 would carry — ``get``
# performs a full inspect (containers-list-filters.md §5), and it is
# the lookup, not the logs call, that reports the container missing.
_URL = f"http://docker/v1.45/containers/{_CONTAINER_ID}"


# ---------------------------------------------------------------------------
# The RED gate (attribute-level, per behaviours 19/20/21/22/23/24/25's pattern)
# ---------------------------------------------------------------------------


def _get_docker_backend_module() -> ModuleType:
    """Import ``tool_swap.backend.docker_backend`` at call time.

    The import is deferred out of module scope via
    ``importlib.import_module`` so a missing module could not abort
    pytest *collection* of this file.  While the module is absent
    this raises ``AssertionError`` naming the missing module, so
    every test fails individually instead of the run being
    interrupted.

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
    """Construct ``DockerBackend(stub, …)`` with ``logs`` present.

    While ``logs`` is absent this raises ``AssertionError`` naming
    the missing method, so the subject tests fail individually
    rather than aborting the run.

    Args:
        stub: The recording client to inject.

    Returns:
        The constructed backend.

    Raises:
        AssertionError: the module or the ``DockerBackend`` class is
            missing, or the class still defines no ``logs`` method —
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
    if not hasattr(backend_cls, "logs"):
        raise AssertionError(
            "DockerBackend.logs is missing — the GREEN step must add "
            "the logs method to "
            "src/tool_swap/backend/docker_backend.py (behaviour 26)"
        )
    return backend_cls(stub, label_namespace=_NAMESPACE, container_prefix="ms-")


# ---------------------------------------------------------------------------
# The fixtures
# ---------------------------------------------------------------------------


def _handle() -> ContainerHandle:
    """The handle whose container ``logs`` must look up by ``id``."""
    return ContainerHandle(
        id=_CONTAINER_ID, name="ms-llama", tool="llama", image="example/tool:1.0"
    )


def _expected_logs_kwargs(*, follow: bool, tail: int) -> dict[str, object]:
    """The exact ``container.logs`` kwargs behaviour 26 pins.

    ``stream`` is always ``True`` (the seam reassembles lines from
    the chunk stream — the non-streaming form returns the whole log
    as one ``bytes`` blob, saved page §2 [READ]); ``follow`` is
    passed **explicitly** because the SDK's ``follow`` defaults to
    ``None`` and silently equals ``stream`` (saved page §1);
    ``tail`` is the caller's value, verbatim — ``0`` included,
    since only *invalid* ints are reset to ``'all'`` (saved page
    §1).  The strict equality in the consuming tests also pins the
    *absence* of ``stdout`` / ``stderr`` / ``timestamps`` /
    ``since`` / ``until``: their saved-page defaults are what the
    seam wants, and passing them would be noise.
    """
    return {"stream": True, "follow": follow, "tail": tail}


def _last_n_lines(log: bytes, n: int) -> bytes:
    """The last ``n`` lines of ``log``, in the seam's line concept.

    The stub's daemon-side ``tail`` emulation, split on ``b"\\n"``
    only — the same line concept the seam's contract uses — with the
    terminators kept so a line split mid-way cannot be reassembled
    wrongly downstream.  A trailing partial line (no terminator)
    counts as a line, matching the seam's flush-the-remainder
    contract.

    Args:
        log: The daemon's full log, as bytes.
        n: How many trailing lines to keep.

    Returns:
        The byte range of the last ``n`` lines, or ``b""`` when
        ``n`` is ``0`` — note that ``list[-0:]`` would select
        *everything*, so the zero is special-cased.
    """
    if n == 0:
        return b""
    parts = log.split(b"\n")
    pieces: list[bytes] = [part + b"\n" for part in parts[:-1]]
    if parts[-1]:
        pieces.append(parts[-1])
    return b"".join(pieces[-n:])


def _apply_tail(log: bytes, tail: object) -> bytes:
    """Apply the recorded ``tail`` kwarg the way the daemon's does.

    The saved page §1 kwarg table: "Output specified number of
    lines at the end of logs.  Either an integer of number of lines
    or the string ``all``" — an int ``N`` (``0`` included) is
    honoured, and only *invalid* ints (< 0, non-int) are silently
    reset to ``'all'`` (saved page §1, line 860-861 of the cited
    source).  A non-int — ``None`` or ``'all'`` — means the whole
    log.  **[INFERRED]**: the page pins the kwarg and its docstring,
    and the daemon-side application follows from ``tail`` being a
    parameter of the request; the stub emulates, it does not prove.

    Args:
        log: The daemon's full log, as bytes.
        tail: The value the backend passed as ``tail``.

    Returns:
        The byte range the daemon would stream back.
    """
    if isinstance(tail, bool) or not isinstance(tail, int):
        return log
    return _last_n_lines(log, tail)


def _chunks(log: bytes, chunk_at: tuple[int, ...]) -> list[bytes]:
    """Split ``log`` at the recorded byte offsets — mid-line allowed.

    The offsets are chosen by the test so that a chunk boundary
    falls *inside* a line: that is the shape of a real daemon frame
    stream (saved page §2: "one or more log frames after header
    stripping", [READ]), and it is what defeats a per-chunk decode
    and split.

    Args:
        log: The byte range the daemon would stream back.
        chunk_at: Byte offsets at which to cut; offsets outside the
            range are ignored (a tail shorter than the offsets'
            span must not crash the stub).

    Returns:
        The chunks, in order; ``[]`` for an empty range.  The last
        segment always runs to ``len(log)`` — without the terminal
        cut, everything after the last recorded offset (with the
        default ``(0,)`` that is the whole log) would be dropped
        silently.
    """
    if not log:
        return []
    cuts = [0] + [offset for offset in chunk_at if 0 < offset < len(log)] + [len(log)]
    return [log[cuts[i] : cuts[i + 1]] for i in range(len(cuts) - 1)]


# ---------------------------------------------------------------------------
# The recording stub
# ---------------------------------------------------------------------------


@dataclass
class _RecordedGet:
    """One recorded ``get`` call: the container id it was asked for."""

    container_id: str


@dataclass
class _RecordedLogsCall:
    """One recorded ``logs`` call: the kwargs it was passed, verbatim."""

    kwargs: dict[str, object]


class _LoggingContainer:
    """A stand-in for the ``Container`` object ``get`` returns.

    The real object is a ``docker.models.containers.Container``
    whose ``logs(**kwargs)`` forwards every kwarg to
    ``client.api.logs`` (saved page §1, models/containers.py:294)
    and returns an iterator of ``bytes`` in the streaming form
    (saved page §2, [READ]).  This stub mirrors the surface the
    ``logs`` path uses — ``id`` and ``logs`` — and **nothing else**:
    **not** ``stop``, **not** ``start``, **not** ``attrs``, **not**
    ``status``, **not** ``reload``.  A ``logs`` call must fetch and
    read, never mutate or re-inspect, and a backend reaching for a
    member the path does not use hits ``AttributeError`` rather
    than being waved through by a permissive stub.

    The stream returned is a plain ``Iterator[bytes]`` — the
    plan's "stub yielding byte chunks" — with no ``close()``: the
    seam's contract is iteration, and the saved page records
    ``close()`` as the abort for an *open follow* (saved page §2),
    which this slice does not claim.

    ``__init__`` is explicit, not a dataclass: the code under test
    wraps its calls in ``except Exception`` (the behaviour-21/22/
    23/24/25 pattern), so a construction failure raised *inside*
    ``logs`` would be routed through ``map_sdk_error`` and surface
    as a ``BackendError`` that looks like an implementation fault
    and is a test fault instead.  A recording stub must fail where
    it is called from — in the test body — never inside the seam it
    records.
    """

    def __init__(
        self,
        log: bytes,
        container_id: str = _CONTAINER_ID,
        chunk_at: tuple[int, ...] = (0,),
    ) -> None:
        """Store the id and the daemon log the stub will stream.

        Args:
            log: The daemon's full log, as bytes — the stub applies
                the caller's ``tail`` to it the way the daemon
                would (see :func:`_apply_tail`).
            container_id: The runtime id ``get`` reports.
            chunk_at: Byte offsets at which the streamed byte range
                is cut into chunks; ``(0,)`` (the default) is one
                chunk, and the tests that need mid-line boundaries
                pass explicit offsets.
        """
        self.id = container_id
        self._log = log
        self._chunk_at = chunk_at
        self.logs_calls: list[_RecordedLogsCall] = []

    def logs(self, **kwargs: object) -> Iterator[bytes]:
        """Record the call, apply the daemon's ``tail``, yield chunks.

        The call is journaled **on entry**, before the tail is
        applied, so the recorded kwargs are exactly what the seam
        sent — the pass-through pin — and a test can read them even
        when the result was empty (the ``tail=0`` case).

        Returns:
            The daemon's byte range for the recorded ``tail``, cut
            at the prepared offsets.
        """
        self.logs_calls.append(_RecordedLogsCall(kwargs=dict(kwargs)))
        return iter(_chunks(_apply_tail(self._log, kwargs.get("tail")), self._chunk_at))


class _RecordingContainers:
    """A stand-in for ``client.containers``: ``get`` only.

    ``get(self, container_id)`` mirrors the SDK signature
    (containers-list-filters.md §5, models/containers.py:939) and
    records the call **on entry, before any prepared exception is
    raised** — the same on-entry journaling the behaviour-21-25
    stubs apply — so a test can assert the lookup happened even
    when it failed.  No other member exists: a backend reaching for
    ``list``, ``create``, ``run`` or ``api`` hits ``AttributeError``.
    """

    def __init__(
        self,
        container: _LoggingContainer | None,
        error: BaseException | None = None,
    ) -> None:
        """Prepare the recorded behaviour of ``get``.

        Args:
            container: The object ``get`` returns (``None`` when
                ``error`` is set — the container is not there).
            error: Exception ``get`` raises after recording the
                call (``None`` for the happy path) — in practice the
                SDK's ``NotFound`` for the missing case, or a
                daemon/transport error; always prepared in the test
                body.
        """
        self._container = container
        self._error = error
        self.get_calls: list[_RecordedGet] = []

    def get(self, container_id: str) -> _LoggingContainer:
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

    Carries exactly the one attribute the ``logs`` path touches —
    ``containers`` — and nothing else, so a backend that reaches
    past ``containers.get`` / ``Container.logs`` fails with
    ``AttributeError`` rather than being waved through by a
    permissive stub.
    """

    def __init__(
        self,
        container: _LoggingContainer | None,
        get_error: BaseException | None = None,
    ) -> None:
        """Build the client around one prepared ``get`` outcome.

        Args:
            container: The object ``get`` returns (``None`` when
                ``get_error`` is set).
            get_error: Exception ``get`` raises after recording
                the call.
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
    ``docker.errors.create_api_error_from_http_exception``, the
    single path every non-2xx response takes in production (``plan/
    third-party-docs/docker/errors.md`` §2 "The 404 mapping") — so
    its class, ``explanation`` and ``status_code`` derive from the
    synthetic response exactly as in production.  The daemon's
    wording for a vanished container names the container, not an
    image, so it matches none of the image fragments and classifies
    as the plain ``NotFound``.
    """
    message = f"404 Client Error: Not Found for url: {_URL}"
    body = json.dumps({"message": message}).encode("utf-8")
    response = requests.Response()
    response.status_code = 404
    response.url = _URL
    response.reason = "Not Found"
    response._content = body
    http_error = requests.exceptions.HTTPError(
        f"404 Client Error: {message} for url: {_URL}", response=response
    )
    with pytest.raises(docker.errors.NotFound) as excinfo:
        docker.errors.create_api_error_from_http_exception(http_error)
    return cast("docker.errors.NotFound", excinfo.value)


def _daemon_unreachable() -> requests.exceptions.ConnectionError:
    """A dead daemon, as an operational call sees it.

    A bare ``requests`` connection error from a call against an
    unreachable daemon — the ``BackendUnavailableError`` row of
    behaviour 19's table (``plan/third-party-docs/docker/errors.md``
    §3, [CORRECTED 2026-09-16]: a connection failure on a later API
    call is never wrapped by docker-py, so it propagates out of
    ``requests`` as-is; ``map_sdk_error`` step 2 matches it).  This
    is what *not* being there is **not**: the daemon is gone, so
    the failure is availability, not state — and for ``logs``,
    unlike ``is_running`` / ``inspect`` / ``stop``, it must not be
    read as "the container is missing" either.
    """
    return requests.exceptions.ConnectionError(
        "Cannot connect to the Docker daemon at unix:///var/run/docker.sock"
    )


# ---------------------------------------------------------------------------
# Behaviour 26 — the call shape
# ---------------------------------------------------------------------------


def test_logs_pins_call_shape_stream_true_explicit_follow_and_tail() -> None:
    """The one ``logs`` call is exactly the pinned shape, explicitly.

    This is the argument-mapping test the saved page §1 forces:
    ``stream=True`` **and** ``follow=False`` together are the
    SDK's own documented "explicit non-following streaming form"
    (saved page §3: "reads to the end of the current log and
    stops").  The strict equality on the recorded kwargs pins:

    - ``stream=True`` — the seam reassembles lines from the chunk
      stream, and the non-streaming form returns the whole log as
      one ``bytes`` blob with no chunks to rejoin (saved page §2,
      [READ]);
    - ``follow`` **present and ``False``** — the load-bearing half.
      The SDK's ``follow`` defaults to ``None`` and
      ``if follow is None: follow = stream`` (saved page §1), so an
      implementation that omits ``follow`` sends a stream that
      follows forever for a ``follow=False`` request — the silent
      equality the pin exists to prevent.  A strict equality is
      what catches the omission: a subset check would not;
    - ``tail`` the caller's value, verbatim;
    - **no ``stdout`` / ``stderr`` / ``timestamps`` / ``since`` /
      ``until``** — their defaults (saved page §1 kwarg table) are
      what the seam wants.

    The lookup happens first — one ``get`` for the handle's id —
    and the ``logs`` call lands on the object the lookup returned.

    **Not claimed here:** what a real follow stream does over time
    — no daemon runs, and the deferred daemon tests (§7 item 7) are
    where a live follow would be observed.  This test pins the call
    we make.

    Arrange: a stub whose ``get`` returns a container whose daemon
    log is two lines.
    Act: ``backend.logs(handle, follow=False, tail=2)`` — must not
    raise.
    Assert: exactly one ``get`` for the handle's id, exactly one
    ``logs`` call with the pinned kwargs, and the reassembled lines.
    """
    container = _LoggingContainer(b"one\ntwo\n")
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    lines = list(backend.logs(_handle(), follow=False, tail=2))

    assert lines == ["one", "two"]
    assert stub.containers.get_calls == [_RecordedGet(container_id=_CONTAINER_ID)]
    assert len(container.logs_calls) == 1
    assert container.logs_calls[0].kwargs == _expected_logs_kwargs(follow=False, tail=2)


def test_logs_follow_true_is_passed_through_explicitly() -> None:
    """``follow=True`` reaches the daemon as ``follow=True``.

    The other half of the mapping pin: a caller that asks to follow
    must see ``follow is True`` on the recorded call, alongside the
    always-``True`` ``stream`` and the verbatim ``tail`` — the
    saved page §3 records ``tail + follow=True`` as the documented
    "last N lines then live" form, so both must reach the daemon
    together.

    **Not claimed here:** that the stream *stays open*.  The stub
    has no feed to follow — it yields its prepared chunks and ends,
    and that termination is a stub artifact.  Whether a real follow
    stream keeps delivering until stopped is daemon territory,
    deferred with the §7 item 7 daemon tests.

    Arrange: a stub whose ``get`` returns a container whose daemon
    log is two lines.
    Act: ``backend.logs(handle, follow=True, tail=2)`` — must not
    raise.
    Assert: the recorded kwargs carry ``follow is True`` (strict
    equality with the pinned shape) and the reassembled lines.
    """
    container = _LoggingContainer(b"first\nsecond\n")
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    lines = list(backend.logs(_handle(), follow=True, tail=2))

    assert lines == ["first", "second"]
    assert container.logs_calls[0].kwargs == _expected_logs_kwargs(follow=True, tail=2)


# ---------------------------------------------------------------------------
# Behaviour 26 — rejoining chunks split mid-line
# ---------------------------------------------------------------------------


def test_logs_rejoins_chunks_split_mid_line() -> None:
    """A chunk boundary inside a line must not fragment the line.

    This is the substantive test of the behaviour, and the fixture
    is built to defeat only buffering implementations.  The daemon
    log is ``b"line one\\nline two\\nline three\\n"`` (29 bytes),
    and the stub cuts it at byte offsets **0, 7 and 17**:

    - chunk 1, ``b"line on"`` — the first boundary falls *inside*
      "line one", between ``on`` and ``e``;
    - chunk 2, ``b"e\\nline two"`` — starts with the *terminator*
      of the previous line and ends *mid-way through* "line two";
    - chunk 3, ``b"\\nline three\\n"`` — starts with a terminator.

    A non-buffering implementation that decodes and splits each
    chunk independently yields the four fragments ``"line on"``,
    ``"e"``, ``"line two"``, ``"line three"`` and fails the
    equality below; a stub that yielded one clean line per chunk
    would let that implementation pass while corrupting every real
    multi-chunk stream — which is why the offsets, not the lines,
    are the fixture's point.  A correct implementation accumulates
    bytes and emits only complete, newline-terminated lines (the
    module docstring's newline contract), yielding exactly the
    three reassembled lines.

    The chunk shape is the real one: the saved page §2 records the
    stream as "one or more log frames after header stripping"
    ([READ]) — frames do not respect line boundaries.  **Not
    claimed here:** that the daemon *will* split at these offsets —
    the stub prepares them, and the pin is on *our* reassembly, not
    the daemon's framing.

    Arrange: a stub whose container streams the log cut at
    ``(0, 7, 17)``.
    Act: ``backend.logs(handle, follow=False, tail=3)`` — ``tail``
    equal to the line count, so the daemon returns the whole log.
    Assert: exactly the three reassembled lines, each a ``str``.
    """
    log = b"line one\nline two\nline three\n"
    container = _LoggingContainer(log, chunk_at=(0, 7, 17))
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    lines = list(backend.logs(_handle(), follow=False, tail=3))

    assert lines == ["line one", "line two", "line three"]
    assert all(isinstance(line, str) for line in lines)


def test_logs_lines_are_stripped_of_their_newline() -> None:
    """Each yielded line is stripped of its trailing newline.

    The seam's line contract (module docstring — **ours**, not an
    SDK fact: the SDK hands over raw bytes and leaves framing to
    the caller, saved page §2 [READ]): a line is the text between
    ``b"\\n"`` terminators, without the terminator.  A consumer
    that must strip newlines itself has been handed framing the
    seam should own, and a ``"one\\n"`` in a ``list[str]`` of "log
    lines" is a framing bug wearing a type's badge.

    Arrange: a stub streaming two terminated lines as one chunk.
    Act: ``backend.logs(handle, follow=False, tail=2)``.
    Assert: the lines equal the terminator-less text, and no
    yielded line contains a newline at all.
    """
    container = _LoggingContainer(b"a\nb\n")
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    lines = list(backend.logs(_handle(), follow=False, tail=2))

    assert lines == ["a", "b"]
    assert all("\n" not in line for line in lines)


def test_logs_final_line_without_newline_is_still_yielded() -> None:
    """A trailing partial line is flushed at the end of the stream.

    The second half of the seam's line contract (module docstring —
    **ours**): the last line of a live log routinely has no
    terminator yet, and a log viewer that silently drops it swallows
    exactly the line the operator most wants — a silent data-loss
    bug by this repository's own KISS rule.  An implementation that
    emits only newline-terminated lines yields ``["one"]`` here and
    fails.

    Arrange: a stub streaming ``b"one\\ntwo"`` — two and a half
    lines, the last unterminated.
    Act: ``backend.logs(handle, follow=False, tail=2)``.
    Assert: both lines are yielded, the partial one included.
    """
    container = _LoggingContainer(b"one\ntwo")
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    lines = list(backend.logs(_handle(), follow=False, tail=2))

    assert lines == ["one", "two"]


# ---------------------------------------------------------------------------
# Behaviour 26 — decoding
# ---------------------------------------------------------------------------


def test_logs_decodes_bad_bytes_with_replace_and_keeps_going() -> None:
    """One bad byte is replaced — it must not kill the stream.

    The plan's explicit edge: "``bytes`` are decoded with
    ``errors='replace'`` so one bad byte cannot kill the stream".
    The premise is the saved page's: the output is always ``bytes``
    and the SDK never decodes (saved page §2, [READ]) — a tool that
    writes an invalid UTF-8 byte to its log is a fact of life, and
    a ``.decode()`` without ``errors="replace"`` raises
    ``UnicodeDecodeError`` on it, killing the whole ``logs`` call
    after the bad line has already been streamed.  The test pins
    both directions at once: the bad byte becomes the replacement
    character **and** the lines after it are still delivered — an
    implementation that drops the bad line *and* the rest, or that
    raises, fails.

    Arrange: a stub streaming three lines, the middle one carrying
    ``0xff`` — a byte that is invalid as UTF-8 on its own.
    Act: ``backend.logs(handle, follow=False, tail=3)`` — must not
    raise.
    Assert: the middle line carries ``U+FFFD`` where the bad byte
    was, and the surrounding lines are intact.
    """
    container = _LoggingContainer(b"ok first\nbad \xff byte\nok last\n")
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    lines = list(backend.logs(_handle(), follow=False, tail=3))

    assert lines == ["ok first", "bad \ufffd byte", "ok last"]


# ---------------------------------------------------------------------------
# Behaviour 26 — tail
# ---------------------------------------------------------------------------


def test_logs_tail_zero_yields_nothing_and_passes_zero_through() -> None:
    """``tail=0`` yields nothing — and reaches the daemon as ``0``.

    The plan's explicit edge, and the falsy-drop trap: the saved
    page §1 records that only *invalid* ints (< 0, non-int) are
    reset to ``'all'`` — ``0`` is valid and is honoured, "Output
    specified number of lines" of which is zero.  An implementation
    that drops the falsy value — ``tail or "all"``, or an
    ``if tail:`` guard — sends ``"all"`` instead, and the daemon
    streams the *entire* log of a long-lived tool container (saved
    page §3: the default ``tail='all'`` is unbounded) — the same
    class of trap behaviour 22 pinned for ``timeout_s=0``.  The
    test pins both directions: the result is empty **and** the
    recorded kwargs carry ``tail == 0`` as an ``int`` — a
    ``"all"`` fails the strict equality before the result is even
    examined.

    Arrange: a stub whose container holds three lines.
    Act: ``backend.logs(handle, follow=False, tail=0)``.
    Assert: the result is ``[]`` and the recorded call passed
    ``tail=0`` verbatim.
    """
    container = _LoggingContainer(b"x\ny\nz\n")
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    lines = list(backend.logs(_handle(), follow=False, tail=0))

    assert lines == []
    assert len(container.logs_calls) == 1
    assert container.logs_calls[0].kwargs == _expected_logs_kwargs(follow=False, tail=0)
    assert isinstance(container.logs_calls[0].kwargs["tail"], int)


def test_logs_tail_returns_last_n_lines() -> None:
    """``tail=N`` keeps the last N lines, not the first N.

    The tail is line-based on the daemon side (saved page §1 kwarg
    table: "Output specified number of lines at the end of logs")
    — the seam passes it through and the stub emulates that
    application (see :func:`_apply_tail`, [INFERRED] from the
    kwarg docstring).  The same "last N" semantics are already
    pinned for ``FakeBackend.logs`` (behaviour 13: "``tail``
    returns the last N lines"), so a docker implementation that
    kept the *first* N would disagree with the fake on the same
    call.

    Arrange: a stub whose container holds five lines.
    Act: ``backend.logs(handle, follow=False, tail=2)``.
    Assert: the two trailing lines, in order.
    """
    container = _LoggingContainer(b"l1\nl2\nl3\nl4\nl5\n")
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    lines = list(backend.logs(_handle(), follow=False, tail=2))

    assert lines == ["l4", "l5"]


def test_logs_tail_larger_than_log_returns_everything() -> None:
    """A ``tail`` past the end of the log returns everything, not an
    error and not padding.

    The plan's fake-parity edge (behaviour 13: "``tail`` larger
    than the buffer returns everything"): a fresh container with
    two lines and a caller asking for the last ten has not made an
    error — the last ten lines of a two-line log are the two lines
    it has.  An implementation that passed a ``tail`` the daemon
    would treat as invalid (< 0, saved page §1) or that clamped
    client-side with a different arithmetic would diverge from the
    fake here.

    Arrange: a stub whose container holds two lines.
    Act: ``backend.logs(handle, follow=False, tail=10)``.
    Assert: both lines, in order.
    """
    container = _LoggingContainer(b"only one\nonly two\n")
    stub = _RecordingClient(container=container)
    backend = _backend_with(stub)

    lines = list(backend.logs(_handle(), follow=False, tail=10))

    assert lines == ["only one", "only two"]


# ---------------------------------------------------------------------------
# Behaviour 26 — a missing container RAISES (the §4.3 exception)
# ---------------------------------------------------------------------------


def test_logs_missing_container_raises_container_not_found() -> None:
    """A missing container raises ``ContainerNotFoundError``.

    The **opposite** of behaviours 22-24: §4.3 grants the not-found
    no-op to ``is_running``, ``inspect`` and ``stop`` only — "every
    other method raises" — and ``logs`` is one of the others.  The
    shared lookup reports the container missing (the SDK's
    ``NotFound`` from ``get``, containers-list-filters.md §5), and
    ``logs`` must surface the taxonomy member, never the raw SDK
    exception.  ``FakeBackend.logs`` raises the same member for the
    same input (behaviour 13), so the two implementations agree
    that asking for the log of a container that is not there is a
    caller error to be answered — not a state to be absorbed: the
    lenient read side exists so M2b's liveness sweep never
    tracebacks, and ``logs`` is not on the sweep's path.

    The ``__cause__`` is deliberately not pinned: the seam may
    raise the member directly from the missing lookup or route the
    ``NotFound`` through ``map_sdk_error`` (whose 404 row is
    ``ContainerNotFoundError`` anyway) — both are honest, and the
    pin is on *what the caller sees*, not on the internal route.

    Arrange: a stub whose ``get`` raises the SDK's own ``NotFound``
    (built through the classifier, errors.md §2).
    Act: ``backend.logs(handle, follow=False, tail=5)`` — expected
    to raise.
    Assert: ``ContainerNotFoundError``, not a
    ``docker.errors.DockerException``; the lookup happened once,
    for the handle's id.

    The ``pytest.raises`` wraps **the call**, not a ``next()``: the
    raise must be eager (module docstring, item 3), and a
    generator-function body would defer it to the first iteration
    and fail this test with ``DID NOT RAISE``.
    """
    error = _vanished_container_404()
    stub = _RecordingClient(container=None, get_error=error)
    backend = _backend_with(stub)

    with pytest.raises(ContainerNotFoundError) as excinfo:
        backend.logs(_handle(), follow=False, tail=5)
    raised = excinfo.value
    assert not isinstance(raised, docker.errors.DockerException)
    assert stub.containers.get_calls == [_RecordedGet(container_id=_CONTAINER_ID)]


def test_logs_on_dead_daemon_surfaces_backend_unavailable_not_not_found() -> None:
    """A dead daemon during the lookup is **not** a missing container.

    The availability half of the §4.3 split: a bare ``requests``
    connection error (errors.md §3, [CORRECTED 2026-09-16]) means
    the daemon is gone — the container is not *known* to be missing,
    the read simply could not happen.  Behaviours 22-24 swallow
    exactly the ``NotFound`` and route everything else; ``logs``
    must do the same, or an outage would read as "every container
    has been removed out of band" and a caller acting on that
    (M7's collector, reconciliation) would destroy state the daemon
    was merely unreachable to confirm.  ``map_sdk_error`` maps that
    row to ``BackendUnavailableError`` (behaviour 19); the mapping
    table itself is not re-tested here — only that ``logs`` routes
    the lookup's non-``NotFound`` failures through it, with the raw
    error chained as ``__cause__``.

    Arrange: a stub whose ``get`` records the call then raises the
    connection error.
    Act: ``backend.logs(handle, follow=False, tail=5)``, expected
    to raise.
    Assert: ``BackendUnavailableError`` — not ``ContainerNotFound-
    Error``, not a ``DockerException`` — with the raw error as
    ``__cause__``; the lookup happened once.
    """
    error = _daemon_unreachable()
    stub = _RecordingClient(container=None, get_error=error)
    backend = _backend_with(stub)

    with pytest.raises(BackendUnavailableError) as excinfo:
        backend.logs(_handle(), follow=False, tail=5)
    raised = excinfo.value
    assert not isinstance(raised, docker.errors.DockerException)
    assert raised.__cause__ is error
    assert stub.containers.get_calls == [_RecordedGet(container_id=_CONTAINER_ID)]


# ---------------------------------------------------------------------------
# Behaviour 26 — the not-found contract, paired with FakeBackend
# ---------------------------------------------------------------------------


def test_logs_missing_container_contract_matches_fake_backend_both_raise() -> None:
    """Both backends must agree that ``logs`` on a missing container
    raises — the one place in the slice where parity means *both
    raise*.

    Behaviours 22-25's parity tests pin the §4.3 *lenient* side:
    ``is_running`` returns ``False``, ``inspect`` returns ``GONE``,
    ``stop`` and ``list_managed`` absorb the absence, and both
    backends agree on the no-error shape.  ``logs`` is the
    complement: §4.3 names the three lenient methods and says
    "every other method raises", and ``FakeBackend.logs`` already
    raises ``ContainerNotFoundError`` for an unmanaged handle
    (behaviour 13).  A copy-paste of the previous no-op parity test
    would assert the *wrong* contract here — "both stay silent" is
    the exact behaviour §4.3 forbids for ``logs`` — so this test
    demands that both backends raise the same taxonomy member for
    the same input: asking for the log of a container that is not
    there is a caller error, answered, not absorbed.

    The fake half drives a handle the fake never managed; the
    docker half drives a handle the daemon reports missing (the
    SDK's own ``NotFound`` from ``get``).  Different mechanisms,
    one contract: both raise ``ContainerNotFoundError``.
    """
    unknown = ContainerHandle(
        id="ghost-id", name="ms-ghost", tool="ghost", image="example/tool:1.0"
    )
    fake = FakeBackend()
    stub = _RecordingClient(container=None, get_error=_vanished_container_404())
    backend = _backend_with(stub)

    with pytest.raises(ContainerNotFoundError):
        fake.logs(unknown, follow=False, tail=5)
    with pytest.raises(ContainerNotFoundError):
        backend.logs(unknown, follow=False, tail=5)


# ---------------------------------------------------------------------------
# The deferred completeness pin (behaviour 21's debt)
# ---------------------------------------------------------------------------


def test_docker_backend_satisfies_the_container_backend_protocol() -> None:
    """``DockerBackend`` passes the protocol's ``isinstance`` check.

    The pin deferred from behaviour 21's correction:
    ``@runtime_checkable`` ``isinstance`` matches on member *names*
    and requires **every** one of the six to be present, so with
    five of the six methods shipped it could only fail — and a
    failing protocol check is not a red step for ``start``, it is a
    fact about the class being incomplete.  The pin moved to
    behaviour 26's red step, where the last member arrives: this is
    the moment the class actually satisfies the seam's protocol,
    and it is worth pinning on the class itself rather than on a
    stub, because a stub carrying six names would pass the check
    while the real class still carried five.

    ``runtime_checkable`` checks member *names*, not signatures —
    the signature pins are behaviour 8's, at the protocol — so this
    asserts the presence, and the named ``logs`` behaviour tests
    above assert what the member does.

    **``build``'s absence is deliberately not asserted here.**
    Behaviour 8 already pins the protocol's exact member set,
    ``build`` included in its absence (``test_container_backend_
    does_not_declare_build``), and §7 item 2 records the deferral
    to M5.  A second copy of the pin against the implementation
    would be a test M5 must *delete* when ``build`` legitimately
    lands, not a guard the seam keeps — the protocol is the seam's
    contract, and its member set is pinned once, at the protocol.

    Arrange: a backend on an empty-log stub — the check is on the
    class's shape, not on any call.
    Act: ``isinstance(backend, ContainerBackend)``.
    Assert: ``True`` — all six protocol members present.
    """
    stub = _RecordingClient(container=_LoggingContainer(b""))
    backend = _backend_with(stub)

    assert isinstance(backend, ContainerBackend) is True
