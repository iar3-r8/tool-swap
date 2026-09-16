"""Docker backend seam (M2a behaviours 14-27).

This module will hold the docker-py implementation of the
``ContainerBackend`` protocol.  Behaviour 14 delivers the first pure
half of it: :func:`build_run_kwargs`, a translation of a
:class:`~tool_swap.backend.base.ContainerSpec` into the kwargs dict
that ``DockerBackend.start`` (behaviour 21) passes to
``client.containers.create``.  No client, no daemon, no
``DockerBackend`` class in this file yet — those arrive with their own
behaviours, keeping this module a thin shell over pure functions
(plan §4.5).

The kwarg names emitted here are the exact ``create``-accepted names
from the saved docker-py reference
``plan/third-party-docs/docker/containers-run-create.md`` §2 and its
routing table — ``image``, ``name``, ``environment`` and ``labels``
are in ``RUN_CREATE_KWARGS``, and ``network`` is the special-cased
network kwarg (routing step 5), which the SDK also turns into
``network_mode`` internally, so this function never emits that one.
``device_requests`` (behaviour 16) is in ``RUN_HOST_CONFIG_KWARGS``
and takes a list of ``docker.types.DeviceRequest`` instances
(``plan/third-party-docs/docker/gpu-device-requests.md`` §2); this
module is the first — and, per behaviour 27's import-linter contract,
the only — ``tool_swap`` module that imports the docker SDK.
"""

from __future__ import annotations

from docker.types import DeviceRequest

from tool_swap.backend.base import ContainerSpec, MountSpec
from tool_swap.backend.labels import managed_labels


def build_run_kwargs(spec: ContainerSpec, *, label_namespace: str) -> dict[str, object]:
    """Translate a :class:`ContainerSpec` into ``containers.create`` kwargs.

    Pure function: it reads the spec and nothing else — no client, no
    daemon, no environment — and returns a fresh dict on every call so
    a later caller that ``**kwargs``-unpacks it cannot share mutable
    state with another.

    The output carries exactly the keys ``image``, ``name``, ``labels``
    and, when non-empty, ``environment``, ``network``, ``volumes`` and
    ``device_requests``.
    ``labels`` is the full :func:`managed_labels` set for
    *label_namespace* and the spec's tool, with the spec's own labels
    merged in (collision precedence is deliberately not decided by
    behaviour 14; the current order lets spec labels win).
    ``environment`` is the spec's mapping copied as a plain dict,
    ``network`` is the spec's network name, and ``volumes`` is the
    spec's mounts in the documented dict form (behaviour 15).  No
    ``detach`` key: the start path is ``create`` + ``start``, not
    ``run(detach=True)`` (plan §5 behaviour 14, amended).

    Args:
        spec: The fully resolved container spec to translate.
        label_namespace: Resolved label namespace, passed by the
            caller and required; there is no default to fall back on,
            matching the ``DockerBackend`` constructor style of
            plan §4.5.

    Returns:
        A fresh kwargs dict for ``client.containers.create(**kwargs)``:
        always ``image``, ``name`` and ``labels``; ``environment`` only
        when ``spec.env`` is non-empty, ``network`` only when
        ``spec.network`` is not ``None``, ``volumes`` only when
        ``spec.mounts`` is non-empty, and ``device_requests`` (one
        ``DeviceRequest``) only when ``spec.devices`` is non-empty.

    Raises:
        ValueError: ``spec.image`` is empty, or a ``spec.devices`` index
            is negative — caller programming errors, raised before any
            SDK call, so a plain ``ValueError`` rather than a
            ``tool_swap.backend.errors`` taxonomy member.
    """
    if not spec.image:
        raise ValueError("container image must not be empty")
    kwargs: dict[str, object] = {
        "image": spec.image,
        "name": spec.name,
        "labels": {**managed_labels(label_namespace, spec.tool), **dict(spec.labels)},
    }
    if spec.env:
        kwargs["environment"] = dict(spec.env)
    if spec.network is not None:
        kwargs["network"] = spec.network
    if spec.mounts:
        kwargs["volumes"] = _volumes_from_mounts(spec.mounts)
    if spec.devices:
        kwargs["device_requests"] = _device_requests_from_devices(spec)
    return kwargs


def _device_requests_from_devices(spec: ContainerSpec) -> list[DeviceRequest]:
    """Translate resolved GPU indices into one :class:`DeviceRequest`.

    The canonical GPU form for specific devices is
    ``DeviceRequest(driver=spec.gpu_runtime, device_ids=[...])`` — the
    named indices and the named runtime live in one request
    (``plan/third-party-docs/docker/gpu-device-requests.md`` §1).
    ``device_ids`` is a list of *strings*, so each int index is
    converted with ``str()`` in declaration order, duplicates
    collapsed.  ``count`` is never set: the docstring says to set
    either ``count`` or ``device_ids`` and the SDK does not enforce
    that client-side (same §1), so setting both would encode a request
    only a daemon could reject.

    Raises:
        ValueError: a device index is negative — raised before any
            construction, naming the offending index.
    """
    if any(index < 0 for index in spec.devices):
        offending = next(index for index in spec.devices if index < 0)
        raise ValueError(f"device index must be non-negative, got {offending}")
    device_ids = [str(index) for index in dict.fromkeys(spec.devices)]
    return [DeviceRequest(driver=spec.gpu_runtime, device_ids=device_ids)]


def _volumes_from_mounts(mounts: tuple[MountSpec, ...]) -> dict[str, dict[str, str]]:
    """Translate resolved mounts into the ``volumes`` dict form.

    Each entry is ``{source: {"bind": target, "mode": "ro" | "rw"}}``,
    the exact shape documented in
    ``plan/third-party-docs/docker/containers-run-create.md`` §2;
    declaration order is preserved by dict insertion order.  No
    de-duplication: collapsing entries is config-validation's job, not
    the driver's.
    """
    return {
        mount.source: {"bind": mount.target, "mode": "ro" if mount.read_only else "rw"}
        for mount in mounts
    }
