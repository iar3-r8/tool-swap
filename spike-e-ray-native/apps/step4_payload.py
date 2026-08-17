"""Step 4 — Payload by reference (reduced form).

Reuses the running tool_torch from step 3's config.
Per §0a: no S3, no remote payload. This reads a baked-in local file.

The step no longer tests D18 — D18 remains an untested assumption.
"""
from __future__ import annotations

# No new app needed — reuses step3_config's tool_torch deployment.
