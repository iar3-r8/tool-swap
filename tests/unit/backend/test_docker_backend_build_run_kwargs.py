"""RED step for M2a behaviour 14 (core translation), behaviour 15
(mounts), behaviour 16 (GPU device requests) and behaviour 17
(resource limits) — ``build_run_kwargs``.

See ``plans/m2a-container-backend-seam.md`` §5 behaviour 14 (amended),
behaviour 16 and §0.1.2 pull request A:
``build_run_kwargs(spec, *, label_namespace)``
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
red/green cycle): ``map_sdk_error`` (19) and the ``DockerBackend``
class itself (20+).  The snapshot test's spec keeps the structural
default for every field those tests own (``command`` ``None``), and
the snapshot pins that none of those keys appears in the output yet.
``published_port`` is no longer out of scope in this file: the
behaviour-18 tests below exercise it, and the snapshot test's spec
keeps ``published_port=None`` so its exact five-key equality is
unaffected.
``devices`` is no longer out of scope in this file: the behaviour-16
tests below exercise it, and the snapshot test's spec keeps
``devices=()`` so its exact five-key equality is unaffected.
``shm_size``, ``cpus`` and ``memory`` are no longer out of scope in
this file: the behaviour-17 tests below exercise them, and the
behaviour-14 snapshot test's spec keeps them ``None`` so its exact
five-key equality is unaffected.
``mounts`` is no longer out of scope in this file: the behaviour-15
tests below exercise it, and the snapshot test's spec keeps
``mounts=()`` so its exact five-key equality is unaffected.

Behaviour 15's mount representation decision, recorded here so the
tests cite it rather than restating it per test: the ``volumes`` dict
form is used, not ``list[docker.types.Mount]``.  Cited from
``plan/third-party-docs/docker/containers-run-create.md``: the
``volumes`` row of the §2 kwarg table (line 77) documents the exact
shape ``{host_path_or_volume_name: {"bind": container_path, "mode":
"rw"|"ro"}}``, and routing step 4 (line 116) shows ``volumes`` is
routed into the host config as ``binds``.  The ``Mount`` form was
rejected because its constructor arguments are captured in no saved
page (that directory's INDEX defers them), and plan §3 forbids
asserting a third-party interface from memory — an invented
``Mount(...)`` signature would produce a passing test, a matching shim
and a broken integration behind a green suite.

Behaviour 16's mechanism decision, likewise recorded once here rather
than restated per test: the GPU runtime is carried as
``DeviceRequest(driver=spec.gpu_runtime)``, *not* as the separate
host-config kwarg ``runtime``.  The saved page
``plan/third-party-docs/docker/containers-run-create.md``, routing
consequence 3, records that ``runtime`` is a host-config kwarg, that
the two are different mechanisms, and that behaviour 16 must pick one
deliberately.  The ``driver`` mechanism is chosen because the saved
page ``plan/third-party-docs/docker/gpu-device-requests.md`` §1
records the canonical GPU form for specific devices as
``DeviceRequest(driver='nvidia', device_ids=[...])`` (noted there as
inferred from the arguments) — the named indices and the named runtime
live in one request, which is exactly the behaviour-16 contract ("one
request naming exactly those indices and that runtime").  The legacy
``runtime`` host-config kwarg names a runtime and *no* indices, so it
cannot express that contract, and emitting both mechanisms would
double-select the GPU stack.

Behaviour 16's ``device_ids`` decision: ``ContainerSpec.devices`` is a
``tuple[int, ...]`` of GPU indices while ``DeviceRequest.device_ids``
is a list of *strings* (``plan/third-party-docs/docker/
gpu-device-requests.md`` §1 constructor table), so the translation
converts each index with ``str(index)`` preserving declaration order.
The ``count`` argument is never emitted: the docstring says "set
either ``count`` or ``device_ids``" and the SDK does not enforce that
client-side (same page, "Mutually exclusive / constraint"), so
emitting both would encode a request the daemon may reject and no
test here can catch.  The assertions compare the full five-key wire
dict (wire keys ``Driver``, ``Count``, ``DeviceIDs``,
``Capabilities``, ``Options``; defaults ``''``, ``0``, ``[]``,
``[]``, ``{}`` — same §1), so an implementation that forgets to emit
``count`` or ``device_ids`` because the constructor defaults fill
them fails here: the wire dict is what the daemon receives.
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

from docker.types import DeviceRequest
import pytest

from tool_swap.backend.base import ContainerSpec, MountSpec
from tool_swap.backend.labels import managed_labels
from tool_swap.config.defaults import BUILT_IN_DEFAULTS

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
    though they belong to later behaviours.  ``devices`` keeps the
    structural default ``()`` (CPU-only) so the behaviour-14 snapshot
    test's exact five-key equality is unaffected; the behaviour-16
    tests override it explicitly.
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
        devices=(),
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


# ---------------------------------------------------------------------------
# Behaviour 15 — ``build_run_kwargs``, mounts
# ---------------------------------------------------------------------------
#
# Representation decision (see module docstring): the ``volumes`` dict
# form, not ``list[docker.types.Mount]``.  Every third-party fact below
# is cited from the saved reference
# ``plan/third-party-docs/docker/containers-run-create.md``:
#   * the ``volumes`` row of the §2 kwarg table (line 77) documents the
#     exact shape ``{host_path_or_volume_name: {"bind": container_path,
#     "mode": "rw"|"ro"}}``;
#   * routing step 4 (line 116) shows ``volumes`` is routed into the
#     host config as ``binds`` — i.e. ``volumes`` is a valid
#     ``create`` kwarg, and a typo'd alternative would be a
#     ``TypeError`` at the SDK layer (routing step 6, same section);
#   * consequence 1 (line 148) records that ``volumes`` is dropped
#     when *falsy*, and states that "behaviours 15 and 18 should still
#     omit the key" — the omission is *our* contract, and the snapshot
#     pinning it is the stricter assertion.
# The falsy-drop is re-verified against the installed source
# ``.venv/lib/python3.11/site-packages/docker/models/containers.py``
# (``_create_container_args``, lines 1142–1144: ``volumes =
# kwargs.pop('volumes', {}); if volumes:``).


def test_build_run_kwargs_carries_mounts_in_declaration_order() -> None:
    """Mounts travel under the exact kwarg ``volumes``, in order.

    Behaviour 15: a spec whose ``mounts`` concatenate the global
    defaults then the tool's own must produce the mount entries *in
    declaration order*.  The ``volumes`` dict form is the documented
    shape ``{host_path_or_volume_name: {"bind": container_path,
    "mode": "rw"|"ro"}}`` (``plan/third-party-docs/docker/
    containers-run-create.md`` §2, line 77); dicts preserve insertion
    order, so pinning the key order pins the declaration order.
    """
    # Arrange: first two mounts are the global defaults, the last is
    # the tool's own — the concatenation order of plan/02 §5.
    spec = _spec(
        mounts=(
            MountSpec(source="/data/models", target="/models", read_only=True),
            MountSpec(source="/data/cache", target="/cache", read_only=False),
            MountSpec(source="/opt/tools/config", target="/etc/tool", read_only=True),
        )
    )
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert kwargs["volumes"] == {
        "/data/models": {"bind": "/models", "mode": "ro"},
        "/data/cache": {"bind": "/cache", "mode": "rw"},
        "/opt/tools/config": {"bind": "/etc/tool", "mode": "ro"},
    }
    assert list(kwargs["volumes"]) == [
        "/data/models",
        "/data/cache",
        "/opt/tools/config",
    ]


def test_build_run_kwargs_volumes_entry_carries_source_target_and_mode() -> None:
    """Each entry carries source, target and the read-only flag.

    The source is the dict key, the target lives under ``"bind"`` and
    the read-only flag under ``"mode"`` — the exact shape from
    ``plan/third-party-docs/docker/containers-run-create.md`` §2, line
    77 (``{host_path_or_volume_name: {"bind": container_path, "mode":
    "rw"|"ro"}}``).  A read-only :class:`MountSpec` maps to
    ``"mode": "ro"``.
    """
    # Arrange
    spec = _spec(
        mounts=(MountSpec(source="/srv/share", target="/share", read_only=True),)
    )
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert kwargs["volumes"]["/srv/share"] == {"bind": "/share", "mode": "ro"}


def test_build_run_kwargs_no_mounts_omits_volumes_key() -> None:
    """Edge case: no mounts omits the ``volumes`` key entirely.

    Behaviour 15: "no mounts omits the key entirely."  The omission is
    *our* contract, stricter than the SDK's falsy-drop
    (``plan/third-party-docs/docker/containers-run-create.md``
    consequence 1, line 148: "behaviours 15 and 18 should still omit
    the key"); ``volumes={}`` and the omission are equivalent at the
    SDK layer (installed source, ``containers.py`` lines 1142–1144)
    but the snapshot pins the omission.
    """
    # Arrange
    spec = _spec(mounts=())
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert "volumes" not in kwargs


def test_build_run_kwargs_duplicate_target_keeps_both_entries_in_order() -> None:
    """Edge case: the same target declared twice keeps both entries.

    Behaviour 15: de-duplication is config-validation's job, not the
    driver's — the pure translation must not collapse entries.  Both
    sources are distinct keys of the ``volumes`` dict, and their
    declaration order is preserved (insertion order of a dict, which
    the SDK then walks verbatim when it converts ``volumes`` to
    ``binds`` — ``plan/third-party-docs/docker/
    containers-run-create.md`` routing step 4, line 116).
    """
    # Arrange: two different host paths mounted at the same target.
    spec = _spec(
        mounts=(
            MountSpec(source="/data/a", target="/dup", read_only=True),
            MountSpec(source="/data/b", target="/dup", read_only=False),
        )
    )
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert kwargs["volumes"] == {
        "/data/a": {"bind": "/dup", "mode": "ro"},
        "/data/b": {"bind": "/dup", "mode": "rw"},
    }
    assert list(kwargs["volumes"]) == ["/data/a", "/data/b"]


def test_build_run_kwargs_read_write_mount_distinguished_from_read_only() -> None:
    """Edge case: a read-write mount is distinguishable from a
    read-only one.

    The ``read_only`` bool maps to ``"mode": "rw"`` versus
    ``"mode": "ro"`` — the only two modes the documented ``volumes``
    shape allows (``plan/third-party-docs/docker/
    containers-run-create.md`` §2, line 77: ``"mode": "rw"|"ro"``).
    The modes are asserted independently, so a translation that
    ignores ``read_only`` (emitting one mode for all) fails here.
    """
    # Arrange: the same source shape, opposite flags.
    spec = _spec(
        mounts=(
            MountSpec(source="/srv/ro", target="/ro", read_only=True),
            MountSpec(source="/srv/rw", target="/rw", read_only=False),
        )
    )
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert kwargs["volumes"]["/srv/ro"]["mode"] == "ro"
    assert kwargs["volumes"]["/srv/rw"]["mode"] == "rw"


# ---------------------------------------------------------------------------
# Behaviour 16 — ``build_run_kwargs``, GPU device requests
# ---------------------------------------------------------------------------
#
# Representation decision (see module docstring): one
# ``docker.types.DeviceRequest`` under the exact kwarg
# ``device_requests``, with ``driver=spec.gpu_runtime`` and
# ``device_ids`` = the spec's GPU indices as strings — *not* the
# legacy ``runtime`` host-config kwarg.  Every third-party fact below
# is cited from the saved reference
# ``plan/third-party-docs/docker/gpu-device-requests.md``:
#   * the constructor takes the keyword arguments ``driver`` /
#     ``count`` / ``device_ids`` / ``capabilities`` / ``options``
#     (§1, ``__init__`` at types/containers.py:187) with defaults
#     ``''`` / ``0`` / ``[]`` / ``[]`` / ``{}`` and wire keys
#     ``Driver`` / ``Count`` / ``DeviceIDs`` / ``Capabilities`` /
#     ``Options`` (lines 215–221);
#   * ``device_ids`` is a list of *strings* (§1 constructor table),
#     so the spec's ``tuple[int, ...]`` indices are converted with
#     ``str()``;
#   * ``device_requests`` is in ``RUN_HOST_CONFIG_KWARGS``
#     (``models/containers.py`` line 1079, §2), so ``create`` accepts
#     it as a *list* of ``DeviceRequest`` instances.
# The kwarg name itself is cited from
# ``plan/third-party-docs/docker/containers-run-create.md`` routing
# table (line 1079); a typo'd name is a ``TypeError`` at the SDK
# layer (same page, routing step 6).
#
# The SDK import is at module scope here, deliberately: the SDK is an
# installed dependency (behaviour 2), so it cannot abort collection,
# and keeping it out of the shared helpers (``_spec`` etc.) is what
# keeps them usable with no SDK present — behaviour 27 will make
# ``docker_backend`` the only ``tool_swap`` module allowed to import
# ``docker``.
#
# No ``capabilities`` is asserted: the cited canonical form for
# specific devices is ``DeviceRequest(driver='nvidia',
# device_ids=[...])`` with no capability list, and inventing one
# (e.g. ``[["gpu"]]``) from memory is exactly what plan §3 forbids.


def _device_request_wire(request: DeviceRequest) -> dict[str, object]:
    """The full wire dict a :class:`DeviceRequest` carries to the daemon.

    ``DeviceRequest`` subclasses ``dict``
    (``docker/types/base.py``, ``class DictType(dict)``) and its
    ``__init__`` (``docker/types/containers.py`` lines 215–221;
    ``plan/third-party-docs/docker/gpu-device-requests.md`` §1)
    stores exactly the five PascalCase wire keys.  Comparing the full
    wire dict — not just the fields under test — is what makes a
    translation that forgets to emit ``count`` or ``device_ids`` fail:
    the constructor defaults would silently fill them, and the wire
    dict is what the daemon receives.
    """
    return dict(request)


def test_build_run_kwargs_no_devices_omits_device_requests_key() -> None:
    """Edge case: ``devices=()`` produces **no key**, not an empty list.

    Behaviour 16: "an empty device request is not the same as none".
    The omission is *our* contract — ``device_requests`` is a plain
    ``RUN_HOST_CONFIG_KWARGS`` pass-through (``plan/third-party-docs/
    docker/containers-run-create.md`` routing table, line 1079), so
    the SDK would accept an empty list; pinning the absence is the
    stricter assertion.
    """
    # Arrange
    spec = _spec(devices=())
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert "device_requests" not in kwargs


def test_build_run_kwargs_single_device_names_index_and_runtime() -> None:
    """``devices=(0,)`` is one request naming exactly index 0 and the runtime.

    The request is a ``docker.types.DeviceRequest`` with
    ``driver=spec.gpu_runtime`` and ``device_ids=["0"]`` — the
    canonical GPU form for specific devices (``plan/
    third-party-docs/docker/gpu-device-requests.md`` §1:
    ``DeviceRequest(driver='nvidia', device_ids=[...])``).
    ``device_ids`` is a list of *strings* (same §1 constructor
    table), so the int index 0 travels as ``"0"``.  The wire dict is
    asserted in full: ``Count`` pinned at its default ``0`` enforces
    the "set either ``count`` or ``device_ids``" docstring constraint
    (same §1, "Mutually exclusive / constraint") — the SDK does not
    enforce it client-side, so a translation that also emits
    ``count=len(devices)`` sets both, which no daemon-free test could
    otherwise catch.
    """
    # Arrange
    spec = _spec(devices=(0,), gpu_runtime="nvidia")
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    requests = kwargs["device_requests"]
    assert len(requests) == 1
    (request,) = requests
    assert isinstance(request, DeviceRequest)
    assert _device_request_wire(request) == {
        "Driver": "nvidia",
        "Count": 0,
        "DeviceIDs": ["0"],
        "Capabilities": [],
        "Options": {},
    }


def test_build_run_kwargs_multiple_devices_is_one_request_naming_each_index() -> None:
    """``devices=(0, 1)`` is one request naming exactly indices 0 and 1.

    One request, not two: the behaviour-16 contract is "one request
    naming exactly those indices and that runtime".  ``device_ids``
    carries both indices in declaration order as strings (``plan/
    third-party-docs/docker/gpu-device-requests.md`` §1:
    ``device_ids`` is a list of strings); ``Driver`` is the spec's
    runtime, ``Count`` stays at its default ``0``.
    """
    # Arrange
    spec = _spec(devices=(0, 1), gpu_runtime="nvidia")
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    requests = kwargs["device_requests"]
    assert len(requests) == 1
    (request,) = requests
    assert isinstance(request, DeviceRequest)
    assert _device_request_wire(request) == {
        "Driver": "nvidia",
        "Count": 0,
        "DeviceIDs": ["0", "1"],
        "Capabilities": [],
        "Options": {},
    }


def test_build_run_kwargs_non_default_gpu_runtime_is_honoured() -> None:
    """Edge case: a non-default ``gpu_runtime`` is honoured, not dropped.

    ``"nvidia"`` is the built-in default
    (``src/tool_swap/config/defaults.py`` line 74); this spec uses a
    deliberately different value, and the request's ``Driver`` must
    carry it verbatim (``plan/third-party-docs/docker/
    gpu-device-requests.md`` §1: ``driver`` is the driver string, a
    plain ``str`` with no enumeration).
    """
    # Arrange
    spec = _spec(devices=(0,), gpu_runtime="rocm")
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    (request,) = kwargs["device_requests"]
    assert _device_request_wire(request)["Driver"] == "rocm"


def test_build_run_kwargs_duplicate_device_indices_collapse() -> None:
    """Edge case: duplicate indices collapse to a single entry.

    Behaviour 16: the request must name *exactly* those indices, and
    an index declared twice is not two devices — ``devices=(0, 0)``
    yields ``DeviceIDs == ["0"]`` (``plan/third-party-docs/docker/
    gpu-device-requests.md`` §1: ``device_ids`` is a list of
    strings).
    """
    # Arrange
    spec = _spec(devices=(0, 0), gpu_runtime="nvidia")
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    (request,) = kwargs["device_requests"]
    assert _device_request_wire(request)["DeviceIDs"] == ["0"]


def test_build_run_kwargs_device_requests_is_list_of_device_request_instances() -> None:
    """The kwarg is a *list* of ``DeviceRequest`` instances under the
    exact name ``device_requests``.

    ``device_requests`` is in ``RUN_HOST_CONFIG_KWARGS``
    (``models/containers.py`` line 1079; ``plan/third-party-docs/
    docker/gpu-device-requests.md`` §2), so ``create`` accepts a list
    of instances — a single bare instance, or a typo'd name (a
    ``TypeError`` at routing step 6 of
    ``plan/third-party-docs/docker/containers-run-create.md``), is a
    different call shape.
    """
    # Arrange
    spec = _spec(devices=(0,), gpu_runtime="nvidia")
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    requests = kwargs["device_requests"]
    assert isinstance(requests, list)
    assert all(isinstance(item, DeviceRequest) for item in requests)


def test_build_run_kwargs_negative_device_index_raises_value_error() -> None:
    """Error behaviour: a negative device index raises plain
    ``ValueError``.

    Behaviour 16: ``devices=(-1,)`` is a caller programming error,
    raised *before any SDK call* — so a plain ``ValueError``, not a
    member of the seven-member taxonomy in
    ``tool_swap.backend.errors`` (the same reasoning as behaviour 14's
    empty-image check: a pure function makes no backend call).  The
    validation precedes the ``str()`` conversion, so a negative index
    can never reach the wire as the string ``"-1"``.
    """
    # Arrange
    spec = _spec(devices=(-1,), gpu_runtime="nvidia")
    fn = _build_run_kwargs()
    # Act / Assert
    with pytest.raises(ValueError):
        fn(spec, label_namespace=_NAMESPACE)


# ---------------------------------------------------------------------------
# Behaviour 17 — ``build_run_kwargs``, resource limits
# ---------------------------------------------------------------------------
#
# The decisions this section pins, recorded once here rather than restated
# per test:
#
# 1. The CPU limit travels as ``nano_cpus`` — one kwarg, no ``cpu_period``.
#    The saved reference ``plan/third-party-docs/docker/
#    containers-run-create.md`` §2 (line 82) lists the mechanisms:
#    ``cpu_quota`` (int, "Microseconds of CPU time that the container can
#    get in a CPU period") paired with ``cpu_period`` (int, microseconds),
#    or ``nano_cpus`` — "CPU quota in units of 1e-9 CPUs" (installed
#    docstring ``.venv/lib/python3.11/site-packages/docker/models/
#    containers.py:681``).  ``nano_cpus`` is in ``RUN_HOST_CONFIG_KWARGS``
#    (same page, routing table, line 1098; ``models/containers.py:1098``),
#    so ``create`` accepts it.  It is chosen over the ``cpu_quota`` +
#    ``cpu_period`` pair because the pair requires a period value the plan
#    pins nowhere — inventing one would be an unsourced constant — and
#    because emitting both mechanisms for one limit is the same
#    double-selection mistake behaviour 16 avoided.  ``HostConfig``
#    requires the field to be an ``int`` (``docker/types/containers.py:
#    621-623``: non-int raises a host-config type error before any daemon
#    call), so the float ``spec.cpus`` is converted before emission:
#    ``cpus=4.0`` is ``nano_cpus=4_000_000_000`` — 4 CPUs × 1e9, the
#    "units of 1e-9 CPUs" convention — and the conversion is snapshotted.
#
# 2. ``memory`` and ``shm_size`` travel as **strings, verbatim** — the
#    translation does not parse them.  ``mem_limit`` is ``int or str`` with
#    the documented string forms ``100000b``, ``1000k``, ``128m``, ``1g``
#    (``plan/third-party-docs/docker/containers-run-create.md`` §2, line 83;
#    installed docstring ``models/containers.py:665-670``), and
#    ``shm_size`` is ``str or int`` (same page, line 81;
#    ``models/containers.py:757``: "Size of /dev/shm (e.g. ``1G``)").  The
#    SDK parses strings *itself*: ``HostConfig.__init__`` calls
#    ``parse_bytes`` on ``mem_limit`` (``docker/types/containers.py:
#    289-290``) and on a str ``shm_size`` (``types/containers.py:309-313``).
#    A local size-string parser would duplicate ``docker.utils.parse_bytes``
#    — a second parser of exactly the kind plan §4.2 removed for mounts —
#    and would have to re-list ``BYTE_UNITS`` (``docker/constants.py:
#    17-22``), drifting from the SDK.  Config validation owns no size rule
#    to defer to either: ``src/tool_swap/config/schema.py:194-207`` types
#    ``memory`` as ``str | None`` and ``shm_size`` as ``str`` with no
#    pattern or validator, and ``src/tool_swap/config/validate.py``
#    contains no size rule.  Consequence: the plan's behaviour-17 error
#    clause ("an unparseable size string raises ``ValueError`` naming the
#    field and the accepted forms") does **not** apply to the pure
#    translation — the SDK rejects an unknown suffix itself, at
#    ``create`` time, with ``DockerException`` naming the accepted
#    postfixes ``b``/``k``/``m``/``g`` (``docker/utils/utils.py:443-446``)
#    — and the tests below pin the pass-through instead of a local
#    ``ValueError``.
#
# 3. Each ``None`` limit **omits its key** — the omission is *our*
#    contract, stricter than the SDK's own falsy-drops
#    (``docker/types/containers.py:289`` ``if mem_limit is not None``,
#    ``:309`` ``if shm_size is not None``, ``:621`` ``if nano_cpus:``),
#    per the same reasoning as the behaviour-14/15 omission pins
#    (``plan/third-party-docs/docker/containers-run-create.md``
#    consequence 1).


@pytest.mark.parametrize(
    ("cpus", "expected_nano_cpus"),
    [(4.0, 4_000_000_000), (2.5, 2_500_000_000)],
)
def test_build_run_kwargs_cpus_converted_to_nano_cpus(
    cpus: float, expected_nano_cpus: int
) -> None:
    """The config's float CPU limit is emitted as an integer ``nano_cpus``.

    ``cpus`` is a ``float`` (``src/tool_swap/backend/base.py``:
    ``cpus: float | None``) while the SDK's quota field ``nano_cpus`` is an
    ``int`` in units of 1e-9 CPUs (installed docstring
    ``.venv/lib/python3.11/site-packages/docker/models/containers.py:681``;
    ``plan/third-party-docs/docker/containers-run-create.md`` §2, line 82),
    so ``cpus=4.0`` is ``nano_cpus=4_000_000_000`` — 4 CPUs × 1e9 — and the
    fractional case ``cpus=2.5`` is ``2_500_000_000``.  The conversion is
    snapshotted here: a wrong multiplier (e.g. the microseconds-per-CPU
    figure of the ``cpu_period`` mechanism, 100 000 at a 100 ms period)
    would move the value by five orders of magnitude, and only a live
    container would ever reveal it.
    """
    # Arrange
    spec = _spec(cpus=cpus)
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert kwargs["nano_cpus"] == expected_nano_cpus


def test_build_run_kwargs_nano_cpus_is_int_not_float() -> None:
    """``nano_cpus`` is an ``int`` — a float would be a client-side error.

    ``HostConfig`` type-checks the field: a non-``int`` raises a
    host-config type error before any daemon call (``.venv/
    lib/python3.11/site-packages/docker/types/containers.py:621-623``; the
    docstring type is ``int``, ``models/containers.py:681``).  The
    conversion to ``int`` therefore happens in the translation, so the
    returned dict is already safe to ``**``-unpack into
    ``client.containers.create``.
    """
    # Arrange
    spec = _spec(cpus=4.0)
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    value = kwargs["nano_cpus"]
    assert isinstance(value, int)
    assert not isinstance(value, bool)
    assert value == 4_000_000_000


def test_build_run_kwargs_cpus_emits_nano_cpus_not_cpu_quota_pair() -> None:
    """Only ``nano_cpus`` is emitted — never the ``cpu_quota`` pair.

    The saved reference (``plan/third-party-docs/docker/
    containers-run-create.md`` §2, line 82) lists the pair as the
    *alternative* mechanism ("pair with ``cpu_period`` … or use
    ``nano_cpus``"); both are in ``RUN_HOST_CONFIG_KWARGS`` (routing
    table, lines 1066-1067).  Emitting both mechanisms for one limit is
    the same double-selection mistake behaviour 16 avoided for
    ``driver`` versus ``runtime``, and the pair would require a
    ``cpu_period`` value the plan pins nowhere.
    """
    # Arrange
    spec = _spec(cpus=4.0)
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert "cpu_quota" not in kwargs
    assert "cpu_period" not in kwargs


def test_build_run_kwargs_cpus_none_omits_all_cpu_quota_keys() -> None:
    """Edge case: ``cpus=None`` omits every CPU-quota key, not just one.

    The omission is *our* contract, stricter than ``HostConfig``'s own
    falsy-drop (``docker/types/containers.py:621``: ``if nano_cpus:``),
    per the behaviour-14/15 omission pins.  All three quota keys are named
    so a translation that defaults one of them to ``0`` is caught: ``0``
    is a different limit (no CPU) than no limit at all.
    """
    # Arrange
    spec = _spec(cpus=None)
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert "nano_cpus" not in kwargs
    assert "cpu_quota" not in kwargs
    assert "cpu_period" not in kwargs


def test_build_run_kwargs_carries_shm_size_verbatim() -> None:
    """The built-in ``shm_size`` default travels verbatim under ``shm_size``.

    The value is read live from ``BUILT_IN_DEFAULTS["shm_size"]``
    (``src/tool_swap/config/defaults.py``) — restating it here would be the
    second copy behaviours 4, 6 and 7 refuse to make.  The string form is
    what the SDK expects: ``shm_size`` is ``str or int`` (``plan/
    third-party-docs/docker/containers-run-create.md`` §2, line 81;
    installed docstring ``models/containers.py:757``: "Size of /dev/shm
    (e.g. ``1G``)"), and ``HostConfig`` parses a str value itself via
    ``parse_bytes`` (``docker/types/containers.py:309-313``) — so the
    translation passes the string through, unit character included.
    """
    # Arrange: the built-in default, read live, never restated.
    default_shm = BUILT_IN_DEFAULTS["shm_size"]
    assert isinstance(default_shm, str)
    spec = _spec(shm_size=default_shm)
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert kwargs["shm_size"] == default_shm


def test_build_run_kwargs_carries_memory_verbatim() -> None:
    """A ``memory`` string travels verbatim under the exact kwarg
    ``mem_limit``.

    ``mem_limit`` is ``int or str`` — bytes, or a string with a unit char
    (``100000b``, ``1000k``, ``128m``, ``1g``); a unitless string means
    bytes (``plan/third-party-docs/docker/containers-run-create.md`` §2,
    line 83; installed docstring ``models/containers.py:665-670``;
    ``RUN_HOST_CONFIG_KWARGS``, routing table line 1093).  ``HostConfig``
    calls ``parse_bytes`` on it (``docker/types/containers.py:289-290``),
    so the translation passes the string through unchanged.  The kwarg
    name is ``mem_limit``, not ``memory`` — a typo'd name would be a
    ``TypeError`` at routing step 6 of the same page.
    """
    # Arrange
    spec = _spec(memory="16g")
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert kwargs["mem_limit"] == "16g"


def test_build_run_kwargs_memory_unitless_string_passes_through() -> None:
    """Edge case: a unitless ``memory`` string passes through as the
    documented bytes form.

    The SDK documents "if a string is specified without a units
    character, bytes are assumed as an intended unit" (installed
    docstring ``models/containers.py:665-670``; ``plan/
    third-party-docs/docker/containers-run-create.md`` §2, line 83), and
    ``parse_bytes`` implements exactly that branch (``docker/utils/
    utils.py:423-427``).  A translation that *converted* the string to
    an int here would be a local size parser (see this section's header)
    and would fail this pass-through pin.
    """
    # Arrange
    spec = _spec(memory="536870912")
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert kwargs["mem_limit"] == "536870912"


def test_build_run_kwargs_memory_none_omits_mem_limit_key() -> None:
    """Edge case: ``memory=None`` omits the ``mem_limit`` key.

    The omission is *our* contract, stricter than ``HostConfig``'s own
    drop (``docker/types/containers.py:289``: ``if mem_limit is not
    None``), per the behaviour-14/15 omission pins.  ``None`` is the
    built-in default (``BUILT_IN_DEFAULTS["memory"]``,
    ``src/tool_swap/config/defaults.py``) — unlimited — and "unlimited"
    must not travel as a key the daemon would have to interpret.
    """
    # Arrange
    spec = _spec(memory=None)
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert "mem_limit" not in kwargs


def test_build_run_kwargs_shm_size_none_omits_shm_size_key() -> None:
    """Edge case: ``shm_size=None`` omits the ``shm_size`` key.

    The omission is *our* contract, stricter than ``HostConfig``'s own
    drop (``docker/types/containers.py:309``: ``if shm_size is not
    None``), per the behaviour-14/15 omission pins.  ``ContainerSpec``
    types the field ``str | None`` (``src/tool_swap/backend/base.py``),
    so a spec that resolves it to "unset" carries ``None`` and must
    emit no key.
    """
    # Arrange
    spec = _spec(shm_size=None)
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert "shm_size" not in kwargs


@pytest.mark.parametrize(
    ("field", "value", "kwarg"),
    [("memory", "16zz", "mem_limit"), ("shm_size", "2zz", "shm_size")],
)
def test_build_run_kwargs_unknown_size_suffix_passes_through_verbatim(
    field: str, value: str, kwarg: str
) -> None:
    """Edge case: an unknown suffix is passed through, not rejected here.

    The plan's behaviour-17 error clause — "an unparseable size string
    raises ``ValueError`` naming the field and the accepted forms" — does
    **not** apply to the pure translation; see this section's header for
    the full reasoning.  In short: the SDK owns size-string parsing and
    rejects an unknown suffix itself, at ``create`` time, with
    ``DockerException`` naming the accepted postfixes ``b``/``k``/``m``/
    ``g`` (``docker/utils/utils.py:443-446``; the table is
    ``docker/constants.py:17-22``).  A local ``ValueError`` check would
    be a second parser (plan §4.2 removed exactly that for mounts), and
    config validation owns no size rule to defer to
    (``src/tool_swap/config/schema.py:194-207`` is a bare ``str`` field
    with no pattern or validator).  The pass-through is therefore the
    contract, asserted for both size fields so a parser introduced for
    one of them is caught.
    """
    # Arrange
    spec = _spec(**{field: value})
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert kwargs[kwarg] == value


# ---------------------------------------------------------------------------
# Behaviour 18 — ``build_run_kwargs``, port publication
# ---------------------------------------------------------------------------
#
# The decisions this section pins, recorded once here rather than restated
# per test:
#
# 1. The mapping is ``{container_port: published_port}`` — the container
#    port is the **key**, the host port the **value**.  Cited from
#    ``plan/third-party-docs/docker/containers-run-create.md`` §2, line 84:
#    the ``ports`` row documents the key as *"container port (``2222/tcp``
#    form, int, or ``port/protocol`` with ``tcp``/``udp``/``sctp``)"* and
#    the value as *"host port int, ``None`` (random), ``(address, port)``
#    tuple, or list of ints"*.  The installed source walks the mapping
#    key-first when it converts it: ``convert_port_bindings`` iterates
#    ``port_bindings.items()`` and treats ``k`` as the container port,
#    building ``HostPort`` from ``v`` (``.venv/lib/python3.11/
#    site-packages/docker/utils/utils.py`` lines 113–123; the value
#    handling is ``_convert_port_binding``, lines 85–110).  An inverted
#    mapping (host port as key) would publish the container's port to the
#    wrong host address, and only a live container would ever reveal it.
#
# 2. The key is the **bare int container port — the pre-normalisation
#    form, not the post-normalisation ``"8000/tcp"`` string**.  The SDK
#    adds the protocol suffix itself: ``convert_port_bindings`` does
#    ``key = str(k); if '/' not in key: key += '/tcp'``
#    (``.venv/lib/python3.11/site-packages/docker/utils/utils.py`` lines
#    116–118).  The saved page's §2 line 84 lists the int form alongside
#    the ``2222/tcp`` form as accepted key shapes, so both reach the same
#    daemon payload — but the test asserts the shape *we* hand the SDK,
#    which is the bare int: pinning ``"8000/tcp"`` instead would pass
#    while the pre-normalisation form (and the int the resolver carries)
#    silently drifted, and pinning the post-normalisation form would make
#    the test assert the SDK's output, not our input.  ``spec.container_port``
#    is an ``int`` (``src/tool_swap/backend/base.py`` line 93), and the
#    SDK accepts ints (saved page line 84), so no string conversion
#    belongs in the translation.
#
# 3. ``published_port=None`` **omits the ``ports`` key entirely** — the
#    D21 reading: tools are addressed by container name on the shared
#    network, so nothing is published in normal operation
#    (``plan/README.md`` decision table, **D21**; ``src/tool_swap/
#    backend/base.py`` line 103: ``None publishes nothing``).  The
#    omission is *our* contract, stricter than the SDK's falsy-drop
#    (``plan/third-party-docs/docker/containers-run-create.md``
#    consequence 1, lines 148–152: ``ports`` is dropped when falsy, and
#    "behaviours 15 and 18 should still omit the key"; installed source
#    ``docker/models/containers.py`` lines 1138–1140: ``ports = kwargs.
#    pop('ports', {}); if ports:``).
#
# 4. **A host port outside ``BackendConfig.port_range`` is not rejected
#    here.**  Range policy is config validation's; the container backend
#    "must not contain policy. It is a dumb driver behind an interface"
#    (``plan/01_ARCHITECTURE.md`` §2.1, line 158).  No test in this file
#    asserts that the driver rejects an out-of-range port — doing so
#    would pin the wrong contract, and the plan's behaviour-18 edge-case
#    clause names this explicitly.
#
# 5. **The plan's error clause — "a port ≤ 0 raises ``ValueError``" —
#    is read to cover *both* ports.**  The clause names no field, and
#    both ``spec.container_port`` and ``spec.published_port`` are ports
#    the translation consumes: ``container_port`` is the mapping key and
#    ``published_port`` the value, so a non-positive value on *either*
#    side would travel to the daemon as an invalid port.  ``container_port``
#    also serves the health probe later (behaviours 24+ read it via the
#    handle), where a non-positive value is equally malformed.  This is
#    well-formedness, not the ``port_range`` policy of decision point 4:
#    every port a resolved spec carries must be usable by the daemon, and
#    ``≤ 0`` is not.  Both are caller programming errors raised *before
#    any SDK call*, so a plain ``ValueError``, not a member of the
#    seven-member taxonomy in ``tool_swap.backend.errors`` (the same
#    reasoning as behaviour 14's empty-image check and behaviour 16's
#    negative-index check).
#
# 6. ``published_port=None`` is the built-in default (D21 — nothing
#    published), and the spec's ``published_port`` field defaults to
#    ``None`` (``src/tool_swap/backend/base.py`` line 103).  The
#    ``container_port`` value in the mapping tests is read live from
#    ``BUILT_IN_DEFAULTS["container_port"]`` (``src/tool_swap/config/
#    defaults.py`` line 54) — restating ``8000`` here would be the second
#    copy behaviours 4, 6, 7 and 17 refuse to make.


def test_build_run_kwargs_published_port_none_omits_ports_key() -> None:
    """Edge case: ``published_port=None`` omits the ``ports`` key.

    The D21 reading: nothing is published in normal operation, and
    ``container_port`` alone (which the health probe uses later) must
    not produce a ``ports`` key.  The omission is *our* contract,
    stricter than the SDK's falsy-drop (``plan/third-party-docs/docker/
    containers-run-create.md`` consequence 1, lines 148–152; installed
    source ``docker/models/containers.py`` lines 1138–1140).
    """
    # Arrange: the built-in default — nothing published.
    spec = _spec(published_port=None)
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert
    assert "ports" not in kwargs


def test_build_run_kwargs_publishes_container_port_to_host_port() -> None:
    """``published_port=7001`` publishes the container port to host 7001.

    The mapping is ``{spec.container_port: spec.published_port}`` —
    container port as the **key**, host port as the **value**
    (``plan/third-party-docs/docker/containers-run-create.md`` §2, line
    84; installed source ``docker/utils/utils.py`` lines 113–123 walks
    the mapping key-first).  The key is the **bare int** container port —
    the *pre-normalisation* form we hand the SDK; the SDK appends
    ``"/tcp"`` itself (``docker/utils/utils.py`` lines 116–118), so this
    test asserts what *we* pass, not what the SDK does next.  The
    ``container_port`` value is read live from
    ``BUILT_IN_DEFAULTS["container_port"]`` — never restated.
    """
    # Arrange: the built-in container port, read live, never restated.
    default_port = BUILT_IN_DEFAULTS["container_port"]
    assert isinstance(default_port, int)
    spec = _spec(published_port=7001, container_port=default_port)
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert: the pre-normalisation form — bare int key, int value.
    assert kwargs["ports"] == {default_port: 7001}


def test_build_run_kwargs_ports_key_is_bare_int_not_protocol_suffixed() -> None:
    """The key is the bare int container port, not ``"8000/tcp"``.

    The SDK adds the protocol suffix when it is missing (``.venv/lib/
    python3.11/site-packages/docker/utils/utils.py`` lines 116–118:
    ``key = str(k); if '/' not in key: key += '/tcp'``), so both the int
    and the suffixed string reach the same daemon payload — but the test
    asserts the shape *we* pass, which is the bare int: ``spec.
    container_port`` is an ``int`` (``src/tool_swap/backend/base.py``
    line 93) and the saved page lists the int form as an accepted key
    (``containers-run-create.md`` §2, line 84).  A translation that
    pre-suffixed the key to ``"8000/tcp"`` would pass the SDK's
    normalization and silently drift from the int the resolver carries;
    pinning the bare int is what catches it.
    """
    # Arrange: the built-in container port, read live, never restated.
    default_port = BUILT_IN_DEFAULTS["container_port"]
    assert isinstance(default_port, int)
    spec = _spec(published_port=7001, container_port=default_port)
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert: the key is an int, not a string with or without "/tcp".
    ports = kwargs["ports"]
    assert isinstance(ports, dict)
    (key,) = ports
    assert isinstance(key, int)
    assert not isinstance(key, bool)
    assert key == default_port
    assert ports[key] == 7001


def test_build_run_kwargs_out_of_range_host_port_is_not_rejected() -> None:
    """Edge case: a host port outside ``port_range`` is not rejected here.

    Range policy is config validation's, explicitly — the container
    backend "must not contain policy. It is a dumb driver behind an
    interface" (``plan/01_ARCHITECTURE.md`` §2.1, line 158), and the
    plan's behaviour-18 edge-case clause names this.  The translation
    therefore passes an out-of-range host port through verbatim rather
    than raising; a driver that rejected it would be asserting the wrong
    contract.  The value is deliberately far outside the built-in
    ``port_range`` (``src/tool_swap/config/defaults.py`` line 76:
    ``[7000, 7999]``) so a policy check, if introduced, would trip.
    """
    # Arrange: a host port far outside the built-in range.
    spec = _spec(published_port=60000)
    fn = _build_run_kwargs()
    # Act
    kwargs = fn(spec, label_namespace=_NAMESPACE)
    # Assert: passed through verbatim, no range check.
    assert kwargs["ports"] == {spec.container_port: 60000}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("container_port", -1),
        ("container_port", 0),
        ("published_port", -1),
        ("published_port", 0),
    ],
)
def test_build_run_kwargs_non_positive_port_raises_value_error(
    field: str, value: int
) -> None:
    """Error behaviour: a port ≤ 0 raises plain ``ValueError``.

    The plan's clause — "a port ≤ 0 raises ``ValueError``" — names no
    field, and both ports the translation consumes are covered:
    ``container_port`` is the mapping key, ``published_port`` the value,
    and ``container_port`` also serves the health probe later, where a
    non-positive value is equally malformed.  ``≤ 0`` is
    well-formedness, not the ``port_range`` policy (see this section's
    header, decision point 5).  A caller programming error raised *before
    any SDK call* — a plain ``ValueError``, not a member of the
    seven-member taxonomy in ``tool_swap.backend.errors`` (the same
    reasoning as behaviour 14's empty-image and behaviour 16's
    negative-index checks).
    """
    # Arrange: the non-positive port on the named field.
    spec = _spec(**{field: value})
    fn = _build_run_kwargs()
    # Act / Assert
    with pytest.raises(ValueError):
        fn(spec, label_namespace=_NAMESPACE)
