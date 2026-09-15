"""Managed-container labels (M2a behaviour 6).

This module produces the exact label set every managed container
carries, in one place.  The label *namespace* is supplied by the
caller — defaulting is the config layer's job, owned by
``BUILT_IN_DEFAULTS["label_namespace"]`` and
``BackendConfig.label_namespace`` — and is never defaulted here;
this module therefore never restates a configured namespace value.
"""

from __future__ import annotations

#: The ``{namespace}.managed-by`` label value.  Deliberately a constant,
#: independent of the namespace: behaviour 7's ``label_selector``
#: receives only the namespace yet must still match it, and a value
#: stable across namespace changes keeps containers labelled under an
#: older namespace recognisable as ours.  Reconciliation, ``tswap ps``,
#: ``prune`` and staleness detection all depend on these labels
#: (plan/08_REPO_LAYOUT.md §2), so this value is effectively permanent.
MANAGED_BY_VALUE = "tool-swap"


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
        f"{namespace}.managed-by": MANAGED_BY_VALUE,
    }
    if group is not None:
        labels[f"{namespace}.group"] = group
    if config_hash is not None:
        labels[f"{namespace}.config-hash"] = config_hash
    if runtime_version is not None:
        labels[f"{namespace}.runtime-version"] = runtime_version
    return labels
