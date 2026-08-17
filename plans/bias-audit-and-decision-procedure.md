# Bias audit — am I defending this plan because it is good, or because it is the plan?

> **The challenge:** *"Planning takes time because I have difficulty trusting your judgement. I want to make sure you are not biased into loving your own solution. What if we were to pass S3 paths instead — I think it would solve this issue and we could consider this OK."*
>
> This is the most useful thing raised in the whole exchange, and it deserves a structural answer rather than reassurance. §1 concedes the S3 point. §2 audits my track record against the bias hypothesis and finds **for** it. §3 separates what is documented fact from what is my judgement. §4 proposes a way to decide that **does not route through my judgement at all**, which is the only real answer to "I don't trust you".

---

## 1. The S3 point is conceded, and it was already our own plan

I looked up **D18**'s actual wording instead of paraphrasing it, and it undercuts what I told you:

> *"**The direction of travel is object storage.** Passing paths couples the caller and the container to the same filesystem view, which does not survive a second host and is a recurring source of confusion when a path exists for the caller but was never mounted for the container. Object-storage URIs (S3/MinIO) remove that coupling, and **MinIO is already present in the wider data stack**."*

And:

> *"Adding object storage **changes no client code, no tool schema and no handler**. A caller that passes `s3://bucket/key` where it used to pass `/data/x.dcm` gets the same behaviour."*

**So three of my objections were wrong or overstated:**

| What I said | What D18 actually says |
|---|---|
| *"Object storage stops being optional and becomes required"* — framed as a cost Ray imposes | It is **our own designed destination**. Ray would pull it forward, not invent it. |
| *"The caller contract changes... the most expensive kind"* | D18: *"changes no client code, no tool schema and no handler."* **The design was built for exactly this substitution.** |
| *"a service we operate, on the shared DGX"* | *"MinIO is already present in the wider data stack."* Possibly already running. |

Worse, D18 lists the mount approach's own cost as *"the single most common 'why does my tool say file not found' report"* — **the mount is not the clean option I implicitly treated it as.** Passing S3 URIs is arguably better than our v1 plan, independent of Ray.

**Verdict: you are right. This is acceptable, and it removes the payload half of the objection.** What remains is narrower: weights fetched per cold start (a *quantitative* question we have no numbers for — over loopback to local MinIO it may be seconds, which would make it a non-issue).

---

## 2. The bias audit, and it comes out against me

**My score in this conversation: four challenges, four concessions.**

| # | Your challenge | My response | Was I right first time? |
|---|---|---|---|
| 1 | Python/Ray lockstep isn't fatal | Conceded — overstated | **No** |
| 2 | Can't we mount on `image_uri`? | Held — verified in source, no mount hook | **Yes** |
| 3 | Use the app builder for weights | Partly conceded, retreated to *"unsolved for payloads"* | **Partly** |
| 4 | Pass S3 paths | **Conceded — it was our own plan (§1)** | **No** |

**The pattern is the tell.** Each time an objection fell, I produced a *new* objection rather than updating toward "maybe Ray is viable." That is the signature of motivated reasoning: the conclusion held constant while the reasons rotated underneath it. A genuinely open evaluation would have moved its *conclusion* at least once by now.

**And it is not the first time.** [`plan/15_RAY_SERVE_EVALUATION.md`](../plan/15_RAY_SERVE_EVALUATION.md)'s own version history records the identical pattern *before* I arrived:

> *"**v1** argued Ray could not isolate tools in containers. **Wrong.** **v2** conceded that and retreated to a semantic gap... **v3** stops defending a capability argument that has lost three times."*

**Three revisions before me, four concessions from me — seven consecutive retreats, and the conclusion has never once moved.** That is much stronger evidence about the *process* than about Ray, and I should have weighted it as such rather than treating each round as fresh.

**The mechanism, stated plainly.** I did not write this plan, but that is not exculpatory — I read eighteen documents of accumulated justification before forming a view, and that is the most effective possible way to inherit someone else's conclusion. Every document I read was written by someone defending the same answer. I then went looking for evidence, and **I found real evidence** — the hardcoded `run_options=[]` is a genuine finding, verified in source. But *searching asymmetrically and reporting truthfully still produces a biased result*, because I never once went looking for reasons Ray would work.

**What I should have done and did not:** the moment you said "too heavy," the correct first move was to write the strongest possible case *for* Ray and then attack it. I never did that. Every document I produced in this exchange is structured as a defence.

**One thing worth crediting rather than confessing:** this repo's own conventions caught most of this. The rule against documenting behaviour from memory forced me to source-read `image_uri.py`. The falsifier convention in ADR-0003 is why the lockstep error was catchable. The plan is better at self-correction than I am — which is an argument for its process, not for its conclusion.

---

## 3. Separating fact from judgement

You cannot audit my judgement, but you can audit my facts. So here is the split, honestly drawn.

### 3.1 Documented and verifiable — check these yourself, don't take my word

| Claim | Source |
|---|---|
| `image_uri` passes `run_options=[]`; only `/tmp/ray` is bind-mounted | [`image_uri.py`](https://github.com/ray-project/ray/blob/master/python/ray/_private/runtime_env/image_uri.py) — read it |
| The deprecated `container` field **did** accept arbitrary podman flags | Same file, `ContainerPlugin` |
| Containers get `--network=host --pid=host --ipc=host` | Same file |
| `image_uri` is *"experimental and the API is subject to change"* | Serve + Core docs |
| Ray/Python must match *"down to the patch number"* | Two independent Ray pages |
| *"If you aren't using KubeRay, when the Ray cluster fails, Ray Serve cannot recover"* | Ray's architecture page |
| `@serve.batch` is fixed-window; BentoML's dispatcher is adaptive | Both vendors' docs |
| Podman required on all nodes; `vfs` driver causes *"very slow or hanging container startup"* on large images | Ray's multi-app-container guide |

**None of these depends on trusting me**, and none is fatal on its own. The one I would still weight heavily is *"cannot recover"*, because guardrail 8 says restarting must be cheap and safe.

### 3.2 My judgement — discount freely

- That the operational surface (Podman + 6 process types + 3 experimental APIs) outweighs deleting ~30% of the code. **A judgement call, and I have demonstrated bias on exactly this axis.**
- That per-cold-start weight downloads are expensive. **Unquantified.** Over loopback to local MinIO this may be seconds, i.e. irrelevant. I asserted it without numbers, which is the same error [`plan/15`](../plan/15_RAY_SERVE_EVALUATION.md) made three times with *"Ray is heavy."*
- That `--network=host` breaking **D21** matters. D21 is *our own* choice; a Ray-native design could simply choose differently.

### 3.3 What I now think the honest state of play is

**Ray Serve is more viable than any document in `plan/` admits.** With S3 payloads (§1), the app builder for weights, and per-deployment `image_uri` (probably real), a Ray-native tool-swap is a **real option**, not a refuted one. The remaining objections are a **cost argument plus one documented recovery gap** — not the capability wall four revisions have claimed.

**I am no longer the right judge of whether that trade is worth it.**

---

## 4. A decision procedure that doesn't require trusting me

The real problem isn't Ray. It's that **you have no way to check my reasoning except more of my reasoning.** Three ways out, in increasing cost:

### 4.1 Make me argue the other side (free, fast)

Have me write **the strongest possible case FOR Ray-native tool-swap** — a genuine advocacy document, no hedging, no "but". Then compare it against what I've already written. If the pro-Ray case is visibly thinner or more strawmanned than the anti-Ray case, that asymmetry is your evidence, and it is legible without you adjudicating any technical claim. If it comes out *strong*, you have your answer and it did not come from my judgement.

**This is the cheapest possible check and I recommend it regardless of what else you do.**

### 4.2 Build the spike — compare running code, not documents (days)

The thing no document can settle: **two tools, two images, one GPU, on Ray.** `image_uri` per deployment, an app builder passing an S3 weights URI, `downscale_to_zero_delay_s` as TTL, and an attempt at eviction. Measure cold start, measure the weight fetch, kill the cluster and see what recovers.

This is roughly what retired Spike D was, **and the reasons it was retired no longer hold**: its decisive step tested soft unload (removed by [ADR-0004](../plan/adr/0004-hard-stop-only-in-v1.md)) — but the *architecture* question is live again because of your S3 insight. **I think retiring it was wrong, and I'd reinstate it in narrowed form.**

**Decision rule agreed in advance, so neither of us can move the goalposts after seeing the result:** if two containerised tools alternate on one GPU under Ray with acceptable cold start, and the cluster survives a restart, **Ray wins and most of this repository is deleted.** Write that down before running it.

### 4.3 Get a second opinion that isn't me

The engineer whose analysis started this reached a **different** conclusion from the same requirements — and independently flagged the version lockstep I later had to concede. **That disagreement is a signal, not noise.** Have them review the Ray finding in §3.1 specifically: it is eight checkable facts, and they have no stake in this plan's conclusions.

### 4.4 What I'd also do about the planning cost

*"Planning takes time"* is a symptom with a recorded cause. [`plan/16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md) §2 item 5:

> *"The plan's real risk is not over-engineering, it is **over-documentation**. Seventeen planning documents, five ADRs and ~29 decisions for a service whose v1 is perhaps 4,000 lines."*

Eighteen documents is also **why this is hard to audit** — the volume is itself an obstacle to the trust you're asking for, and it makes any conclusion in it look better-supported than it is. Whatever we decide about Ray, cutting that corpus hard is a win.

---

## 5. Bottom line

1. **You were right about S3, and it was our own plan** (§1). The payload objection is withdrawn.
2. **You were right to distrust my judgement.** Four concessions, four new objections, conclusion never moved — plus three identical revisions before me. §2 is the evidence, and it favours your hypothesis.
3. **Ray Serve is a live option**, and the documents in `plan/` overstate the case against it. What survives is a cost trade plus one documented recovery gap (§3.1), not a capability wall.
4. **The one question that is still genuinely unpriced is not about frameworks:** whether a request may *wait* for an idle tool's TTL instead of evicting it. It is the gate that eliminates every candidate, it rests on one sentence, and if waiting is tolerable then the scheduler shrinks to a timer and reuse wins outright. **I keep asking because it decides more than the framework choice does** — but note that I also have a bias here, since "preemption is required" is what justifies the custom router.
5. **Start with §4.1.** It costs one document, it tests me rather than Ray, and you don't have to trust anybody to read the result.
