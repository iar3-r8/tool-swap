"""RED step for M2a behaviour 9 — the backend error taxonomy.

See ``plans/m2a-container-backend-seam.md`` §4.3 and behaviour 9: a new
module, ``src/tool_swap/backend/errors.py``, holds the seven exception
classes the container backend seam raises — the six failure classes
plus the base, which doubles as the fallback for an unrecognised SDK
exception.  Every member carries a human ``message`` and an actionable
``remedy`` so ``plan/01_ARCHITECTURE.md`` §11's "error string surfaced
in /status" is real rather than aspirational: M2b's ``FAILED`` state
carries a reason which *is* the taxonomy member's message — "M2b
formats it, it does not invent it" (plan §6 item 6).  An error whose
remedy is empty or unhelpful is a user staring at a dead tool with no
next step, which is why behaviour 9 verifies that every concrete
subclass produces a non-empty remedy.

**The constructor signature — pinned here, the ambiguity resolved in
the RED report.**  The plan names the classes and what each remedy
names, but not the constructor, and behaviour 9's two halves pull in
different directions: "Inputs: construction with a message and a
remedy" reads as the caller supplying both, while "an error
constructed with no remedy must still render usefully" and "every
concrete subclass produces a non-empty remedy" read as a remedy
existing without caller input.  Both are satisfied by one signature,
identical on all seven classes:

    def __init__(self, message: str, *, remedy: str | None = None)
        -> None: ...

- ``message`` is required (positional or keyword): the human
  statement of what went wrong — the value M2b's ``FAILED`` reason
  carries.
- ``remedy`` is **keyword-only** and optional: the two parameters are
  interchangeable strings, so keyword-only makes each call
  self-documenting (behaviour 6's rationale for its optional
  keywords).  The name matches the ``remedy=`` keyword convention of
  the config layer (``Diagnostic.remedy``, ``Rule.remedy``).
- When omitted, the class's own per-class default remedy is used:
  §4.3's remedy column is per-class (each row names something
  specific to that failure), so the default lives on the class.  When
  supplied, it replaces the default — that is how behaviours 19 and
  21's ``map_sdk_error`` passes the per-value context the class
  cannot know (the image ref, the conflicting name, the underlying
  SDK error text) into the remedy.
- An explicitly empty or whitespace-only ``remedy`` raises
  ``ValueError``: the config layer already pins exactly this for
  ``Diagnostic`` and ``Rule``, and it turns "every concrete subclass
  produces a non-empty remedy" into a construction-level invariant
  rather than a property of the defaults alone.

Both halves come back as public attributes — ``exc.message`` and
``exc.remedy``, always ``str`` (an omitted remedy resolves to the
class's default, never ``None``) — and ``str(exc)`` includes **both**
the message and the effective remedy.  The ``/status`` consumer reads
the string, so the rendering is part of the contract; a construction
with no remedy therefore "renders usefully" because every class's
default remedy is non-empty, including the base's (its own row of
§4.3 names the underlying error text, and behaviour 19's fallback
constructs the base directly).

Hierarchy, per the behaviour's words read literally: ``BackendError``
derives from ``Exception``; the six named subclasses derive from
``BackendError`` (the base cannot derive from itself, so "all seven
derive from BackendError" is read as the base plus its six
subclasses).  Together the seven form the taxonomy: the module
exposes no public exception type outside them — the taxonomy is a
closed seam (it maps one-to-one onto the ``/status`` surface and
M2b's ``FAILED`` reason), so a later branch adding a member is a plan
change that must update this file's expected set.

No docker-SDK fact is asserted here: ``BackendError`` being the
fallback for an unrecognised SDK exception is *our* design (§4.3's
first row), but mapping docker's own exception classes is behaviour
19's job, to be pinned against saved documentation on a later
branch.

This file is the RED step: ``errors.py`` does not exist yet.  Every
access to ``tool_swap`` is deferred out of module scope into
call-time helpers via ``importlib.import_module`` (the precedent:
``test_managed_labels.py``): a module-level import would raise
``ModuleNotFoundError`` at *collection* time and abort the whole
suite, whereas each gate instead raises ``AssertionError`` naming the
missing module, so every test fails individually, and the moment the
GREEN step creates ``errors.py`` each test proceeds to its own
assertions.  No ``importorskip``, no skips — a skipped test is not a
red step.  Errors carry no mount strings, so behaviour 3's
mount-parsing guard (which walks the package and will also cover
``errors.py`` once it exists) cannot trip on this module.

Conventions: pytest, AAA pattern, Google-style docstrings, no
``warnings.warn`` (pyproject sets ``filterwarnings = "error"``).
"""

from __future__ import annotations

import importlib
import inspect
import typing
from types import ModuleType

import pytest

#: The base of the taxonomy; also the fallback for an unrecognised
#: SDK exception (§4.3).
BASE_NAME = "BackendError"

#: The six concrete subclasses of §4.3, in the plan's table order.
SUBCLASS_NAMES: tuple[str, ...] = (
    "BackendUnavailableError",
    "ImageNotFoundError",
    "ContainerNameConflictError",
    "ContainerStartError",
    "ContainerNotFoundError",
    "GpuUnavailableError",
)

#: The full taxonomy: the base plus its six subclasses.
TAXONOMY_NAMES: tuple[str, ...] = (BASE_NAME, *SUBCLASS_NAMES)

#: Distinctive fixture strings, so a containment assertion can fail
#: only on a real rendering defect, never on a generic ``str()``.
_MSG = "synthetic failure message"
_REMEDY = "synthetic actionable remedy"


# ---------------------------------------------------------------------------
# RED-safe access — the module does not exist until the GREEN step
# ---------------------------------------------------------------------------


def _get_errors_module() -> ModuleType:
    """Import ``tool_swap.backend.errors`` at call time, RED-safely.

    Deferred out of module scope so the not-yet-existing module cannot
    abort pytest *collection* of this file (and thereby of the whole
    suite), and so ``mypy --strict`` stays clean while no ``tool_swap``
    name is imported at module scope (the editable install carries no
    ``py.typed`` marker).

    Raises:
        AssertionError: ``tool_swap.backend.errors`` does not exist
            yet — the GREEN step must create it with the seven
            classes of §4.3.
    """
    try:
        return importlib.import_module("tool_swap.backend.errors")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tool_swap.backend.errors is missing — the GREEN step must "
            "create src/tool_swap/backend/errors.py with the seven "
            "classes of plan §4.3"
        ) from exc


def _get_error_class(class_name: str) -> type:
    """Resolve one taxonomy class by name, RED-safely.

    ``AttributeError`` is caught separately from the module-level
    failure handled by :func:`_get_errors_module`: a module that
    exists but lacks the name is a different RED failure mode and
    deserves its own message.  Returns a bare ``type`` (not
    ``type[Exception]``) because the pinned constructor takes a
    ``remedy=`` keyword that ``Exception.__init__`` does not, and the
    ``Exception``-subclass-ness is the runtime check below, not a
    typing-level one.

    Args:
        class_name: One of :data:`TAXONOMY_NAMES`.

    Raises:
        AssertionError: the class is missing, or the name does not
            resolve to an ``Exception`` subclass.
    """
    module = _get_errors_module()
    try:
        cls: object = getattr(module, class_name)
    except AttributeError as exc:
        raise AssertionError(
            f"tool_swap.backend.errors.{class_name} is missing — the "
            "GREEN step must add it"
        ) from exc
    if not isinstance(cls, type):
        raise AssertionError(
            f"tool_swap.backend.errors.{class_name} is not a class (got {cls!r})"
        )
    if not issubclass(cls, Exception):
        raise AssertionError(
            f"tool_swap.backend.errors.{class_name} is not an "
            f"Exception subclass (got {cls!r})"
        )
    return cls


def _instance_attr(exc: BaseException, attr: str) -> object:
    """Read a public attribute from a constructed taxonomy member.

    Read via ``getattr`` so this file stays clean under ``mypy
    --strict`` while ``errors.py`` does not exist yet; the ``message``
    and ``remedy`` attributes are the pinned API, and the GREEN step
    must store both on every member.

    Args:
        exc: The constructed error.
        attr: The attribute name, ``"message"`` or ``"remedy"``.

    Raises:
        AssertionError: the attribute is missing — the pinned API
            stores message and remedy as public attributes.
    """
    try:
        return getattr(exc, attr)
    except AttributeError as exc2:
        raise AssertionError(
            f"constructed {type(exc).__name__} has no {attr!r} "
            "attribute — the pinned API stores message and remedy "
            "as public attributes on every member"
        ) from exc2


def _transitive_subclasses(cls: type) -> list[type]:
    """All transitive subclasses of *cls*, deduplicated, DFS order.

    A member a later branch adds — directly under ``BackendError`` or
    under an intermediate base — is covered exactly like the six.
    """
    seen: set[type] = set()
    ordered: list[type] = []

    def _visit(node: type) -> None:
        for child in node.__subclasses__():
            if child in seen:
                continue
            seen.add(child)
            ordered.append(child)
            _visit(child)

    _visit(cls)
    return ordered


# ---------------------------------------------------------------------------
# Outputs — the hierarchy of §4.3
# ---------------------------------------------------------------------------


def test_backend_error_derives_from_exception() -> None:
    """The base derives from Exception: a real, catchable error."""
    # Arrange
    base = _get_error_class(BASE_NAME)
    # Act / Assert
    assert issubclass(base, Exception)
    assert base is not Exception


@pytest.mark.parametrize("class_name", SUBCLASS_NAMES)
def test_named_subclass_derives_from_backend_error(class_name: str) -> None:
    """Each of the six named subclasses derives from BackendError.

    A member deriving from ``Exception`` directly would escape the
    taxonomy's single catch point and its remedy invariant.
    """
    # Arrange
    base = _get_error_class(BASE_NAME)
    cls = _get_error_class(class_name)
    # Act / Assert
    assert issubclass(cls, base)
    assert cls is not base


def test_the_seven_form_a_closed_taxonomy() -> None:
    """The seven names are distinct classes; the module exposes no
    public exception type outside the seven.

    "The seven together form the taxonomy" read structurally: the
    taxonomy is a closed seam (it maps one-to-one onto the
    ``/status`` surface and M2b's ``FAILED`` reason), so a stray
    exception type in the module would be a member the plan's table
    never approved.
    """
    # Arrange
    module = _get_errors_module()
    resolved = [_get_error_class(name) for name in TAXONOMY_NAMES]
    public_exceptions = {
        value
        for name, value in vars(module).items()
        if not name.startswith("_")
        and isinstance(value, type)
        and issubclass(value, Exception)
    }
    # Assert — the seven names are all distinct
    assert len({id(cls) for cls in resolved}) == len(resolved)
    # Assert — nothing public outside the seven is an exception type
    assert public_exceptions == set(resolved)


# ---------------------------------------------------------------------------
# The pinned constructor signature
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("class_name", TAXONOMY_NAMES)
def test_init_signature_is_pinned(class_name: str) -> None:
    """Every class is exactly ``__init__(self, message, *, remedy=None)``.

    ``message`` is the required positional-or-keyword first parameter;
    ``remedy`` is keyword-only with a ``None`` default; the
    annotations are ``str`` and ``str | None`` respectively (the
    ``str | None`` style pins the branch convention, per behaviour
    6's precedent).
    """
    # Arrange
    cls = _get_error_class(class_name)
    # Act
    parameters = inspect.signature(cls).parameters
    # Sound in practice: every taxonomy class defines its own __init__
    # (the pinned API), so the hints belong to the class under test,
    # not to an unrelated subclass.
    hints = typing.get_type_hints(cls.__init__)  # type: ignore[misc]
    # Assert — names, order, kinds, defaults
    assert list(parameters) == ["message", "remedy"]
    assert parameters["message"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["message"].default is inspect.Parameter.empty
    assert parameters["remedy"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["remedy"].default is None
    # Assert — annotations
    assert hints["message"] is str
    assert hints["remedy"] == (str | None)


@pytest.mark.parametrize("class_name", TAXONOMY_NAMES)
def test_remedy_is_keyword_only(class_name: str) -> None:
    """Passing the remedy positionally is a TypeError.

    Behavioural side of the keyword-only pin: the two parameters are
    interchangeable strings, so a positional remedy is a silently
    swapped message — the call must be rejected, not reinterpreted.
    """
    # Arrange
    cls = _get_error_class(class_name)
    # Act / Assert
    with pytest.raises(TypeError):
        cls(_MSG, _REMEDY)


# ---------------------------------------------------------------------------
# Outputs — construction and rendering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("class_name", TAXONOMY_NAMES)
def test_construction_with_message_and_remedy_renders_both(
    class_name: str,
) -> None:
    """Construction takes both; both come back; both render.

    The caller's remedy wins over the class default — behaviours 19
    and 21's ``map_sdk_error`` passes the underlying SDK error text
    along, and that value must reach the rendered string, not be
    swallowed by a default.
    """
    # Arrange
    cls = _get_error_class(class_name)
    # Act
    exc = cls(_MSG, remedy=_REMEDY)
    rendered = str(exc)
    # Assert — public attributes
    assert _instance_attr(exc, "message") == _MSG
    assert _instance_attr(exc, "remedy") == _REMEDY
    # Assert — str(exc) includes BOTH message and remedy
    assert _MSG in rendered
    assert _REMEDY in rendered


@pytest.mark.parametrize("class_name", TAXONOMY_NAMES)
def test_omitted_remedy_falls_back_to_non_empty_class_default(
    class_name: str,
) -> None:
    """Edge case: a construction with no remedy still renders usefully.

    The omitted remedy resolves to the class's own default — non-empty
    on all seven, since §4.3 says *every member* carries an actionable
    remedy — and the rendering keeps both the message and that
    default, with ``remedy`` always a ``str``.
    """
    # Arrange
    cls = _get_error_class(class_name)
    # Act
    exc = cls(_MSG)
    rendered = str(exc)
    # Assert
    remedy = _instance_attr(exc, "remedy")
    assert isinstance(remedy, str), (
        f"{class_name}: the remedy attribute is not a str (got {type(remedy).__name__})"
    )
    assert remedy.strip(), (
        f"{class_name}: an omitted remedy must fall back to a per-class "
        "default remedy, not to the empty string"
    )
    assert rendered.strip()
    assert _MSG in rendered
    assert remedy in rendered


@pytest.mark.parametrize("class_name", TAXONOMY_NAMES)
def test_explicit_empty_remedy_raises_value_error(class_name: str) -> None:
    """An explicitly empty remedy is rejected, not stored.

    The config layer pins exactly this for ``Diagnostic`` and
    ``Rule``; a stored empty remedy would be the dead-tool-with-no-
    next-step failure this behaviour exists to prevent.
    """
    # Arrange
    cls = _get_error_class(class_name)
    # Act / Assert
    with pytest.raises(ValueError):
        cls(_MSG, remedy="")
    with pytest.raises(ValueError):
        cls(_MSG, remedy="   ")


# ---------------------------------------------------------------------------
# The growth-proofed remedy guarantee
# ---------------------------------------------------------------------------


def test_every_concrete_subclass_default_remedy_is_non_empty() -> None:
    """Every concrete subclass produces a non-empty remedy, even when
    the caller omits one — including a subclass a later branch adds.

    The load-bearing invariant of §4.3 (plan §6 item 6): M2b's
    ``FAILED`` reason is the member's message, and the remedy is the
    user's next step.  The walk is over ``BackendError.__subclasses__``
    transitively — directly under the base or under an intermediate
    base — so the guard tracks the taxonomy wherever it grows rather
    than hardcoding the six names known today; the same growth-
    proofing reasoning as behaviour 3's boundary guard and behaviour
    6's namespace guard.  The remedy is read from the *instance*
    built with the message only, so the invariant is pinned at
    construction time.
    """
    # Arrange
    base = _get_error_class(BASE_NAME)
    subclasses = _transitive_subclasses(base)
    # Assert — the walk is not vacuous: the six named members are in it
    names = [cls.__name__ for cls in subclasses]
    for expected in SUBCLASS_NAMES:
        assert expected in names, (
            f"{expected} is missing from the transitive walk of "
            f"BackendError.__subclasses__() — the walk saw {names}"
        )
    # Act / Assert — per class
    offenders: list[str] = []
    for cls in subclasses:
        exc = cls(_MSG)
        remedy = _instance_attr(exc, "remedy")
        if not (isinstance(remedy, str) and remedy.strip()):
            offenders.append(cls.__name__)
    # Assert
    assert not offenders, (
        f"Concrete BackendError subclass(es) with an empty remedy: "
        f"{offenders}. Every concrete subclass must carry a non-empty "
        "default remedy naming the actionable thing (plan §4.3) — "
        "M2b's FAILED reason and the /status error string depend on "
        "the remedy being the user's next step."
    )
