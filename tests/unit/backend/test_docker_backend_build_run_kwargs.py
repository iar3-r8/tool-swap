"""RED step for M2a behaviour 14 — ``build_run_kwargs`` core translation.

See ``plans/m2a-container-backend-seam.md`` §5 behaviour 14 (amended)
and §0.1.2 pull request A: ``build_run_kwargs(spec, *, label_namespace)``
is a pure translation of a :class:`ContainerSpec` into the kwargs dict
that ``DockerBackend.start`` (behaviour 21) will pass to
``client.containers.create(**kwargs)``.  No client, no daemon, no
``DockerBackend`` class in this file.

Every kwarg name asserted here is cited from the saved docker-py
reference ``plan/third-party-docs/docker/containers-run-create.md``
(captured and re-verified against the installed docker 7.2.0), per the
blocking discipline of plan §3 — an invented kwarg name produces a
passing test, a matching shim and a broken integration with a green
suite.  docker-py raises ``TypeError`` for any kwarg it does not know
(that page, §1 "Client-side guards" and routing step 6), so a wrong
name fails fast at the SDK layer, not at the daemon.

Deliberately out of scope (later ledger behaviours, each with its own
red/green cycle): mounts (15), GPU device requests (16), resource
limits (17), port publication (18), ``map_sdk_error`` (19) and the
``DockerBackend`` class itself (20+).  The spec therefore carries the
structural defaults for the fields those behaviours own (``command``
``None``, ``mounts`` ``()``, ``devices`` ``()``, ``shm_size`` ``None``,
``cpus`` ``None``, ``memory`` ``None``, ``published_port`` ``None``),
and the snapshot test pins that none of those keys appears in the
output yet.  The two required-and-keyword-only spec fields
(``gpu_runtime``, ``container_port``) are supplied with neutral values
deliberately distinct from ``BUILT_IN_DEFAULTS``.

The contract pinned here, as confirmed before this red step:

- ``build_run_kwargs(spec, *, label_namespace)`` — ``label_namespace``
  is keyword-only and required (no default; defaulting is the config
  layer's job), matching the ``DockerBackend`` constructor style of
  plan §4.5.
- Empty ``spec.env`` **omits** the ``environment`` key; non-empty env
  is carried verbatim.
- ``spec.labels`` merge into the full ``managed_labels`` set;
  collision precedence is deliberately not pinned (this file uses
  non-colliding keys only).

This file is the RED step: ``src/tool_swap/backend/docker_backend.py``
does not exist yet.  A module-scope import of it would abort pytest
*collection* of the whole suite — the exact failure that got
behaviour 3's first red step rejected — so the import is deferred out
of module scope into :func:`_build_run_kwargs`, following the
committed pattern in ``test_fake_backend_happy_path.py``: while the
module is absent every test fails *individually* at the gate, with its
assertions present and reachable; the moment the GREEN step creates
the module each test proceeds to its own assertions.  No
``importorskip`` and no skip of any kind is used — a skipped test is
not a red step, it is a test that silently does not run.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from types import ModuleType
from typing import Any, cast

import pytest

from tool_swap.backend.base import ContainerSpec
from tool_swap.backend.labels import managed_labels

# Neutral label namespace, deliberately distinct from
# BUILT_IN_DEFAULTS["label_namespace"] — this file must not restate a
# configured default.
_NAMESPACE = "com.acme"


def _get_docker_backend_module() -> ModuleType:
    """Import ``tool_swap.backend.docker_backend`` at call time, RED-safely.

    The import is deferred out of module scope — via
    ``importlib.import_module`` so that the not-yet-existing
    ``tool_swap.backend.docker_backend`` module cannot abort pytest
    collection of this file (and thereby of the whole suite).  While
    the module is absent this raises ``AssertionError`` naming the
    missing module, so every test fails individually instead of the
    run being interrupted during collection.

    Raises:
        AssertionError: ``tool_swap.backend.docker_backend`` does not
            exist yet — the GREEN step must create
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


def _build_run_kwargs() -> Callable[..., dict[str, Any]]:
    """Import and return the ``build_run_kwargs`` function, RED-safely.

    Raises:
        AssertionError: the module does not exist yet (see
            :func:`_get_docker_backend_module`), or it does not define
            ``build_run_kwargs`` yet — the GREEN step must define it as
            a module-level function.
    """
    module = _get_docker_backend_module()
    try:
        fn = module.build_run_kwargs
    except AttributeError as exc:
        raise AssertionError(
            "tool_swap.backend.docker_backend.build_run_kwargs is missing — "
            "the GREEN step must define build_run_kwargs in "
            "src/tool_swap/backend/docker_backend.py"
        ) from exc
    return cast("Callable[..., dict[str, Any]]", fn)


def _spec(**overrides: Any) -> ContainerSpec:
    """A minimal behaviour-14 spec with neutral, non-default values.

    Values are deliberately distinct from ``BUILT_IN_DEFAULTS``:
    behaviour 14 is about the translation, not any configured default.
    ``gpu_runtime`` and ``container_port`` are keyword-only required
    fields of :class:`ContainerSpec`, so they must be supplied even
    though they belong to later behaviours.
    """
    defaults: dict[str, Any] = dict(
        tool="llama",
        name="ms-llama",
        image="example/tool:1.0",
        gpu_runtime="cuda",
        container_port=8080,
        env={"FOO": "bar"},
        labels={"app": "test-tool"},
        network="llm-network",
    )
    defaults.update(overrides)
    return ContainerSpec(**defaults)


def test_build_run_kwargs_is_module_level_function() -> None:
    """Behaviour 14: a pure function, no client, no daemon.

    The function lives at module level in
    ``tool_swap.backend.docker_backend`` rather than as a method of a
    class that carries a client — that is what makes it table-testable
    with no stub (plan §5 behaviour 14, "Verified").
    """
    # Act
    fn = _build_run_kwargs()
    # Assert
    assert inspect.isfunction(fn)


def test_build_run_kwargs_signature_pins_spec_and_keyword_only_namespace() -> None:
    """The confirmed contract: ``build_run_kwargs(spec, *, label_namespace)``.

    ``label_namespace`` is keyword-only and required — no default,
    since defaulting is the config layer's job (``BUILT_IN_DEFAULTS`` /
    ``BackendConfig.label_namespace``), matching the ``DockerBackend``
    constructor style of plan §4.5.  ``ContainerSpec`` itself carries
    no namespace field, so the caller must supply it.
    """
    # Arrange
    fn = _build_run_kwargs()
    # Act
    params = inspect.signature(fn).parameters
    # Assert
    assert list(params) == ["spec", "label_namespace"]
    assert params["label_namespace"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["label_namespace"].default is inspect.Parameter.empty


def test_build_run_kwargs_core_translation_snapshot() -> None:
    """The full snapshot: exactly the five keys, nothing more, nothing less.

    Kwarg names from
    ``plan/third-party-docs/docker/containers-run-create.md`` §2 and
    its routing table: ``image`` (``RUN_CREATE_KWARGS``, line 1041),
    ``name`` (line 1044), ``environment`` (line 1038) and ``labels``
    (line 1042) are the exact ``create``-accepted names, and
    ``network`` is the special-cased network kwarg (routing step 5).
    The ``labels`` value is derived by *calling* :func:`managed_labels`
    and merging the non-colliding spec labels, so this test cannot
    drift from ``labels.py`` in lockstep.  Exact-dict equality also
    pins the absence of ``detach`` and of every key owned by
    behaviours 15–18.
    """
    # Arrange
    spec = _spec()
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    expected = {
        "image": spec.image,
        "name": spec.name,
        "environment": dict(spec.env),
        "labels": {**managed_labels(_NAMESPACE, spec.tool), **dict(spec.labels)},
        "network": spec.network,
    }
    assert kwargs == expected


def test_build_run_kwargs_carries_image() -> None:
    """The image reference travels under the exact kwarg name ``image``.

    Cited from
    ``plan/third-party-docs/docker/containers-run-create.md`` §2
    (routing table: ``image`` is in ``RUN_CREATE_KWARGS``, line 1041,
    goes to create).  A typo'd name (e.g. an ``image`` alias) is a
    ``TypeError`` at the SDK layer, not at the daemon (same page, §1
    "Client-side guards").
    """
    # Arrange
    spec = _spec()
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert kwargs["image"] == spec.image


def test_build_run_kwargs_carries_name() -> None:
    """The container name travels under the exact kwarg name ``name``.

    Cited from
    ``plan/third-party-docs/docker/containers-run-create.md`` §2
    (routing table: ``name`` is in ``RUN_CREATE_KWARGS``, line 1044,
    goes to create).
    """
    # Arrange
    spec = _spec()
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert kwargs["name"] == spec.name


def test_build_run_kwargs_carries_environment() -> None:
    """Non-empty env travels verbatim under the exact kwarg
    ``environment``.

    Cited from
    ``plan/third-party-docs/docker/containers-run-create.md`` §2:
    ``environment`` is a ``dict`` (or list of ``"KEY=VALUE"`` strings)
    and the routing table places it in ``RUN_CREATE_KWARGS`` (line
    1038).  The spec's mapping form is the dict form, passed through
    unchanged.
    """
    # Arrange
    spec = _spec()
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert kwargs["environment"] == dict(spec.env)


def test_build_run_kwargs_labels_carry_full_managed_labels_set() -> None:
    """Every ``managed_labels`` entry is present, key and value.

    The label *values* are not third-party facts — they are this
    repository's own contract — so the expected set is derived by
    calling :func:`managed_labels` rather than restating the dict
    literally, and the two cannot drift apart.
    """
    # Arrange
    spec = _spec(labels={})
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    for key, value in managed_labels(_NAMESPACE, spec.tool).items():
        assert kwargs["labels"][key] == value


def test_build_run_kwargs_merges_non_colliding_spec_labels() -> None:
    """Non-colliding ``spec.labels`` merge into the managed set.

    Collision precedence is deliberately not pinned by behaviour 14,
    so this test uses a spec label whose key cannot collide with any
    ``managed_labels`` key.
    """
    # Arrange
    spec = _spec(labels={"app": "test-tool"})
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    expected = {**managed_labels(_NAMESPACE, spec.tool), **dict(spec.labels)}
    assert kwargs["labels"] == expected


def test_build_run_kwargs_empty_spec_labels_yield_exactly_managed_set() -> None:
    """Edge case: empty ``spec.labels`` adds nothing to the managed set.

    Exact equality against the :func:`managed_labels` call — no extra
    keys from an empty mapping, and no managed key lost.
    """
    # Arrange
    spec = _spec(labels={})
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert kwargs["labels"] == managed_labels(_NAMESPACE, spec.tool)


def test_build_run_kwargs_carries_network_not_network_mode() -> None:
    """Network travels under the exact kwarg ``network`` — and
    ``network_mode`` never appears in the output.

    Cited from
    ``plan/third-party-docs/docker/containers-run-create.md`` §2:
    ``network`` is a str — the network name at creation time — and the
    routing subsection, consequence 2: ``network`` is *not* a
    pass-through (it also sets ``network_mode`` internally, which is
    why passing both is rejected), so ``build_run_kwargs`` must emit
    ``network`` **or** ``network_mode``, never both.  The spec carries
    only ``network``, so the output is ``network`` alone.
    """
    # Arrange
    spec = _spec()
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert kwargs["network"] == spec.network
    assert "network_mode" not in kwargs


def test_build_run_kwargs_empty_env_omits_environment_key() -> None:
    """Edge case: empty ``spec.env`` omits the ``environment`` key.

    Confirmed contract for this red step.  The omission is *our*
    contract, not the SDK's: the routing table (step 1 of
    ``plan/third-party-docs/docker/containers-run-create.md``) shows
    ``environment`` is copied unconditionally from
    ``RUN_CREATE_KWARGS``, so ``environment={}`` and the omission both
    reach the API layer — the snapshot pinning the omission is the
    stricter assertion (the same reasoning the page applies to falsy
    ``ports``/``volumes``, consequence 1).
    """
    # Arrange
    spec = _spec(env={})
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert "environment" not in kwargs


def test_build_run_kwargs_network_none_omits_network_key() -> None:
    """Edge case: ``network=None`` omits the key rather than passing
    ``None``.

    Confirmed contract for this red step, and the omission is the
    stricter assertion: routing step 5 of
    ``plan/third-party-docs/docker/containers-run-create.md`` (and the
    installed source it cites) shows ``network`` is popped and guarded
    by ``if network:``, so ``network=None`` is equivalent to omission
    at the SDK layer — but equivalence at that layer is not a contract
    (consequence 1), and the snapshot pins the omission.
    """
    # Arrange
    spec = _spec(network=None)
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert "network" not in kwargs
    assert "network_mode" not in kwargs


def test_build_run_kwargs_output_has_no_detach_key() -> None:
    """The output carries no ``detach`` key — the start path is
    ``create`` + ``start``, not ``run(detach=True)``.

    Behaviour 14 (amended): the kwargs are destined for
    ``client.containers.create``, and ``run`` was rejected because it
    returns before any exit check and auto-pulls a missing image
    (``plan/third-party-docs/docker/containers-run-create.md`` §1
    "Which call for a detached start"; plan §5 behaviour 14).  Note
    the precision: the SDK does list ``detach`` in
    ``RUN_CREATE_KWARGS`` (same page, routing table, line 1035) — it
    is meaningful on the ``run`` return-value path — so this test pins
    *our* contract (absence), not a claim about what the SDK accepts.
    """
    # Arrange
    spec = _spec()
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert "detach" not in kwargs


def test_build_run_kwargs_empty_image_raises_value_error() -> None:
    """Error behaviour: an empty image raises plain ``ValueError``.

    Behaviour 14: a spec with an empty image fails *before any SDK
    call* — a programming error in the caller, so the error is a plain
    ``ValueError``, not a member of the seven-member taxonomy in
    ``tool_swap.backend.errors`` (those are backend failures, and a
    pure function makes no backend call at all).
    """
    # Arrange
    spec = _spec(image="")
    fn = _build_run_kwargs()
    # Act / Assert
    with pytest.raises(ValueError):
        fn(spec, label_namespace=_NAMESPACE)


def test_build_run_kwargs_is_pure_and_returns_fresh_dict() -> None:
    """Two calls on the same spec return equal dicts, not the same
    object.

    Behaviour 14: "pure function; no client, no daemon."  Freshness
    matters because behaviour 21 will ``**kwargs`` the returned dict
    into ``client.containers.create`` — a shared mutable dict mutated
    by one caller would leak into another.
    """
    # Arrange
    spec = _spec()
    fn = _build_run_kwargs()
    # Act
    first = fn(spec, label_namespace=_NAMESPACE)
    second = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert first == second
    assert first is not second
