# Podman / containers-image documentation capture

Evidence base for **D17** (spike-E continuation, host-blocker): podman does not
assume Docker Hub for unqualified image names, so the Ray base image tag in
[`spike-e-ray-native/.env.example`](../../../spike-e-ray-native/.env.example) must be
fully qualified (`docker.io/rayproject/ray:2.57.0-py311-gpu`) for hosts whose
`/etc/containers/registries.conf` defines no `unqualified-search-registries`.

## Pages

| File | Upstream | Version captured | What it answers |
| --- | --- | --- | --- |
| [`short-name-resolution.md`](short-name-resolution.md) | synthesis of the two man pages below | podman v3.4.4 | Does `podman run <locally built short name>` hit local storage or registry resolution? **Yes — local storage first** (`--pull missing`, default); registry resolution only when the local image is absent. |
| [`podman-run.1.v3.4.4.md`](podman-run.1.v3.4.4.md) | https://raw.githubusercontent.com/containers/podman/v3.4.4/docs/source/markdown/podman-run.1.md | podman v3.4.4 | `--pull` semantics (default `missing` ⇒ local image short-circuits the pull). |
| [`podman-pull.1.v3.4.4.md`](podman-pull.1.v3.4.4.md) | https://raw.githubusercontent.com/containers/podman/v3.4.4/docs/source/markdown/podman-pull.1.md | podman v3.4.4 | What "short name" means and how it is resolved (aliases → `unqualified-search-registries` → prompt/error). |
| [`containers-registries.conf.5.v5.17.0.md`](containers-registries.conf.5.v5.17.0.md) | https://raw.githubusercontent.com/containers/image/v5.17.0/docs/containers-registries.conf.5.md | containers/image v5.17.0 (the exact version vendored by podman v3.4.4, per its `go.mod`) | `registries.conf` rules: `unqualified-search-registries`, `[aliases]`, `short-name-mode`, docker.io normalization, the "always use fully qualified names" recommendation. |

## Not captured (and why)

- **`podman build` / buildah man pages** — the base-image failure happens in the
  build step, but the mechanism it exercises (pulling an absent base image through
  short-name resolution) is fully covered by `podman-pull.1` + the
  `registries.conf` man page; no additional claim depends on buildah prose.
- **`podman system` / storage internals** — "local image storage" is the
  terminology the man pages use; no deeper storage-doc citation is needed.

## Findings that post-date the captures

None yet. The D17 change (fully qualify `RAY_BASE_TAG`) is the direct
application of the `registries.conf` man page's own recommendation; the
fixture-image `localhost/` question is answered (no change needed for the
just-built-on-this-host case) in [`short-name-resolution.md`](short-name-resolution.md).
