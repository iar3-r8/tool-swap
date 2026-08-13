# llama-swap — container security

**Source URL:** https://github.com/mostlygeek/llama-swap/blob/main/docs/container-security.md
**Upstream version at capture:** **v249** (latest release, published 2026-08-10); file read from `main`
**Captured:** 2026-08-13
**Relevance to tool-swap:** **D20** puts the router in a container with a mounted docker socket and states plainly that this is *"root-equivalent"*. This page is the only prior art in the captures on running an on-demand model swapper safely, and it bears directly on the base images generated in M5.
**Completeness:** **verbatim**, complete. The page is short.

---

## Container Security

For convenience, the default container images use the **root** user within the container. This permits simplified access to host resources including volume mounts and hardware devices under `/dev/dri` (*for Vulkan support*). But this can widen the attack surface to privilege escalation exploits.

Alternative images, tagged as `non-root`, are also available. For example, `llama-swap:cpu-non-root` uses the unprivileged **app** user by default. Depending on deployment requirements, additional configuration may be necessary to ensure that the container retains access to required hosts resources. This might entail customizing host filesystem permissions/ownership appropriately or injecting host group membership into the container.

Docker offers a [system-wide option enabling user namespace remapping](https://docs.docker.com/engine/security/userns-remap/) to accommodate situations were a **root** container user is required but also mentions that *"The best way to prevent privilege-escalation attacks from within a container is to configure your container's applications to run as unprivileged users."*

Podman offers similar capability, per-container, to [set UID/GID mapping in a new user namespace](https://docs.podman.io/en/latest/markdown/podman-run.1.html#set-uid-gid-mapping-in-a-new-user-namespace).

The Large Language Model (*LLM/AI*) ecosystem is rapidly evolving and [serious security vulnerabilities have surfaced in the past](https://huggingface.co/docs/hub/security-pickle). These alternative *non-root* images could reduce the impact of future unknown problems. However, proper planning and configuration is recommended to utilize them.

---

## tool-swap notes

### 1. Our exposure is larger than theirs, and the plan says so

llama-swap's concern is the *upstream* container running as root. **D20** ([`13_OPEN_QUESTIONS.md`](../../13_OPEN_QUESTIONS.md)) gives us a strictly worse starting position:

> *"The router runs in a container… The cost — a mounted docker socket, which is root-equivalent — is stated plainly rather than hidden."*

A mounted `/var/run/docker.sock` is host root, whatever user the router process runs as. So we have two separate questions where they have one:

| | Concern | Our current position |
| --- | --- | --- |
| Router container | Docker socket = host root | **D20**, accepted and documented |
| Tool containers | Root inside the container, with GPU device access and mounted weight caches | **Unaddressed.** [`03_TOOL_AUTHORING.md`](../../03_TOOL_AUTHORING.md) §6 and M5 do not specify a `USER` |

The second is the one this page speaks to, and it is a real omission rather than a considered choice.

### 2. The pickle warning is not an LLM-only problem

The linked reference is Hugging Face's own [security-pickle](https://huggingface.co/docs/hub/security-pickle) page. **This applies to us more sharply than to them.** llama-swap loads GGUF files, a format with no code execution path. Our tools call `from_pretrained()` and `torch.load()` against arbitrary Hugging Face repositories (**D11** grants the host network access precisely so they can), and `.bin` checkpoints are pickles that execute on load.

**A tool image that runs as root, mounts the shared HF cache and deserialises a pickle from the internet is the sharpest edge in this design.** It is not hypothetical, it is the default authoring path, and no document in the plan currently mentions it.

Two mitigations are cheap and neither is in the plan:

1. **A non-root `USER` in the generated base image** ([`08_REPO_LAYOUT.md`](../../08_REPO_LAYOUT.md), M5), with the HF cache mounted read-only where the tool does not need to download. llama-swap's caveat applies to us too — *"additional configuration may be necessary to ensure that the container retains access to required host resources"*, which for us means the cache mount and `/dev/nvidia*`.
2. **Prefer `safetensors`** in the authoring guidance. A one-line recommendation in [`03_TOOL_AUTHORING.md`](../../03_TOOL_AUTHORING.md), not a mechanism.

Neither is a v1 blocker. Both are the kind of thing that is nearly free before M5 and awkward after, since changing the base image's `USER` later invalidates every author's assumptions about file ownership.

### 3. What their non-root variant tells us about the cost

They ship non-root as a **separate image tag**, not as the default, and warn that using it needs *"proper planning and configuration"*. That is an honest signal: for GPU workloads with host mounts, unprivileged containers are not free, and a project with thousands of users still made root the default.

**Read as evidence, not as permission.** Their default is root because their users mount arbitrary model directories on personal machines. Ours runs on a **shared DGX** ([`README.md`](../../README.md) §2) where other people's work is on the same host — the same fact that produced **D28**. The blast radius argument that justifies **D2** ([`00_CONTEXT_AND_MOTIVATION.md`](../../00_CONTEXT_AND_MOTIVATION.md) §3) is a *stability* argument; this is the *security* half of it, and the plan currently makes only the first.

### 4. What this does not change

Nothing here bears on **D2**, the router design, or ADR-0001. It is captured because it is the one operational-hardening page in any of the three third-party captures, and because a shared-node deployment makes its subject matter more relevant to us than to its author. Raised as gap **G5** in [`17_LLAMA_SWAP_PHILOSOPHY.md`](../../17_LLAMA_SWAP_PHILOSOPHY.md) §5.
