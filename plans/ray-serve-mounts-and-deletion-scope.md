# Ray Serve — can `image_uri` mount? And what would adoption delete?

> Answers two questions:
> 1. *"Can't we mount on `image_uri`?"*
> 2. *"If we were to use Ray Serve, what would be removed from this plan?"*
>
> **Source for Q1:** [`python/ray/_private/runtime_env/image_uri.py`](https://github.com/ray-project/ray/blob/master/python/ray/_private/runtime_env/image_uri.py) on `ray-project/ray@master`, read directly rather than inferred from docs. This is the code that actually starts the container.

---

## Part 1 — Mounts

### 1.1 First, a caution about the example you pasted

Your snippet has a `<FollowUp>` block in it, so it is chatbot output rather than Ray documentation. That matters twice over:

- **The deployment code is plausible and useful** — see §1.4, it is real evidence for check 1.
- **The mount advice is wrong for our case.** *"Mount your model weights directory onto the underlying cluster nodes (e.g. via Kubernetes volumes)"* answers a **different question**. Mounting onto the *node* does not put the directory inside the *Podman container* that `image_uri` starts. And the parenthetical gives the game away: it assumes Kubernetes, which is where node volumes reach pods. **This is exactly the class of claim this repo has a rule against** — never document a flag or behaviour from memory, and by extension never from a chatbot. Three revisions of [`15_RAY_SERVE_EVALUATION.md`](../plan/15_RAY_SERVE_EVALUATION.md) were caused by not reading the manual.

### 1.2 What the implementation actually does

`ImageURIPlugin` declares its own compatibility set, matching the docs exactly:

```python
@staticmethod
def get_compatible_keys():
    return {"image_uri", "config", "env_vars"}
```

And the container is started with a **fixed, hardcoded** command:

```python
container_command = [
    "podman", "run",
    "-v", ray_tmp_dir + ":" + ray_tmp_dir,
    "--cgroup-manager=cgroupfs",
    "--network=host",
    "--pid=host",
    "--ipc=host",
    "--userns=keep-id",
]
```

**The only bind mount is Ray's own tmp dir**, for IPC. There is no user-facing hook. So: **no, you cannot mount on `image_uri`.** Confirmed in code, not inferred.

### 1.3 The twist: the *deprecated* predecessor could

Look at the two plugins side by side. `_modify_context_impl` takes a `run_options` parameter and splices it into the podman command:

```python
if run_options:
    container_command.extend(run_options)
```

- **`ContainerPlugin`** (the old `container` field) passes `runtime_env.py_container_run_options()` — **arbitrary podman flags, including `-v`.**
- **`ImageURIPlugin`** (the replacement) passes **`[]`**, hardcoded.

So the capability we need exists in the API Ray **deprecated**, and was dropped from its replacement. That is a **capability regression in the migration path**, which sharpens rather than softens the "experimental, already once-deprecated" objection: this API has churned once and lost a feature doing it. The documented remedy is *"If you have a use case for pairing `image_uri` with another runtime environment feature, submit a feature request on Github."*

Depending on `container` instead is not a fix — you would be building **D2**, the most load-bearing decision in the plan, on a deprecated field.

### 1.4 Your example is good evidence for the *other* check

`ray_actor_options={"runtime_env": {"image_uri": ...}}` is consistent with the primary sources: `runtime_env` is a documented `ray_actor_options` key, and `runtime_env` is settable per-actor. So **per-deployment `image_uri` is probably real** — which was check 1, and a yes makes a Ray-native design architecturally neater (one application, many separately-imaged tools, one autoscaling policy over all of them). Still worth confirming by printing the running image inside two replicas, but I'd now expect it to pass.

### 1.5 Three more things that fall out of reading the command

Not previously recorded anywhere, and all three bear on the plan:

| Flag | Consequence |
|---|---|
| `--network=host` | **Every tool shares the host network namespace.** Our **D21** — address tools by container name on a private network, publish no host ports — is not expressible. Tools would contend for host ports, which is the bug class D21 exists to delete. |
| `--ipc=host`, `--pid=host` | Weaker isolation than our `docker run`. Not fatal, but it is *less* isolation than the ✅ in anyone's comparison table implies. |
| `--userns=keep-id` + rootless podman | The documented `/tmp/ray` permission failure mode, plus *"very slow or hanging container startup"* with the default `vfs` storage driver **on large images**. Ours are multi-gigabyte CUDA images. |

### 1.6 The finding that actually matters

**The mount problem and the recovery problem have the same solution, and it is Kubernetes.**

| | Ray on the bare DGX | Ray on Kubernetes (KubeRay) |
|---|---|---|
| Weight-cache / `/data` mounts | ❌ not expressible | ✅ pod volumes |
| Cluster failure | ❌ *"Ray Serve cannot recover"* | ✅ KubeRay recovers |
| Podman on a node we don't administer | required | not required (k8s runs containers) |

So the Ray option collapses into two sub-options, and **both are already-answered questions**:

- **Ray without Kubernetes** — no mounts (§1.2), and cannot recover from cluster failure. Fails on capability, for the first time in four revisions, on a feature our tools demonstrably need: **D18** passes 500 MB CT scans by reference, and a reference to `/data/x.dcm` is meaningless in a container that cannot see `/data`.
- **Ray with Kubernetes** — works, and means adopting Kubernetes on a single shared box. **Which is the thing you and the engineer both already rejected** as too heavy, and which ADR-0001 closed on evidence.

That is a cleaner refusal than anything in [`15_RAY_SERVE_EVALUATION.md`](../plan/15_RAY_SERVE_EVALUATION.md), and it does not depend on the lockstep argument I conceded in [`ray-native-reconsideration.md`](ray-native-reconsideration.md) §1.

**Worth stating the falsifier, per the ADR-0003 lesson:** if `image_uri` gains user-supplied `run_options` (or any mount mechanism) while staying non-deprecated, this refusal is wrong and should be revisited. That is a single GitHub feature request away, so it is worth re-checking rather than assuming.

---

## Part 2 — What Ray Serve adoption would remove from the plan

Scored honestly against [`09_IMPLEMENTATION_PLAN.md`](../plan/09_IMPLEMENTATION_PLAN.md), assuming the mount problem were solved somehow. **This is the useful half of your question, because it holds regardless of how the mount issue resolves.**

### 2.1 Deleted outright

| Milestone / item | Why it goes |
|---|---|
| **M2 — container backend + lifecycle** | Ray owns container start/stop and replica state. `ContainerBackend`, `DockerBackend`, `FakeBackend`, the state machine, boot reconciliation, shutdown ordering. **The single biggest deletion.** |
| **M3.5 — the BentoML spike** | Moot if batching comes from `@serve.batch`. |
| **M3's proxy internals** | `ANY /upstream/{tool}/{path...}`, header hygiene, streaming passthrough — Ray's ingress does this. |
| **M6's TTL watchdog** | `downscale_to_zero_delay_s` **is** our `ttl`, by another name and with a similar default. |
| **M7's log collector** | Ray captures per-replica logs; `serve status` and the dashboard beat what we would build in v1. |
| **`example_echo` integration harness for swap** | Ray's own status surface replaces most of it. |

### 2.2 Shrinks, but does not disappear

| Item | What remains ours |
|---|---|
| **M4 — the runtime** | **Re-targeted, not deleted.** The handler protocol, background loading, truthful `/ready`, schema compilation, the uniform calling convention ([ADR-0005](../plan/adr/0005-one-uniform-batched-calling-convention.md)), the error envelope and result attribution all still have to exist — as a Ray `@serve.deployment` class instead of a BentoML service. And we'd **lose** adaptivity: `@serve.batch` is fixed-window, BentoML's dispatcher is adaptive, which was the reason for **D14**. |
| **M6 — scheduling** | TTL goes; **the eviction policy stays** — `max_resident`, victim ranking by `(evict_cost, last_used)`, `min_residency`, in-flight immunity, thrash detection, and **D28** (a neighbour's VRAM is not our failure). Re-homed as a Ray application-level autoscaling policy, which is an *experimental* API. |
| **M3 — the request path** | `/run/{tool}`, `ensure_ready` coalescing, bounded queueing (**D22**), the error envelope. A thin FastAPI shim on Ray ingress. |
| **M7 — observability** | `/status` and `/ui` shrink; per-tool log retention **after a container stops** still needs checking against Ray's behaviour. |

### 2.3 Untouched — and this is the point

**Every one of these is work we do either way:**

- **M1** — `tools.yaml`, precedence resolution, validation, **the schema compiler** (**D13**)
- **M5** — the authoring ladder, Dockerfile generation, base images, `tswap new/build/test/dev` (**D3**, **R2**)
- **M5.5** — `tswap preflight`, all seven stages (**D17**)
- **M8** — the CLI (**R1**)
- **M9** — `/tools`, `?format=tools`, the agent-callable projection (**D13**), admin endpoints
- **M10** — hardening, docs, migrating real models

### 2.4 And what it adds

- A Ray cluster to operate on a shared DGX, with **six process types** (controller, proxy per node, replica actors, GCS, raylet, dashboard) plus Podman
- **Podman on all head and worker nodes**, `--privileged` if the raylet is containerised
- A `tools.yaml` → Ray Serve config generator (new code, replacing the code we deleted)
- **Three experimental-or-alpha APIs** load-bearing simultaneously: `image_uri`, custom autoscaling policies, the external scaling API
- Every image derived from `rayproject/ray` at the cluster's exact Ray and Python patch version
- ***"Cannot recover"*** without KubeRay
- Driving replica counts at **request** cadence, which the docs discourage

### 2.5 The arithmetic

**Roughly 25–35% of v1's code is deleted.** Real, and worth having. But:

- The **authoring layer, schema/contract, preflight, CLI and the eviction policy itself all survive** — that is the majority of the work and all of the distinctive part.
- Deleted code is replaced by **infrastructure to operate**, and the trade is only good if that infrastructure is boring. Three experimental APIs, Podman on someone else's machine, no mounts, and a documented unrecoverable failure mode is **not boring**.
- **We would still write the scheduler.** [`15 §7`](../plan/15_RAY_SERVE_EVALUATION.md): *"The platform does not remove the interesting work; it relocates it."*

**The honest summary:** Ray deletes the plumbing (~a third) and keeps the contract (~two thirds). That is the same conclusion as [`14 §8.3`](../plan/14_ALTERNATIVES_EVALUATION.md) reached for KServe — *"a substantial part of what we build would be deleted… the plumbing rather than the contract"* — and it is why the framework choice moves less than it feels like it should.

---

## Part 3 — Where this leaves us

1. **The lockstep concession stands.** You were right; [`15 §4.2`](../plan/15_RAY_SERVE_EVALUATION.md) is overstated and must be downgraded from a ground for refusal to a cost. That is the fourth concession this challenge has extracted.
2. **The refusal now rests on something cleaner and better-sourced:** without Kubernetes, `image_uri` cannot mount weight caches or `/data`, and Ray cannot recover from cluster failure. With Kubernetes, both are solved — and we are running Kubernetes on one shared box, which is the option you and the engineer both rejected. **No judgement call about maintainability is needed to reach this.**
3. **The "too heavy" instinct is still right, and still aimed one level off.** v1 is ~4,000 lines; the plan is eighteen documents. Ray would delete about a third of the code and none of the documents. [`16 §2`](../plan/16_COMPLEXITY_AUDIT.md) item 5 already says this.
4. **The unanswered question remains the highest-leverage one**, and it is not about frameworks: *if tool B waited for idle tool A's TTL instead of evicting it, how bad is that in seconds for your traffic?* Preemption is the gate that eliminates KServe, Ray-for-containerised-tools, and BentoML alike. If waiting is tolerable, our scheduler shrinks to a TTL timer and the reuse argument wins outright. **ADR-0004 was produced by re-asking exactly this kind of question, and it was the largest win in this plan's history.**
