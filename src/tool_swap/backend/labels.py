"""Managed-container labels and names (M2a behaviours 6 and 7).

This module produces the exact label set every managed container
carries, in one place, plus the container-name builder and the
label map that selects our containers.  The label *namespace* and
the container *prefix* are supplied by the caller — defaulting is
the config layer's job, owned by ``BUILT_IN_DEFAULTS`` and
``BackendConfig`` — and are never defaulted here; this module
therefore never restates a configured value.
"""

from __future__ import annotations

import re
from typing import Final

#: The ``{namespace}.managed-by`` label value.  Deliberately a constant,
#: independent of the namespace: behaviour 7's ``label_selector``
#: receives only the namespace yet must still match it, and a value
#: stable across namespace changes keeps containers labelled under an
#: older namespace recognisable as ours.  Reconciliation, ``tswap ps``,
#: ``prune`` and staleness detection all depend on these labels
#: (plan/08_REPO_LAYOUT.md §2), so this value is effectively permanent.
MANAGED_BY_VALUE = "tool-swap"

#: A legal container name: a lowercase letter or digit first, then a
#: run of lowercase letters, digits, ``_`` and ``-``.  A deliberate
#: mirror of TSWAP-C210, whose pattern is owned by
#: ``src/tool_swap/config/validate.py:310``; the two must be changed
#: together.  A backend module must not import the config layer
#: (plan §4.2), so the mirror is cited here, not imported.  The
#: pattern is a strict subset of Docker's legal name charset —
#: deliberately *not* claimed to be Docker's own rule, which this
#: repository has not verified — and no length limit is applied.
_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"[a-z0-9][a-z0-9_-]*")


def _managed_by_key(namespace: str) -> str:
    """The ``{namespace}.managed-by`` key, built in one place.

    ``managed_labels`` and ``label_selector`` both build their
    managed-by key through this helper rather than restating the
    suffix, so the two functions cannot drift apart.

    Args:
        namespace: Resolved label namespace.

    Returns:
        The managed-by key for *namespace*.
    """
    return f"{namespace}.managed-by"


def managed_labels(
    namespace: str,
    tool: str,
    *,
    group: str | None = None,
    config_hash: str | None = None,
    runtime_version: str | None = None,
) -> dict[str, str]:
    """Build the exact label set for one managed container.

    Keys follow the naming table of ``plan/08_REPO_LAYOUT.md`` §2,
    built from the caller-supplied *namespace*::

        {namespace}.model            the tool name
        {namespace}.managed-by       always present
        {namespace}.group            only when *group* is given
        {namespace}.config-hash      only when *config_hash* is given
        {namespace}.runtime-version  only when *runtime_version* is given

    An omitted optional omits its key entirely — never an empty
    string value, which would be a silent reconciliation mismatch.

    Args:
        namespace: Resolved label namespace, passed by the caller.
            Required; there is no default to fall back on.
        tool: Logical tool name, stamped as the ``model`` label value.
        group: Optional group name; its key is omitted when ``None``.
        config_hash: Config hash, stamped verbatim — nothing in this
            module computes or validates one.  Key omitted when
            ``None``.
        runtime_version: Runtime version string; key omitted when
            ``None``.

    Returns:
        The exact label dict: always ``model`` and ``managed-by``,
        plus one key per given optional.

    Raises:
        ValueError: *namespace* or *tool* is empty.
    """
    if not namespace:
        raise ValueError("namespace must not be empty")
    if not tool:
        raise ValueError("tool must not be empty")
    labels: dict[str, str] = {
        f"{namespace}.model": tool,
        _managed_by_key(namespace): MANAGED_BY_VALUE,
    }
    if group is not None:
        labels[f"{namespace}.group"] = group
    if config_hash is not None:
        labels[f"{namespace}.config-hash"] = config_hash
    if runtime_version is not None:
        labels[f"{namespace}.runtime-version"] = runtime_version
    return labels


def container_name(container_prefix: str, tool: str) -> str:
    """Build the container name for one tool.

    The name is ``container_prefix + tool``.  Both the tool name and
    the whole concatenation must match TSWAP-C210's tool-name
    pattern — a lowercase letter or digit first, then lowercase
    letters, digits, ``_`` and ``-``.  That rule is a strict subset
    of Docker's legal name charset, so every name this function
    accepts is one Docker accepts; it is deliberately *not* claimed
    to be Docker's own rule, which this repository has not verified
    (plan behaviour 7, amendment 3).  No length limit is applied.

    Args:
        container_prefix: Resolved prefix, passed by the caller.
            Required; the config layer owns the default.  The only
            input no config rule checks, so an unusable name blames
            it.
        tool: Logical tool name, passed by the caller.

    Returns:
        ``container_prefix + tool``.

    Raises:
        ValueError: the tool name breaks TSWAP-C210 — rejected
            defensively, since the config layer is that rule's
            primary gate — or the concatenation fails the pattern,
            in which case the message names the prefix, the tool
            and the rule.
    """
    if _NAME_PATTERN.fullmatch(tool) is None:
        raise ValueError(
            f"tool name {tool!r} is unusable as a container name: it breaks TSWAP-C210"
        )
    name = container_prefix + tool
    if _NAME_PATTERN.fullmatch(name) is None:
        raise ValueError(
            f"container prefix {container_prefix!r} combined with "
            f"tool {tool!r} yields {name!r}, which breaks TSWAP-C210"
        )
    return name


def label_selector(namespace: str) -> dict[str, str]:
    """The label map that selects our containers.

    A neutral one-entry map, not a docker filter: translating it
    into a backend's own filter form is behaviour 14's job, pinned
    against saved documentation (plan behaviour 7).  The key is the
    managed-by key ``managed_labels`` emits for the same namespace,
    built by the same helper, so the two cannot drift apart.

    Args:
        namespace: Resolved label namespace, passed by the caller.
            Required; the config layer owns the default.

    Returns:
        Exactly one entry: the managed-by key for *namespace*,
        mapped to ``MANAGED_BY_VALUE``.
    """
    return {_managed_by_key(namespace): MANAGED_BY_VALUE}
