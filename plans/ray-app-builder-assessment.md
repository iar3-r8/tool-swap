# Does the app builder solve the weights problem?

> **Question:** *"For passing the weights etc, why not use the [application builder](https://docs.ray.io/en/latest/serve/advanced-guides/app-builder-guide.html)?"*
> **Source:** page read in full at Ray 2.57.0. Quotes below are verbatim.
>
> **Short answer:** it solves **half** the problem, and it is a genuinely good find for a *different* reason than mounting. But it does not mount anything, and the half it leaves untouched is the half that costs us a new service to operate.

---

## 1. What the page actually provides

An **application builder** is a function taking an args dict (or a Pydantic model) and returning a built `Application`. Args come from `serve run key=val` or from the config file's `args:` field. Ray's own motivating example is exactly our use case:

> *"For example, you might have a path to trained model weights and want to test out a newly trained model."*

And the multi-model pattern is precisely the shape a generated config would take:

```yaml
applications:
  - name: Model1
    import_path: my_module:my_model_code
    args:
      model_uri: s3://my_bucket/model_1
  - name: Model2
    import_path: my_module:my_model_code
    args:
      model_uri: s3://my_bucket/model_2
```

**Credit where due: this is the mechanism a `tools.yaml` → Ray config generator would use**, and it maps cleanly onto our design. One builder, N tools, per-tool args — that is `defaults` plus per-tool overrides, in Ray's vocabulary. If we ever went Ray-native, this page is how the config layer would work, and it is a better fit than I had assumed.

## 2. But it is not a mount, and it changes the architecture rather than the plumbing

**It passes strings.** Look at what the string is in Ray's own example: `s3://my_bucket/model_1`. The pattern is **fetch from object storage inside `__init__`**, not bind-mount a host directory. Which is consistent with §1.2 of [`ray-serve-mounts-and-deletion-scope.md`](ray-serve-mounts-and-deletion-scope.md) — there is no mount hook, so the docs route you around the missing feature.

So the answer to *"can we pass weights this way?"* is **yes, by replacing the mount with a download.** That is a real option, and it has real costs:

| | Mount (our plan) | Fetch-by-URI (app builder) |
|---|---|---|
| First cold start | Read from a shared local cache | Download N GB |
| **Every subsequent cold start** | Read from the same cache | **Download N GB again** — the container filesystem is per-replica and ephemeral |
| Shared across tools | One HF cache for the whole zoo | Each tool fetches its own copy |
| Prerequisite | A directory | **An object store to run and populate** (MinIO/S3), or a reachable HTTP source |

The recurring-download row is the problem, because [ADR-0004](../plan/adr/0004-hard-stop-only-in-v1.md) made **cold start the price of every displacement**. We accepted 5–18 s of container start plus weight load. Adding a multi-gigabyte download to that path changes the arithmetic of the whole eviction design — and it would likely re-promote soft unload (ADR-0004's trigger 1: *cold starts exceeding ~20% of request time*) to defend against a cost we introduced ourselves.

**Mitigations exist** — bake weights into the image (image size × weights, rebuild on weight change), or use `--network=host` reachability to hit a local MinIO over loopback (fast, but still a copy per cold start and a service to operate). Neither is free, and note the second one is only fast *because* of the `--network=host` flag that breaks **D21**.

## 3. The half it does not touch at all: request payloads (D18)

This is the load-bearing distinction, and it is why the app builder does not close the question.

| | Weights | Request payloads |
|---|---|---|
| When | **Startup**, once per replica | **Per request** |
| Known at config time? | Yes — a builder arg works | **No** — it is whatever the caller sends |
| Our design | mounted cache | **D18**: passed **by reference** because a CT scan is 500 MB |

App builder args are **startup configuration**. They cannot carry a per-request payload reference. So **D18 is entirely unaddressed**: R8's tools today take *"Path STRING to a DICOM chest X-ray image"* — a host filesystem path — and in an `image_uri` container with no mount, `/data/x.dcm` does not exist.

**The consequences are architectural, not incidental:**

1. **Object storage stops being optional and becomes required.** [`plan/09_IMPLEMENTATION_PLAN.md`](../plan/09_IMPLEMENTATION_PLAN.md) M3 says v1's resolver *"accepts a filesystem path and returns it unchanged; the seam is what makes object storage additive later."* Under Ray, that seam has to be filled **in v1** — MinIO or equivalent becomes a service we operate, on the shared DGX.
2. **The caller contract changes.** Every consumer — including R8's workflow demo — must upload to object storage and pass a URI, instead of passing a path to a file already on the box. That is a change to somebody else's code, which is the most expensive kind.
3. **Or inline the bytes over HTTP**, which is what **D18** exists to avoid: 500 MB in a JSON body, base64-inflated by a third.

## 4. Two incidental findings from the page

- **`import_path` resolution is unverified and matters.** The logs show *"Building application 'MyApp'"* emitted by `ServeController`, which suggests the builder function executes in the **controller's** environment rather than inside the tool's container image. If so, each tool's builder module must be importable *outside* its own image — which would partially defeat the point of per-tool isolation, or at least require our generated builder to be generic and shared. **Flagging as unverified rather than asserting it**; it would need checking before any Ray-native design was drawn.
- **Churn, again:** *"Pydantic v1 is deprecated and Ray will drop support for it in version 2.56."* A third data point, alongside `container` → `image_uri`, on how fast this surface moves.

## 5. Where this leaves the Ray option

**The app builder narrows the gap and does not close it.** Revised scorecard for weights and data on the bare DGX:

| Need | With app builder |
|---|---|
| Model weights | ⚠️ **workable**, by replacing a mount with a per-cold-start download plus an object store |
| Request payloads (**D18**) | ❌ **unsolved** — requires object storage in v1 and a change to every caller |
| `--network=host` vs **D21** | ❌ unchanged |
| Recovery without KubeRay | ❌ unchanged — *"Ray Serve cannot recover"* |

So the refusal stands, but **the honest reason has shifted once more** — and this is the fourth time this challenge has moved the argument, which is worth noting rather than hiding:

> **Not** *"Ray cannot see our data"* — it is *"Ray requires us to adopt object storage in v1, change the caller contract, and pay a download on every cold start, in exchange for deleting about a third of our code."*

That is a **cost argument**, not a capability one. It is weaker than what I wrote yesterday, and you should weigh it as such. It is also still, in my judgement, the wrong trade — because the download lands on the exact path [ADR-0004](../plan/adr/0004-hard-stop-only-in-v1.md) already identified as our dominant cost, and because it pulls a phase-2 item (object storage) into v1 while pushing a change onto R8's callers.

**And the falsifier is unchanged and cheap to watch:** if `image_uri` gains user-supplied `run_options` — one GitHub feature request, and the deprecated `container` field already had it — the mount objection evaporates and this whole thread should be re-run. That is worth a calendar reminder rather than a closed door.

## 6. What I would still rather you answered

Everything above is a debate about how to make **preemption of containerised tools** work in a framework that puts displacement inside the replica. It is downstream of one requirement, and that requirement rests on one sentence (**D25**).

> *If a request for tool B arrived while idle tool A held the GPU, and B waited for A's TTL to expire instead of evicting it — how bad is that in seconds for your real traffic?*

If *"wait"* is acceptable with a short `ttl` on contended tools, then **`downscale_to_zero_delay_s` is our whole scheduler**, the eviction policy is deleted rather than re-homed, and Ray becomes a much stronger candidate than any of these documents allow — because the argument would no longer hinge on displacing containers at all. [ADR-0004](../plan/adr/0004-hard-stop-only-in-v1.md) came from re-asking exactly this kind of question, and it was the largest simplification in this plan's history.
