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
"""

from __future__ import annotations

from tool_swap.backend.base import ContainerSpec
from tool_swap.backend.labels import managed_labels


def build_run_kwargs(spec: ContainerSpec, *, label_namespace: str) -> dict[str, object]:
    """Translate a :class:`ContainerSpec` into ``containers.create`` kwargs.

    Pure function: it reads the spec and nothing else — no client, no
    daemon, no environment — and returns a fresh dict on every call so
    a later caller that ``**kwargs``-unpacks it cannot share mutable
    state with another.

    The output carries exactly the keys ``image``, ``name``, ``labels``
    and, when non-empty, ``environment`` and ``network``.  ``labels``
    is the full :func:`managed_labels` set for *label_namespace* and
    the spec's tool, with the spec's own labels merged in (collision
    precedence is deliberately not decided by behaviour 14; the
    current order lets spec labels win).  ``environment`` is the spec's
    mapping copied as a plain dict, and ``network`` is the spec's
    network name.  No ``detach`` key: the start path is
    ``create`` + ``start``, not ``run(detach=True)``
    (plan §5 behaviour 14, amended).

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
        ``spec.network`` is not ``None``.

    Raises:
        ValueError: ``spec.image`` is empty — a caller programming
            error, raised before any SDK call, so a plain
            ``ValueError`` rather than a ``tool_swap.backend.errors``
            taxonomy member.
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
    return kwargs
