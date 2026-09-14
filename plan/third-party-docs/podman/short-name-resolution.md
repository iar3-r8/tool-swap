# Short-name resolution for locally built images — synthesis

**Question (D17, separate concern).** An image was just built locally as
`tool_torch:spike`. When Ray's `image_uri` runtime env hands that string to
`podman run`, does podman resolve it from local storage, or does it attempt
short-name registry resolution and fail like the base image did at build time?

**Answer: local storage is consulted first, and an exact local match never
reaches short-name / registry resolution. No change is required for the
just-built-on-this-host case.** This is documented behaviour for podman
v3.4.4 (the host's version), not an assumption.

## The two load-bearing citations

**1. `podman run --pull` defaults to `missing`, and `missing` is
local-first.** From [`podman-run.1.v3.4.4.md`](podman-run.1.v3.4.4.md),
v3.4.4 man page, option `--pull`:

> Pull image before running. The default is **missing**.
>
> - **missing**: attempt to pull the latest image from the registries listed
>   in registries.conf **if a local image does not exist**. Raise an error if
>   the image is not in any listed registry and is not present locally.

So for `podman run tool_torch:spike`: the local image exists (it was just
built) ⇒ no pull is attempted ⇒ the name is never submitted to short-name
resolution ⇒ the host's missing `unqualified-search-registries` is
irrelevant. The same page's DESCRIPTION says the same thing more loosely:
" If the _image_ is not already loaded then **podman run** will pull the
_image_ ... before it starts the container from that image."

**2. Short-name resolution only runs when a pull is actually performed.**
From [`podman-pull.1.v3.4.4.md`](podman-pull.1.v3.4.4.md), v3.4.4 man page:
an image reference without a registry component is a *short-name* reference,
subject to alias lookup and then to the `unqualified-search-registries` list
— which is precisely where the D17 base-image pull died:

> If the image is a 'short-name' reference, Podman will prompt the user for
> the specific container registry to pull the image from, if an alias for the
> short-name has not been specified in the `short-name-aliases.conf`.

And [`containers-registries.conf.5.v5.17.0.md`](containers-registries.conf.5.v5.17.0.md)
(the exact `registries.conf` reference vendored by podman v3.4.4, per its
`go.mod`: `github.com/containers/image/v5 v5.17.0`) defines what happens when
the list is empty: nothing — there is no registry to try, so an *absent*
short-name image fails deterministically with the error D17 saw:

> `unqualified-search-registries`: An array of _host_[`:`_port_] registries
> to try when pulling an unqualified image, in order.

## Why the build failure and the run case differ

| | Base image at **build** time | Fixture at **run** time |
| --- | --- | --- |
| Name | `rayproject/ray:2.57.0-py311-gpu` (short name) | `tool_torch:spike` (short name) |
| Present in local storage? | **No** — must be pulled from Docker Hub | **Yes** — `podman build -t tool_torch:spike` just stored it |
| `--pull missing` path | pull attempted ⇒ short-name resolution ⇒ **fails** (no `unqualified-search-registries`, no alias) | local hit ⇒ **no pull, no short-name resolution** ⇒ succeeds |

The build-time fix (fully qualify `RAY_BASE_TAG` with `docker.io/`) is
therefore necessary; the run-time name is not affected **as long as the
image is present locally on the node that runs the container**.

## Residual risk and the (not-implemented) recommendation

`--pull missing` re-enters registry resolution whenever the local image is
*absent*: after `podman system prune -a`, or on a worker node that did not
build the fixture. On the D17 host that case would fail exactly like the base
image did, and the documented fix would be to build and reference the
fixtures as `localhost/tool_torch:spike` / `localhost/tool_tf:spike` (the
`localhost` registry resolves against local storage without any
`unqualified-search-registries` entry).

Two doc-based constraints on that fix, both from
[`containers-registries.conf.5.v5.17.0.md`](containers-registries.conf.5.v5.17.0.md):

- `[aliases]` "cannot include a registry domain **or refer to localhost**" —
  so the name must be qualified in the *code/config*, not papered over by an
  alias;
- the man page's own recommendation: "We recommend always using fully
  qualified image names including the registry server (full dns name),
  namespace, image name, and tag."

**Recommendation (D17 report only, not implemented here):** keep the
short names for now — they are documented to work for locally built images —
and record `localhost/` qualification as the hardening step for the
multi-node / pruned-storage case.

## Version applicability

All citations are from the **exact host version (podman v3.4.4)** and the
**exact vendored `containers/image` release (v5.17.0)**. The `--pull missing`
default has been stable across the v3.x line, so the conclusion is not
version-dependent within the range this spike targets; a future podman
upgrade should re-verify the `--pull` default before relying on it.
