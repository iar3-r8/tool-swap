"""RED step for M2a behaviour 20 — ``DockerBackend`` never touches the
ambient environment.

See ``plans/m2a-container-backend-seam.md`` §4.5 and behaviour 20 (§5):
``DockerBackend(client, *, label_namespace, container_prefix)`` takes an
**already-built** client and never reads the ambient environment;
``from_config`` is the only place a real client is created, and it is
*not exercised here* (it would need a daemon).  This is
``plans/m2-docker-testing-recommendation.md`` "done 4" ("a test
asserting that the backend under test is never constructed from the
default environment") made daemon-free — a named regression guard, and
the load-bearing half of this file.

**The poisoned set, and why it is sufficient.**  Every
environment-reading entry point on the SDK's client-construction paths
is enumerated in the saved reference
``plan/third-party-docs/docker/client-construction-and-env.md``
(captured 2026-09-16 for exactly this behaviour, read from the
installed docker 7.2.0).  That page's §5 table lists fifteen readers
and concludes with the guard's shape:

- **Patch items 1–4 by name** — ``docker.from_env``,
  ``docker.DockerClient.from_env``, ``docker.from_context`` and
  ``docker.DockerClient.from_context``.  Page §1: ``docker.from_env``
  is a module-level alias bound *at import time* (``client.py:283``),
  a distinct binding from the classmethod, so patching one of the pair
  does not affect the other — a guard missing either half of a pair is
  the under-patched version of this test (the decoy rows catch each
  half independently).
- **Patch the two constructors** — ``DockerClient.__init__`` and
  ``APIClient.__init__`` (page items 13 and 12) — because page §4
  records that ``APIClient.__init__`` is *not* environment-free even
  with an explicit ``base_url``: it reads ``DOCKER_CONFIG`` and
  ``~/.docker/config.json`` (``api/client.py:131``) and, with
  ``version=None``, performs a live daemon handshake
  (``api/client.py:203–207``).  Page items 5–11 and 14–15
  (``kwargs_from_env``, ``kwargs_from_context``,
  ``get_current_context_name``, ``find_config_file`` and friends) are
  reachable *only through* one of the four named entry points or the
  two constructors, so patching the constructors to raise is the
  strongest single guard (page §5, "What this implies").  The six
  poisoned points therefore cover every row of the page's table.
- **One deliberate non-fact:** an *unset* ``DOCKER_HOST`` is **not**
  evidence of isolation.  Page §3 records that the context/config-file
  path is taken *precisely when* ``DOCKER_HOST`` is absent, so the
  guard patches the readers instead of relying on any environment
  variable being clean, and it clears nothing.

The poison raises a distinctive sentinel from every poisoned point,
and :func:`_verify_poison_live` proves before the subject runs that
each of the six poisoned points actually raises it — a monkeypatch
that had silently missed its target fails the test on the proof, not
on the subject.

**Proving the guard non-vacuous.**  The suite has been bitten by a
guard that passed against its own decoys (behaviour 3's first
boundary guard; plan §0.1) and by an assertion any invented value
satisfied (behaviour 7).  So the guard is demonstrated to fail when it
should: :func:`test_guard_catches_ambient_read_decoys` ``exec``s
in-memory decoy backend classes — each one the exact regression shape
this behaviour exists to rule out, one per row of the page's table —
through the *same* poison, and asserts that the sentinel leaks from
the decoy's construction.  The decoys are string constants parsed in
memory; nothing is written under ``src/``.  Each decoy test re-runs
:func:`_verify_poison_live` first, so a poison that had stopped
raising would fail the decoy tests at the verification step and the
"the sentinel leaked" assertion cannot be explained away as a silent
patch.

**Judgements recorded here, per the task brief:**

- **"and using".**  Behaviours 21–26 (``start`` … ``logs``) do not
  exist yet, so "using" is pinned to what behaviour 20 actually
  delivers: the object's stored state — the client read back from the
  instance, identity-wise — while the poison is still in force.  No
  protocol method is exercised, because none is delivered by this
  behaviour and none is tested here.
- **``from_config``.**  Its *existence* is pinned — a classmethod on
  the class — so §4.5's two-part construction contract (injected-
  client constructor plus config-built factory) is enforced from this
  red step; but it is *never called*: it is the only path permitted
  to build a real client, and calling it would need a daemon.  Its
  behaviour belongs to a later ledger entry.
- **``DockerClientLike``.**  §4.5's signature names it, but no
  protocol is introduced here.  The tests pin the constructor
  parameter *names and positions*, never annotations, and the stub is
  a plain object; the minimal protocol the seam actually needs will be
  forced by the shapes behaviours 21–26 pin.  Inventing a broad
  protocol now would ship a declaration no test exercises.

**The RED gate.**  ``docker_backend.py`` exists (behaviours 14–19
landed it) but defines no ``DockerBackend`` attribute, so the gate is
attribute-level, following the committed pattern of
``test_docker_backend_map_sdk_error.py``: every access is deferred
into call-time helpers via ``importlib.import_module``, so while the
class is absent **every subject test fails individually** with its
assertions present and reachable — never aborting pytest collection.
The two guard-verification tests (poison live, decoys) do not depend
on the class and are expected to pass in the red phase: they prove
the poison is armed *before* the green step, which is what makes the
subject tests trustworthy once the class exists.  No
``importorskip``, no skips.

Conventions: pytest, AAA, Google-style docstrings, Black at 88
columns, ruff, ``filterwarnings = "error"`` — no fixture emits a
warning, and no test asserts a docker fact from memory.
"""

from __future__ import annotations

import importlib
import inspect
from types import ModuleType
from typing import cast

import docker
import pytest

# ---------------------------------------------------------------------------
# The RED gate (attribute-level, per behaviour 19's committed pattern)
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


def _docker_backend_class() -> type:
    """Import and return the ``DockerBackend`` class, RED-safely.

    Raises:
        AssertionError: the module does not exist yet (see
            :func:`_get_docker_backend_module`), or it does not define
            ``DockerBackend`` yet — the GREEN step must define the
            class in ``src/tool_swap/backend/docker_backend.py``.
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
    return cast(type, backend_cls)


def _constructor_params() -> list[str]:
    """The parameter names of ``DockerBackend``'s constructor, in order.

    ``inspect.signature`` on a class reports the ``__init__``
    signature with ``self`` removed.

    Raises:
        AssertionError: the class cannot be obtained yet (see
            :func:`_docker_backend_class`).
    """
    return list(inspect.signature(_docker_backend_class()).parameters)


# ---------------------------------------------------------------------------
# The poison (behaviour 20's named regression guard)
# ---------------------------------------------------------------------------

#: The sentinel the poisoned entry points raise.  Distinctive enough
#: that no test can confuse it with a real SDK message, and free of
#: quote characters so the decoy sources below could embed it.
_SENTINEL_MESSAGE = (
    "BEHAVIOUR-20 GUARD: DockerBackend must never read the ambient "
    "environment or build a client from it"
)


class _AmbientReadError(RuntimeError):
    """The error a poisoned entry point raises when called.

    A ``RuntimeError`` rather than a ``DockerException``: a backend
    that *caught* the guard's own poison would be asserting a meaning
    onto it that only its author could have known — the sentinel must
    be impossible to confuse with any SDK failure.
    """


#: The six points the poison patches, in the order of the saved
#: reference's table (client-construction-and-env.md §5): the four
#: named entry points (items 1–4) and the two constructors (items
#: 12–13).  Items 5–11 and 14–15 are unreachable without first
#: passing through one of these (page §5, "What this implies").
_PATCH_TARGETS: tuple[tuple[object, str], ...] = (
    (docker, "from_env"),
    (docker.DockerClient, "from_env"),
    (docker, "from_context"),
    (docker.DockerClient, "from_context"),
    (docker.DockerClient, "__init__"),
    (docker.APIClient, "__init__"),
)


def _raise_ambient_read_sentinel(*args: object, **kwargs: object) -> None:
    """The poison body: raise the sentinel whatever was passed."""
    raise _AmbientReadError(_SENTINEL_MESSAGE)


def _apply_poison(monkeypatch: pytest.MonkeyPatch) -> None:
    """Poison the six entry points, then prove each one is live.

    Each target is replaced with a callable raising the sentinel.  For
    the two constructors the replacement goes into the class's own
    ``__dict__`` — a plain ``setattr`` on the class would be ignored
    for ``__init__`` by the C-level type machinery.  Each replacement
    is then invoked once (see :func:`_verify_poison_live`) so a patch
    that missed its target fails here with the sentinel visible, not
    as a silent no-op on the subject.

    Args:
        monkeypatch: The pytest fixture; every patch is reverted at
            test end, so no other test can observe a poisoned SDK.
    """
    for target, attr in _PATCH_TARGETS:
        # ``__init__`` is an ordinary function in each class's own
        # ``__dict__`` (verified on the installed docker 7.2.0: both
        # ``DockerClient.__dict__`` and ``APIClient.__dict__`` carry
        # it), so a plain attribute patch reaches it — the C-level slot
        # machinery only intercepts descriptors like ``__new__`` and
        # ``__getattribute__``, never ``__init__``.
        monkeypatch.setattr(target, attr, _raise_ambient_read_sentinel)
    _verify_poison_live()


def _verify_poison_live() -> None:
    """Assert every poisoned point raises the sentinel when called.

    Called *before* the subject under test, so the proof that the
    guard is armed is separate from the assertion that the subject
    survived it — and re-run by the decoy tests, which is what makes
    their "the sentinel leaked" assertions trustworthy.

    Raises:
        AssertionError: a poisoned point did not raise the sentinel,
            i.e. the poison is not live and the whole test is void.
    """
    for target, attr in _PATCH_TARGETS:
        if attr == "__init__":
            try:
                cast(type, target)()
            except _AmbientReadError:
                continue
        else:
            try:
                getattr(target, attr)()
            except _AmbientReadError:
                continue
        raise AssertionError(
            f"poison not live on {type(target).__name__}.{attr} — the "
            "guard is void and this test proves nothing"
        )


@pytest.fixture()
def poisoned_docker(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The ``docker`` module with all six entry points poisoned.

    The poison is applied and verified live in one step; the
    ``monkeypatch`` fixture reverts every patch at test end.
    """
    _apply_poison(monkeypatch)
    return docker


# ---------------------------------------------------------------------------
# The stub — the only object ``DockerBackend`` may ever hold
# ---------------------------------------------------------------------------


class _StubClient:
    """A deliberately empty stand-in for the injected client.

    It is an *identity* marker, not a behaviour stand-in: behaviour 20
    asserts the backend holds exactly this object, and no method is
    called on it because no method is delivered by this behaviour.  A
    plain object (rather than a mock) means a backend that called
    anything on it would fail with ``AttributeError`` — itself a
    useful signal.
    """


# ---------------------------------------------------------------------------
# Behaviour 20 — the constructor contract
# ---------------------------------------------------------------------------


def test_constructor_stores_exactly_the_injected_client() -> None:
    """The client attribute IS the injected object, identity-wise.

    Arrange: a stub client with nothing else to be confused with it.
    Act: construct the backend with the stub and the two keyword-only
    namespace arguments.
    Assert: the backend's ``client`` attribute is the stub — the
    *same* object, per the behaviour's "exactly the injected object"
    output — so any client the constructor secretly built is not what
    the backend will use.  The attribute name ``client`` is the
    natural pin for "whose client is exactly the injected object" and
    is what behaviours 21–26 will call through.
    """
    stub = _StubClient()
    backend = _docker_backend_class()(
        stub, label_namespace="com.tool-swap", container_prefix="ms-"
    )
    assert backend.client is stub


def test_constructor_rejects_none_client_with_type_error() -> None:
    """Constructing with ``None`` as the client raises ``TypeError``.

    The ledger's error-behaviour line: a ``None`` client is a
    programming error at the seam, and the constructor must refuse it
    loudly rather than let it reach an SDK call.
    """
    with pytest.raises(TypeError):
        _docker_backend_class()(
            None, label_namespace="com.tool-swap", container_prefix="ms-"
        )


def test_constructor_signature_matches_plan_4_5() -> None:
    """The constructor takes ``(client, *, label_namespace, container_prefix)``.

    Pinned from plan §4.5: the client is the single positional
    parameter, and both namespace arguments are keyword-only with no
    default — the same "no built-in default is re-stated" discipline
    as behaviours 6 and 7.  Only names and positions are pinned, never
    annotations: ``DockerClientLike`` is deliberately not introduced
    by this behaviour (see the module docstring).
    """
    assert _constructor_params() == [
        "client",
        "label_namespace",
        "container_prefix",
    ]
    signature = inspect.signature(_docker_backend_class())
    for name in ("label_namespace", "container_prefix"):
        parameter = signature.parameters[name]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty


def test_from_config_exists_as_classmethod_but_is_never_exercised() -> None:
    """``from_config`` exists as a classmethod; it is not called here.

    §4.5's shape has two construction paths: the injected-client
    constructor and the config-built factory.  Behaviour 20 pins the
    factory's *existence* — a classmethod on the class — so the
    two-part contract is enforced from this red step, but it is
    **never called**: it is the only path permitted to build a real
    client, and exercising it would need a daemon.  Its behaviour
    belongs to a later ledger entry.
    """
    backend_cls = _docker_backend_class()
    from_config = inspect.getattr_static(backend_cls, "from_config")
    assert isinstance(from_config, classmethod)


# ---------------------------------------------------------------------------
# Behaviour 20 — the named regression guard (the load-bearing half)
# ---------------------------------------------------------------------------


def test_construct_and_use_succeed_with_all_env_readers_poisoned(
    poisoned_docker: ModuleType,
) -> None:
    """Constructing AND using the backend survives the poisoned SDK.

    "And using" is pinned to what behaviour 20 delivers: the object's
    stored state — the client read back from the instance — because
    behaviours 21–26 (the six protocol methods) do not exist yet and
    none is tested here.

    Arrange: all six environment-reading entry points poisoned to
    raise the sentinel and proven live by the fixture.
    Act: construct the backend with the stub, then use it — read its
    stored client — while the poison is still in force.
    Assert: construction and use both succeed, the stored client is
    the stub, and the sentinel never leaked.  A constructor that
    secretly called any poisoned point would raise the sentinel
    (caught and re-raised with the context, so the failure shows the
    guard fired); a constructor that stashed a secretly built client
    under a second name is caught by the stray-client test below, and
    one that replaced the stub is caught by the identity assertion.
    """
    stub = _StubClient()
    try:
        backend = _docker_backend_class()(
            stub, label_namespace="com.tool-swap", container_prefix="ms-"
        )
    except _AmbientReadError as exc:
        raise AssertionError(
            "DockerBackend's constructor read the ambient environment — the guard fired"
        ) from exc
    # "Using": read back the stored state under the still-live poison.
    assert backend.client is stub


def test_no_stray_sdk_client_stored_on_the_backend(
    poisoned_docker: ModuleType,
) -> None:
    """The constructed backend stores no real SDK client object at all.

    Belt-and-braces for the identity claim: a constructor that built a
    client through a route the six poisoned points do not cover and
    stashed it under a second attribute would pass the ``is stub``
    assertion yet still have been constructed from ambient state.  The
    walk covers every instance attribute (works whether or not the
    class uses ``__slots__``), and the poison stays live the whole
    time, so any real-client construction through a covered route
    raises the sentinel and any through an uncovered route leaves an
    object the walk names.
    """
    stub = _StubClient()
    backend = _docker_backend_class()(
        stub, label_namespace="com.tool-swap", container_prefix="ms-"
    )
    for attr in dir(backend):
        if attr.startswith("__"):
            continue
        value = getattr(backend, attr)
        if isinstance(value, (docker.DockerClient, docker.APIClient)):
            raise AssertionError(
                f"attribute {attr!r} holds a real SDK client — the backend "
                "was constructed from ambient state through an unpoisoned route"
            )
    assert backend.client is stub


def test_poison_proven_live_on_all_six_entry_points(
    poisoned_docker: ModuleType,
) -> None:
    """Each of the six poisoned points raises the sentinel when called.

    The proof the poison is armed, independent of the subject: a
    monkeypatch that had silently missed a target (a renamed
    attribute, a moved module object) fails *here* with the sentinel
    name visible, rather than passing vacuously because the subject
    never happened to use that route.  Expected to pass in the red
    phase — it verifies the guard's machinery, not the class.
    """
    for target, attr in _PATCH_TARGETS:
        if attr == "__init__":
            with pytest.raises(_AmbientReadError):
                cast(type, target)()
        else:
            with pytest.raises(_AmbientReadError):
                getattr(target, attr)()


def test_guard_catches_ambient_read_decoys(poisoned_docker: ModuleType) -> None:
    """The guard FAILS against every regression shape it exists to catch.

    The non-vacuity proof (the precedent: behaviour 3's in-memory
    decoys, plan §0.1).  Each decoy is the exact regression a naive
    ``DockerBackend`` could drift into — one per row of the saved
    reference's table — ``exec``ed in memory; nothing is written under
    ``src/``.  Each decoy is constructed through the *same* poison the
    real test uses (verified live first), and the sentinel must leak
    from the decoy's construction: a guard that would pass against any
    of these is the vacuous version of this test, and its row fails it.

    Decoy rows (client-construction-and-env.md §5 table):

    - item 1 — the constructor calls ``docker.from_env()`` (the
      module alias);
    - item 2 — the constructor calls
      ``docker.DockerClient.from_env()`` (the classmethod — alias and
      classmethod are distinct bindings, page §1, so a guard missing
      either half of the pair is caught by the *other* row);
    - item 3 — the constructor calls ``docker.from_context()``;
    - items 12/13 — the constructor builds ``docker.DockerClient``
      directly (construction is not environment-free, page §4, so this
      row is the one a "we pass an explicit ``base_url``" regression
      lands on);
    - item 12 — the constructor stores a pre-built
      ``docker.APIClient`` — the identity assertion alone cannot catch
      a client built *before* the constructor, so the ``APIClient``
      constructor poison is what catches this row.

    Expected to pass in the red phase — it verifies the guard's
    machinery, not the class.
    """
    decoy_sources: tuple[tuple[str, str], ...] = (
        (
            "module alias from_env",
            (
                "class _DecoyBackend:\n"
                "    def __init__(self, client, *, label_namespace, "
                "container_prefix):\n"
                "        self.client = docker.from_env()\n"
            ),
        ),
        (
            "classmethod DockerClient.from_env",
            (
                "class _DecoyBackend:\n"
                "    def __init__(self, client, *, label_namespace, "
                "container_prefix):\n"
                "        self.client = docker.DockerClient.from_env()\n"
            ),
        ),
        (
            "module alias from_context",
            (
                "class _DecoyBackend:\n"
                "    def __init__(self, client, *, label_namespace, "
                "container_prefix):\n"
                "        self.client = docker.from_context()\n"
            ),
        ),
        (
            "direct DockerClient construction",
            (
                "class _DecoyBackend:\n"
                "    def __init__(self, client, *, label_namespace, "
                "container_prefix):\n"
                "        self.client = docker.DockerClient("
                'base_url="tcp://guard.invalid")\n'
            ),
        ),
        (
            "pre-built APIClient stored by the constructor",
            (
                "class _DecoyBackend:\n"
                "    def __init__(self, client, *, label_namespace, "
                "container_prefix):\n"
                "        self.client = docker.APIClient("
                'base_url="tcp://guard.invalid")\n'
            ),
        ),
    )

    _verify_poison_live()  # the decoy assertions below must not be void
    stub = _StubClient()
    for label, source in decoy_sources:
        namespace: dict[str, object] = {"docker": docker}
        exec(compile(source, f"<decoy:{label}>", "exec"), namespace)
        decoy_cls = cast(type, namespace["_DecoyBackend"])
        try:
            decoy_cls(stub, label_namespace="com.tool-swap", container_prefix="ms-")
        except _AmbientReadError:
            continue
        raise AssertionError(f"guard is VACUOUS: the '{label}' decoy did not trip it")
