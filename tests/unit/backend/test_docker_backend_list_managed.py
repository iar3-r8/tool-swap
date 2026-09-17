"""RED step for M2a behaviour 25 — ``DockerBackend.list_managed``.

See ``plans/m2a-container-backend-seam.md`` behaviour 25 (§5) and §6
item 5.  ``list_managed() -> list[ContainerHandle]`` (the signature is
pinned by the ``ContainerBackend`` protocol in
``src/tool_swap/backend/base.py``, behaviour 8) must:

1. **ask the daemon for stopped containers too** — the call is
   ``client.containers.list(all=True, ...)``: ``all`` is a *parameter*,
   not a filter key (``plan/third-party-docs/docker/
   containers-list-filters.md`` §2: only running containers are shown
   by default, and "there is **no** ``all=`` in the label-filter
   dict"), because reconciliation must see an exited container (plan
   §6 item 5: "``list_managed`` returning stopped containers too");
2. **pass the filter derived from ``label_selector``** — the neutral
   one-entry label map of behaviour 7 translated into the docker
   ``label`` filter's ``"key=value"`` string form (the saved page §3
   records the accepted forms — ``"key"``, ``"key=value"`` or a list —
   and the SDK performs no client-side interpretation; the daemon is
   the authority), so ``list_managed`` and ``label_selector`` cannot
   drift;
3. **take the non-sparse path with ``ignore_removed=True``** —
   recovering ``tool`` from a label means reading labels, and on a
   sparse result the ``labels`` property *raises* (saved page §4,
   [READ], containers.py:54-58), so ``sparse=True`` is ruled out for
   this behaviour; ``ignore_removed=True`` is the documented remedy
   for the ``NotFound`` race when a container disappears between the
   list call and its inspect (saved page §4, lines 87-91).

**The evidence ceiling, stated plainly.**  The stub returns canned
container objects, so these tests pin *the filter we pass* and *our
handling of what comes back*.  Whether the daemon's label selector
*really selects* is **not claimed here** — it is deferred docker
test 1 (``plans/m2-docker-testing-recommendation.md`` §4, round
trip) and no docstring below claims daemon verification.

**Where the handle fields come from.**  ``id`` from ``attrs['Id']``
and ``name`` from ``attrs['Name'].lstrip('/')`` and ``labels`` from
``attrs['Config']['Labels']`` are **[READ]** — the SDK's own property
derivations, recorded in ``plan/third-party-docs/docker/
container-attrs-reload.md`` §3 (resource.py:28-40,
containers.py:28-34, containers.py:47-58).  The stub container
exposes exactly those derivations, so an implementation reading the
properties or the raw attrs observes the same fixture write.  The
``image`` handle field has **no saved page of its own**: the saved
reference records the SDK reading ``attrs['Config']['Labels']``
([READ], containers.py:47-58), which establishes ``Config`` as the
inspect dict's configuration section, and the handle's image is
pinned at ``attrs['Config']['Image']`` as its **[INFERRED]**
Engine-API sibling — an anti-drift pin of the same class as
behaviour 24's ``State.ExitCode`` pin: it proves only that the code
reads the key this fixture writes, and the stub deliberately exposes
**no** ``image`` member, so an implementation reaching for an
unrecorded SDK property fails loudly (routed through
``map_sdk_error``) instead of passing on an unverified fact.

**``tool`` from the label, never from the name.**  ``container_name``
is ``prefix + tool`` (behaviour 7), so a name-parsing implementation
would need the prefix and would silently break for any container
started under a different one.
``test_list_managed_recovers_tool_from_label_not_name`` uses a
container whose name would parse to a *different* tool than its
label says, so only a label-reading implementation passes.

**A malformed container warns, it does not crash.**  A container
carrying our managed-by label but no model label is skipped with a
logged warning (asserted with ``caplog``, as behaviour 24 did for
the unknown-state case) and the surviving containers are still
returned — one malformed container must not deny the caller the
rest.  Plan §6 item 5: reconciliation adopts by label, so a crash
here takes out boot-time reconciliation.

**Daemon-unreachable is availability, not an empty list.**  A bare
``requests`` connection error (``plan/third-party-docs/docker/errors.
md`` §3, [CORRECTED 2026-09-16]) routes through ``map_sdk_error`` to
``BackendUnavailableError`` (behaviour 19), and a daemon refusal is
routed to the taxonomy the same way — returning ``[]`` for either
would read an outage as "nothing is managed".  The mapping table
itself is behaviour 19's and is *not* re-tested here — only that
``list_managed`` *routes* every exception it does not deliberately
swallow through it.

**The stub's fidelity.**  As in behaviours 21-24, the stub records
and never fails on its own: construction is plain (explicit
``__init__``, no dataclass ``__post_init__``), the ``list`` call is
journaled **on entry, before any prepared exception is raised** (so
a test can assert the list call happened even when it failed), and
the only exceptions that ever leave a stub method are SDK/transport
exceptions *prepared in the test body*.  The stub container exposes
exactly ``id``, ``attrs`` and the derived ``name``/``labels``
properties — **not** ``stop``, ``start``, ``wait``, ``reload`` or
``image``: a listing call must observe, never mutate, and must read
the image from the inspect dict where the saved reference
establishes it.

The ``isinstance(backend, ContainerBackend)`` conformance pin is
deliberately **absent**: ``isinstance`` matches on member *names*
and every one of the six must be present, while ``DockerBackend``
carries five methods so far.  The pin is behaviour 26's, where
``logs`` lands and the class is complete — one behaviour, one
cycle.

This file is the RED step: ``DockerBackend`` exists (behaviour 20)
with ``start`` (21), ``stop`` (22), ``is_running`` (23) and
``inspect`` (24) but no ``list_managed``, so every subject test
fails *individually* at the attribute-level gate with its assertions
present and reachable — never aborting pytest collection.  No
``importorskip``, no skips.

Conventions: pytest, AAA, Google-style docstrings, Black at 88
columns, ruff, ``filterwarnings = "error"`` — no test asserts a
docker fact from memory; each is cited to the saved reference
above, and the [INFERRED] claims are marked as such in their
docstrings.
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

from tool_swap.backend.base import ContainerHandle, ContainerSpec
from tool_swap.backend.errors import BackendError, BackendUnavailableError
from tool_swap.backend.fake_backend import FakeBackend
from tool_swap.backend.labels import label_selector, managed_labels

# Neutral label namespace, deliberately distinct from any configured
# default — the discipline of test_docker_backend_start.py, which uses
# "com.acme".
_NAMESPACE = "com.acme"

# The container prefix the backend under test is built with.
_PREFIX = "ms-"

# The list URL a daemon failure would carry — the URL text only feeds
# the synthetic daemon response built through the SDK's own
# classifier (``plan/third-party-docs/docker/errors.md`` §2).
_URL = "http://docker/v1.45/containers/json"


# ---------------------------------------------------------------------------
# The RED gate (attribute-level, per behaviours 19/20/21/22/23/24's pattern)
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
    """Construct ``DockerBackend(stub, …)`` with ``list_managed`` present.

    While ``list_managed`` is absent this raises ``AssertionError``
    naming the missing method, so the subject tests fail
    individually rather than aborting the run.

    Args:
        stub: The recording client to inject.

    Returns:
        The constructed backend.

    Raises:
        AssertionError: the module or the ``DockerBackend`` class is
            missing, or the class still defines no ``list_managed``
            method — the GREEN step must add it to
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
    if not hasattr(backend_cls, "list_managed"):
        raise AssertionError(
            "DockerBackend.list_managed is missing — the GREEN step must "
            "add the list_managed method to "
            "src/tool_swap/backend/docker_backend.py (behaviour 25)"
        )
    return backend_cls(stub, label_namespace=_NAMESPACE, container_prefix=_PREFIX)


# ---------------------------------------------------------------------------
# The fixtures
# ---------------------------------------------------------------------------


def _list_attrs(
    *,
    name: str,
    labels: dict[str, str],
    image: str,
    container_id: str,
    state: str = "running",
) -> dict[str, object]:
    """A canned ``container.attrs`` dict in the Engine API's inspect shape.

    The keys rest on the saved reference where it has SDK code
    behind them: ``Id`` **[READ]** (resource.py:28-40), ``Name``
    **[READ]** (containers.py:28-34 — the SDK strips the leading
    ``/``), ``Config.Labels`` **[READ]** (containers.py:47-58) and
    ``State.Status`` **[READ]** (containers.py:59-67);
    ``Config.Image`` is the **[INFERRED]** Engine-API sibling of
    ``Config.Labels`` — see the module docstring for the full
    evidence statement.  A test asserting the code reads these keys
    proves only that the code reads the keys this fixture writes: an
    anti-drift pin, not a proof of the daemon's real key names.

    ``State.Status`` is present because a non-sparse list returns a
    full inspect per container (saved page §4: the per-item inspect
    loop); the handle carries no state, so no test asserts on it.

    Args:
        name: The container's name, given daemon-style with its
            leading slash.
        labels: The container's label map (``Config.Labels``).
        image: The image reference (``Config.Image``, [INFERRED]).
        container_id: The runtime id (``Id``).
        state: The value of ``State.Status`` the daemon reports.

    Returns:
        A fresh attrs dict; every call returns independent storage.
    """
    return {
        "Id": container_id,
        "Name": f"/{name}",
        "Config": {"Labels": dict(labels), "Image": image},
        "State": {"Status": state},
    }


def _expected_list_kwargs() -> dict[str, object]:
    """The exact ``containers.list`` kwargs behaviour 25 pins.

    **Derived, never restated**: the label entry comes from calling
    ``label_selector(_NAMESPACE)`` (behaviour 7's neutral one-entry
    map) at test time, and the translation into docker's filter form
    is the saved page's ``"key=value"`` string form (containers-
    list-filters.md §3: the ``label`` filter accepts ``"key"``,
    ``"key=value"`` or a list of such; the docstring's own example is
    ``filters={"label": "tswap.owner=me"}``).  If behaviour 7's map
    changes, the expected filter changes with it — the test pins the
    *translation*, not a second copy of the map.

    The strict equality in the test that consumes this also pins the
    *absence* of the other parameters: no ``sparse`` (``sparse=True``
    is ruled out for this behaviour — the labels property would
    raise, saved page §4), no ``before``/``since``/``limit``, and no
    ``all`` key inside ``filters`` (``all`` is a parameter, not a
    filter key, saved page §2).

    Returns:
        ``{"all": True, "filters": {"label": "<key>=<value>"},
        "ignore_removed": True}`` with the label entry computed from
        ``label_selector``.
    """
    selector = label_selector(_NAMESPACE)
    assert len(selector) == 1
    (key, value) = next(iter(selector.items()))
    return {
        "all": True,
        "filters": {"label": f"{key}={value}"},
        "ignore_removed": True,
    }


def _spec() -> ContainerSpec:
    """A minimal spec for the ``FakeBackend`` half of the agreement test."""
    return ContainerSpec(
        tool="llama",
        name=f"{_PREFIX}llama",
        image="example/tool:1.0",
        gpu_runtime="cuda",
        container_port=8080,
    )


# ---------------------------------------------------------------------------
# The recording stub
# ---------------------------------------------------------------------------


@dataclass
class _RecordedListCall:
    """One recorded ``list`` call: the kwargs it was passed, verbatim."""

    kwargs: dict[str, object]


class _ListedContainer:
    """A stand-in for the ``Container`` object ``list`` returns.

    A non-sparse ``list`` runs the per-item inspect loop (saved page
    §4, lines 1013-1024 of the source the page cites), so every
    object it returns already carries a fresh full inspect —
    ``attrs`` as the raw dict.  This stub mirrors the SDK's three
    property derivations the saved reference marks **[READ]**:
    ``name`` from ``attrs['Name'].lstrip('/')`` (containers.py:28-
    34), ``labels`` from ``attrs['Config']['Labels']``
    (containers.py:47-58) and ``id`` from ``attrs['Id']``
    (resource.py:28-40), so a single fixture write feeds every read
    path exactly as one daemon inspect would.  An implementation
    reading the properties or the raw attrs observes the same data.

    Nothing else exists — **not** ``stop``, **not** ``start``,
    **not** ``wait``, **not** ``reload`` (a listing call must
    observe, never mutate, and a second per-container lookup would
    duplicate what the non-sparse list already did), and **not**
    ``image``: no saved page records an SDK image property, so the
    handle's image field is pinned at ``attrs['Config']['Image']``
    (the [INFERRED] sibling of the [READ] ``Config.Labels``, see the
    module docstring) — an implementation reaching for the
    unrecorded property fails loudly through ``map_sdk_error``
    instead of passing on memory.

    ``__init__`` is explicit, not a dataclass: the code under test
    wraps its call in ``except Exception`` (the behaviour-21/22/
    23/24 pattern), so a construction failure raised *inside*
    ``list_managed`` would be routed through ``map_sdk_error`` and
    surface as a ``BackendError`` that looks like an implementation
    fault and is a test fault instead.  A recording stub must fail
    where it is called from — in the test body — never inside the
    seam it records.
    """

    def __init__(self, attrs: dict[str, object], container_id: str) -> None:
        """Store the id and the raw inspect dict.

        The parameter is ``container_id`` — not ``id``, which ruff
        forbids as a shadowed builtin — while the attribute it stores
        stays ``id``, the name the SDK's ``Container`` carries.

        Args:
            attrs: The raw inspect dict the daemon returned.
            container_id: The runtime id ``list`` reports.
        """
        self.attrs = attrs
        self.id = container_id

    @property
    def name(self) -> str:
        """The name property, derived as the SDK derives it.

        ``attrs['Name'].lstrip('/')`` — the [READ] derivation
        (containers.py:28-34, container-attrs-reload.md §3).
        """
        return str(self.attrs["Name"]).lstrip("/")

    @property
    def labels(self) -> dict[str, str]:
        """The labels property, derived as the SDK derives it.

        ``attrs['Config']['Labels']`` — the [READ] derivation
        (containers.py:47-58, container-attrs-reload.md §3).  The
        sparse-object raise the SDK carries is not modelled: the
        fixtures are full inspects, which is what a non-sparse
        ``list`` returns (containers-list-filters.md §4).
        """
        config: object = self.attrs["Config"]
        if not isinstance(config, Mapping):
            raise AssertionError("stub fixture: Config is not a mapping")
        labels: object = config["Labels"]
        if not isinstance(labels, Mapping):
            raise AssertionError("stub fixture: Config.Labels is not a mapping")
        return {str(key): str(value) for key, value in labels.items()}


class _RecordingContainers:
    """A stand-in for ``client.containers``: ``list`` only.

    ``list(**kwargs)`` mirrors the SDK signature's keyword surface
    (containers-list-filters.md §1: ``list(all=False, before=None,
    filters=None, limit=-1, since=None, sparse=False,
    ignore_removed=False)``) and records the call **on entry,
    before any prepared exception is raised** — the same on-entry
    journaling ``FakeBackend`` applies to its own calls — so a test
    can assert the list call happened, and with which kwargs, even
    when it failed.  No other member exists: a backend reaching for
    ``get``, ``create`` or ``run`` hits ``AttributeError``.
    """

    def __init__(
        self,
        containers: list[_ListedContainer],
        error: BaseException | None = None,
    ) -> None:
        """Prepare the recorded behaviour of ``list``.

        Args:
            containers: The objects ``list`` returns (``[]`` for the
                zero-match case; the prepared exception wins when
                ``error`` is set — the daemon never answered).
            error: Exception ``list`` raises after recording the call
                (``None`` for the happy path) — always prepared in
                the test body, never a stub-internal fault.
        """
        self._containers = containers
        self._error = error
        self.list_calls: list[_RecordedListCall] = []

    def list(self, **kwargs: object) -> list[_ListedContainer]:
        """Record the call; return the prepared list or raise.

        Raises:
            BaseException: the prepared ``error``, verbatim — an SDK
                or transport exception built in the test body, never
                a stub-internal fault.
        """
        self.list_calls.append(_RecordedListCall(kwargs=dict(kwargs)))
        if self._error is not None:
            raise self._error
        return list(self._containers)


class _RecordingClient:
    """A stand-in for the injected ``docker.DockerClient``.

    Carries exactly the one attribute the ``list_managed`` path
    touches — ``containers`` — and nothing else, so a backend that
    reaches past ``containers.list`` fails with ``AttributeError``
    rather than being waved through by a permissive stub.
    """

    def __init__(
        self,
        containers: list[_ListedContainer],
        list_error: BaseException | None = None,
    ) -> None:
        """Build the client around one prepared ``list`` outcome.

        Args:
            containers: The objects ``list`` returns.
            list_error: Exception ``list`` raises after recording
                the call.
        """
        self.containers = _RecordingContainers(containers=containers, error=list_error)


# ---------------------------------------------------------------------------
# The error fixtures (built the way the SDK builds them)
# ---------------------------------------------------------------------------


def _server_error_500() -> docker.errors.APIError:
    """A generic 500 — a daemon refusal with no dedicated taxonomy row.

    Runs the synthetic daemon response through
    ``docker.errors.create_api_error_from_http_exception`` — the
    single classifier every non-2xx response passes through in
    production (``plan/third-party-docs/docker/errors.md`` §2) — so
    its class, ``explanation`` and ``status_code`` derive from the
    response exactly as in production.
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
    ``requests`` as-is; ``map_sdk_error`` step 2 matches it).  This
    is what *not* being there is **not**: the daemon is gone, so the
    failure is availability, not an empty fleet.
    """
    return requests.exceptions.ConnectionError(
        "Cannot connect to the Docker daemon at unix:///var/run/docker.sock"
    )


# ---------------------------------------------------------------------------
# Behaviour 25 — the list call shape
# ---------------------------------------------------------------------------


def test_list_managed_pins_call_shape_all_derived_filter_ignore_removed() -> None:
    """The one ``list`` call is exactly the pinned shape, derived.

    This is the test the plan's "Verified" line names: the stub
    client asserts the filter passed equals ``label_selector``'s
    entry, translated into docker's ``label`` filter form.
    Concretely the strict equality on the recorded kwargs pins:

    - ``all=True`` as a **parameter** — stopped containers
      included, since only running ones are shown by default and
      "there is **no** ``all=`` in the label-filter dict"
      (containers-list-filters.md §2, lines 27-34).
      Reconciliation must see an exited container (plan §6 item
      5), so this is the edge no other test would catch: an
      implementation omitting it passes every fixture whose
      containers happen to be running;
    - ``filters`` exactly ``{"label": "<key>=<value>"}`` with the
      entry **derived by calling ``label_selector(_NAMESPACE)``**
      at test time — the ``"key=value"`` string form of the saved
      page's three accepted forms (§3, line 47), not a list, not a
      bare ``"key"``.  The expectation is never a restated dict:
      change behaviour 7's map and the expectation changes with
      it;
    - ``ignore_removed=True`` — the documented remedy for the
      ``NotFound`` race when a container vanishes between the list
      call and its inspect (saved page §4, lines 87-91);
    - **no ``sparse`` key at all** — ``sparse=True`` is ruled out
      for this behaviour because ``tool`` is recovered from a label
      and the labels property raises on a sparse object (saved
      page §4, lines 79-99); the strict equality is what pins the
      absence.

    **Not claimed here:** whether the daemon's selector really
    selects.  The SDK performs no client-side interpretation of
    ``filters`` (saved page §3, lines 65-67) — the daemon is the
    authority, and that half is deferred docker test 1.  This test
    pins only the filter we *pass*.

    Arrange: a stub whose ``list`` returns one of our containers.
    Act: ``backend.list_managed()`` — must not raise.
    Assert: exactly one ``list`` call, with the derived kwargs; the
    result carries our container's handle.
    """
    container = _ListedContainer(
        _list_attrs(
            name=f"{_PREFIX}llama",
            labels=managed_labels(_NAMESPACE, "llama"),
            image="example/llama:1.0",
            container_id="deadbeef",
        ),
        container_id="deadbeef",
    )
    stub = _RecordingClient([container])
    backend = _backend_with(stub)

    result = backend.list_managed()

    assert isinstance(result, list)
    assert [handle.id for handle in result] == ["deadbeef"]
    containers = cast("_RecordingContainers", stub.containers)
    assert len(containers.list_calls) == 1
    assert containers.list_calls[0].kwargs == _expected_list_kwargs()


# ---------------------------------------------------------------------------
# Behaviour 25 — our containers only
# ---------------------------------------------------------------------------


def test_list_managed_returns_our_handles_only_and_stays_silent_for_foreign(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A mix of our containers and foreign ones yields our handles only.

    The foreign container carries no managed-by label at all — it
    is not ours, full stop, and is skipped **silently**: a warning
    is reserved for a container that *is* ours (managed-by label
    present) but malformed (model label missing, the next test).
    An implementation that warned on "no model label" regardless of
    managed-by would warn here and fail.  The assertion that no
    warning was logged is what separates "not ours" from "ours but
    broken".

    The handle fields are asserted in full — ``id`` from
    ``attrs['Id']`` **[READ]**, ``name`` from the daemon's name with
    the leading slash stripped **[READ]** (the SDK's own
    ``container.name`` derivation, containers.py:28-34), ``tool``
    **from the model label** and ``image`` from
    ``attrs['Config']['Image']`` **[INFERRED]** (see the module
    docstring) — so a result that silently drops or mangles a field
    cannot pass.

    Arrange: a stub whose ``list`` returns one of our running
    containers, one of our exited ones, and one foreign container
    (labels from another owner).
    Act: ``backend.list_managed()`` — must not raise.
    Assert: exactly our two handles, in full, the foreign id
    absent, and no record at WARNING or above.
    """
    ours_running = _ListedContainer(
        _list_attrs(
            name=f"{_PREFIX}alpha",
            labels=managed_labels(_NAMESPACE, "alpha"),
            image="example/alpha:1.0",
            container_id="aaaa1111",
            state="running",
        ),
        container_id="aaaa1111",
    )
    ours_exited = _ListedContainer(
        _list_attrs(
            name=f"{_PREFIX}beta",
            labels=managed_labels(_NAMESPACE, "beta"),
            image="example/beta:1.0",
            container_id="bbbb2222",
            state="exited",
        ),
        container_id="bbbb2222",
    )
    foreign = _ListedContainer(
        _list_attrs(
            name="other-service",
            labels={"owner": "someone-else"},
            image="registry/other:2",
            container_id="cccc3333",
        ),
        container_id="cccc3333",
    )
    stub = _RecordingClient([ours_running, foreign, ours_exited])
    backend = _backend_with(stub)

    with caplog.at_level(logging.WARNING):
        result = backend.list_managed()

    expected = [
        ContainerHandle(
            id="aaaa1111",
            name=f"{_PREFIX}alpha",
            tool="alpha",
            image="example/alpha:1.0",
        ),
        ContainerHandle(
            id="bbbb2222",
            name=f"{_PREFIX}beta",
            tool="beta",
            image="example/beta:1.0",
        ),
    ]
    assert sorted(result, key=lambda handle: handle.id) == sorted(
        expected, key=lambda handle: handle.id
    )
    assert all(handle.id != "cccc3333" for handle in result)
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


# ---------------------------------------------------------------------------
# Behaviour 25 — tool from the label, never from the name
# ---------------------------------------------------------------------------


def test_list_managed_recovers_tool_from_label_not_name() -> None:
    """``tool`` comes from the model label — a name-parsing
    implementation fails this test.

    ``container_name`` is ``prefix + tool`` (behaviour 7), so a
    name-parsing implementation would strip the prefix and read
    ``embedder-v2`` out of ``ms-embedder-v2`` — while the
    container's model label says ``embedder``.  The two disagree,
    and the label wins: reconciliation adopts by label (plan §6
    item 5), and a container started under a *different* prefix
    (a namespace migration, a hand-created container adopted later)
    would parse to the wrong tool and be reconciled against the
    wrong entry — the silent break the requirement exists to
    prevent.  This fixture is the one that makes the requirement
    real.

    The name itself is reported unchanged — the handle's ``name``
    is the container's name, not a source to derive from.

    Arrange: a stub whose ``list`` returns one of our containers
    whose name, minus the prefix, is not the tool its label says.
    Act: ``backend.list_managed()`` — must not raise.
    Assert: the one handle carries ``tool == "embedder"`` (the
    label) and ``name == "ms-embedder-v2"`` (the name, verbatim).
    """
    container = _ListedContainer(
        _list_attrs(
            name=f"{_PREFIX}embedder-v2",
            labels=managed_labels(_NAMESPACE, "embedder"),
            image="example/embedder:3.0",
            container_id="eeee5555",
        ),
        container_id="eeee5555",
    )
    stub = _RecordingClient([container])
    backend = _backend_with(stub)

    result = backend.list_managed()

    assert [handle.tool for handle in result] == ["embedder"]
    assert [handle.name for handle in result] == [f"{_PREFIX}embedder-v2"]
    assert [handle.id for handle in result] == ["eeee5555"]


# ---------------------------------------------------------------------------
# Behaviour 25 — stopped containers are visible
# ---------------------------------------------------------------------------


def test_list_managed_includes_stopped_containers() -> None:
    """An exited container is listed — the call asks for it.

    The plan's explicit edge (behaviour 25; §6 item 5): "the list
    call must include stopped containers — reconciliation must see
    an exited one".  The mechanism is the ``all=True`` **parameter**
    — not a filter key — because only running containers are shown
    by default (containers-list-filters.md §2, lines 27-34); this
    test pins the parameter on the recorded call *and* the
    consequence on the result, so an implementation that drops the
    parameter (passing every fixture that happens to contain only
    running containers) fails here.

    Arrange: a stub whose ``list`` returns one of our running and
    one of our exited containers.
    Act: ``backend.list_managed()`` — must not raise.
    Assert: the recorded call passed ``all=True``; both handles are
    returned.
    """
    running = _ListedContainer(
        _list_attrs(
            name=f"{_PREFIX}live",
            labels=managed_labels(_NAMESPACE, "live"),
            image="example/live:1.0",
            container_id="1111aaaa",
            state="running",
        ),
        container_id="1111aaaa",
    )
    exited = _ListedContainer(
        _list_attrs(
            name=f"{_PREFIX}dead",
            labels=managed_labels(_NAMESPACE, "dead"),
            image="example/dead:1.0",
            container_id="2222bbbb",
            state="exited",
        ),
        container_id="2222bbbb",
    )
    stub = _RecordingClient([running, exited])
    backend = _backend_with(stub)

    result = backend.list_managed()

    assert sorted(handle.id for handle in result) == ["1111aaaa", "2222bbbb"]
    containers = cast("_RecordingContainers", stub.containers)
    assert containers.list_calls[0].kwargs["all"] is True


# ---------------------------------------------------------------------------
# Behaviour 25 — zero matches
# ---------------------------------------------------------------------------


def test_list_managed_with_zero_matches_returns_empty_list() -> None:
    """An empty daemon answer is ``[]`` — not an error, not a crash.

    The plan's explicit edge: "zero matches returns ``[]``".  A
    fresh node, a fully reconciled fleet, or a namespace migration
    all look like this, and reconciliation must treat "none
    managed" as a normal answer — the call still carries the pinned
    filter, so the empty result is a *filtered* empty, not an
    unfiltered one.

    Arrange: a stub whose ``list`` returns ``[]``.
    Act: ``backend.list_managed()`` — must not raise.
    Assert: the result is ``[]``; the one ``list`` call carried the
    derived filter.
    """
    stub = _RecordingClient([])
    backend = _backend_with(stub)

    result = backend.list_managed()

    assert result == []
    containers = cast("_RecordingContainers", stub.containers)
    assert len(containers.list_calls) == 1
    assert containers.list_calls[0].kwargs == _expected_list_kwargs()


# ---------------------------------------------------------------------------
# Behaviour 25 — malformed: managed-by present, model label missing
# ---------------------------------------------------------------------------


def test_list_managed_warns_and_skips_on_missing_model_label(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ours but broken: a warning, a skip, and the rest still returned.

    The plan's explicit edge: "a container carrying our managed-by
    label but no model label is skipped with a warning rather than
    crashing the caller".  Plan §6 item 5 makes this load-bearing —
    reconciliation adopts by label, so a crash here takes out
    boot-time reconciliation entirely, and a silent skip would make
    an unadoptable container invisible in production.  The warning
    is asserted with ``caplog`` (as behaviour 24 did for the
    unknown-state case): a test that omits the assertion lets the
    warning be silently dropped, which is exactly how a malformed
    container becomes invisible.  The assertion checks level and
    that the message names the offending container (by its name or
    its id) — not the exact wording, so the GREEN step owns the
    message text.

    The surviving container is still returned: one malformed
    container must not deny the caller the rest.

    Arrange: a stub whose ``list`` returns one healthy container
    and one carrying only the managed-by label (no model label).
    Act: ``backend.list_managed()`` — must **not** raise.
    Assert: the healthy handle returned, the malformed id absent,
    and at least one record at WARNING or above naming the
    malformed container.
    """
    healthy = _ListedContainer(
        _list_attrs(
            name=f"{_PREFIX}healthy",
            labels=managed_labels(_NAMESPACE, "healthy"),
            image="example/healthy:1.0",
            container_id="3333cccc",
        ),
        container_id="3333cccc",
    )
    mangled_name = f"{_PREFIX}mangled"
    mangled = _ListedContainer(
        _list_attrs(
            name=mangled_name,
            labels=dict(label_selector(_NAMESPACE)),
            image="example/mangled:1.0",
            container_id="4444dddd",
        ),
        container_id="4444dddd",
    )
    stub = _RecordingClient([healthy, mangled])
    backend = _backend_with(stub)

    with caplog.at_level(logging.WARNING):
        result = backend.list_managed()

    assert [handle.id for handle in result] == ["3333cccc"]
    assert all(handle.id != "4444dddd" for handle in result)
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(
        mangled_name in record.getMessage() or "4444dddd" in record.getMessage()
        for record in warnings
    ), (
        f"no WARNING naming the malformed container ({mangled_name!r} / "
        f"4444dddd) was logged"
    )


# ---------------------------------------------------------------------------
# Behaviour 25 — availability is not an empty fleet
# ---------------------------------------------------------------------------


def test_list_managed_on_dead_daemon_surfaces_backend_unavailable() -> None:
    """Daemon-unreachable is **not** an empty list — it must not be
    swallowed.

    A bare ``requests`` connection error (errors.md §3, [CORRECTED
    2026-09-16]) means the daemon is gone: the fleet is not *known*
    to be empty, the read simply could not happen.
    ``map_sdk_error`` maps that row to
    ``BackendUnavailableError`` (behaviour 19), and returning
    ``[]`` would make every outage read as "nothing is managed" —
    reconciliation would then adopt nothing and reap everything.
    This is the test a blanket ``except Exception`` returning
    ``[]`` fails: it would return where a taxonomy member must be
    raised, and ``pytest.raises`` records that as ``DID NOT RAISE``.
    The mapping table itself is behaviour 19's and is not re-tested
    here.

    Arrange: a stub whose ``list`` records the call then raises the
    connection error.
    Act: ``backend.list_managed()``, expected to raise.
    Assert: ``BackendUnavailableError`` — not ``[]``, not a
    ``DockerException`` — with the raw error chained as
    ``__cause__``; the list call happened once.
    """
    error = _daemon_unreachable()
    stub = _RecordingClient([], list_error=error)
    backend = _backend_with(stub)

    with pytest.raises(BackendUnavailableError) as excinfo:
        backend.list_managed()
    raised = excinfo.value
    assert not isinstance(raised, docker.errors.DockerException)
    assert isinstance(raised, BackendError)
    assert raised.__cause__ is error
    containers = cast("_RecordingContainers", stub.containers)
    assert len(containers.list_calls) == 1


def test_list_managed_on_daemon_refusal_is_routed_not_swallowed() -> None:
    """A daemon 500 during the list is routed through
    ``map_sdk_error`` — it must not become ``[]``.

    The 500 is the row that proves *routing*, not *classification*:
    the mapping table is behaviour 19's and is not re-tested here —
    only that whatever ``list`` raises passes through
    ``map_sdk_error`` and the result is raised, the raw SDK
    exception chained as ``__cause__`` and no
    ``docker.errors.DockerException`` escaping.  A blanket
    ``except Exception`` returning ``[]`` fails this test the same
    way it fails the dead-daemon test: a daemon refusal is an
    availability failure, and reading it as "empty fleet" tells
    reconciliation a fleet the daemon could not even be asked about
    does not exist.

    Arrange: a stub whose ``list`` records the call then raises the
    500 built through the SDK's own classifier (errors.md §2).
    Act: ``backend.list_managed()``, expected to raise.
    Assert: a ``BackendError``-family member, not a
    ``DockerException``, with the raw 500 as ``__cause__``; the
    list call happened once.
    """
    error = _server_error_500()
    stub = _RecordingClient([], list_error=error)
    backend = _backend_with(stub)

    with pytest.raises(BackendError) as excinfo:
        backend.list_managed()
    raised = excinfo.value
    assert not isinstance(raised, docker.errors.DockerException)
    assert raised.__cause__ is error
    containers = cast("_RecordingContainers", stub.containers)
    assert len(containers.list_calls) == 1


# ---------------------------------------------------------------------------
# Behaviour 25 — the presence contract, paired with FakeBackend
# ---------------------------------------------------------------------------


def _fake_list_counts() -> tuple[int, int, int]:
    """Drive ``FakeBackend.list_managed`` through the three scenarios.

    The fake's documented contract (behaviour 10): ``list_managed``
    returns "every managed container, stopped ones included" — a
    stopped container stays listed, a vanished one disappears
    (``fake_backend.py``'s ``list_managed`` and ``vanish``).

    Returns:
        The handle counts after ``start``, after ``stop`` and after
        ``vanish``.
    """
    fake = FakeBackend()
    handle = fake.start(_spec())
    after_start = fake.list_managed()
    fake.stop(handle, timeout_s=5.0)
    after_stop = fake.list_managed()
    fake.vanish(handle)
    after_vanish = fake.list_managed()
    return len(after_start), len(after_stop), len(after_vanish)


def _docker_list_counts() -> tuple[int, int, int]:
    """Drive ``DockerBackend.list_managed`` through the same scenarios.

    The docker half of each scenario is the daemon's list answer: a
    running container, an exited one, and no container at all — the
    same three facts, observed the way the daemon reports them.

    Returns:
        The handle counts for running, exited and absent.
    """
    counts: list[int] = []
    for state, present in (("running", True), ("exited", True), (None, False)):
        containers: list[_ListedContainer] = []
        if present:
            assert state is not None
            containers = [
                _ListedContainer(
                    _list_attrs(
                        name=f"{_PREFIX}llama",
                        labels=managed_labels(_NAMESPACE, "llama"),
                        image="example/tool:1.0",
                        container_id="beefcafe",
                        state=state,
                    ),
                    container_id="beefcafe",
                )
            ]
        stub = _RecordingClient(containers)
        backend = _backend_with(stub)
        result = backend.list_managed()
        counts.append(len(result))
    return tuple(counts)


def test_list_managed_contract_matches_fake_backend() -> None:
    """Both backends must agree on the presence contract — or the fast
    unit tests rest on a lie.

    The shared contract, from base.py's protocol and plan §6 item 5:
    *every managed container, stopped ones included*.  A stopped
    container is still managed — reconciliation must see it, adopt
    it by label, and find its port state nowhere (D21: there is
    none to reconcile) — so it stays listed.  A container removed
    out of band is no longer *known* to be managed and disappears.
    This test runs the same three scenarios — present and running,
    present and stopped, absent — through both backends and demands
    agreement on the handle count:

    1. running → 1 handle on both sides;
    2. stopped → **1 handle on both sides** — the load-bearing
        half, the "stopped ones included" contract a docker
        implementation that filtered to running would break;
    3. absent → **0 handles on both sides** without raising.

    The fields themselves are not compared: the fake mints uuid
    ids and has no image of its own, while the docker half reads
    the daemon's attrs (its own dedicated tests pin the fields,
    including tool-from-label).  A disagreement in either direction
    fails this test naming the scenario.
    """
    fake_counts = _fake_list_counts()
    docker_counts = _docker_list_counts()

    assert fake_counts == docker_counts == (1, 1, 0), (
        f"DockerBackend.list_managed disagreed with FakeBackend: "
        f"docker={docker_counts}, fake={fake_counts} — the contract is "
        f"(running: 1, stopped: 1, absent: 0)"
    )
