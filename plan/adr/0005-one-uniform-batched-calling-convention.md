# ADR-0005 — One uniform calling convention: every handler takes and returns a list

- **Status:** Accepted
- **Date:** 2026-08-13
- **Amends:** **D15** (changes its meaning, not merely its wording). Narrows the `native`-backend justification in **D14**.
- **Affects:** [`05_RUNTIME_AND_BATCHING.md`](../05_RUNTIME_AND_BATCHING.md) §4.3–§4.4, [`03_TOOL_AUTHORING.md`](../03_TOOL_AUTHORING.md), [`02_CONFIGURATION.md`](../02_CONFIGURATION.md) §7, [`04_API_CONTRACT.md`](../04_API_CONTRACT.md) §9, [`09_IMPLEMENTATION_PLAN.md`](../09_IMPLEMENTATION_PLAN.md) M3.5/M4
- **Does not affect:** **D5** (batching is in scope), **D14** (BentoML is the engine), **D19** (descriptions stay mandatory), or the batch-length safety check, which becomes *more* load-bearing rather than less.
- **Evidence class:** one vendor documentation page, read directly, plus a structural simplicity argument. **One factual premise is unverified and flagged as such in §5** — M3.5 must settle it before M4 builds on this.

---

## Context

**D15** forbade a batched tool from declaring any per-request non-batchable input, and pushed per-request knobs into **static params fixed at load time**. The reasoning was sound and the hazard is real: BentoML's dispatcher cannot separate a batch by differing arguments, so two requests with `threshold=0.5` and `threshold=0.9` would be batched and one silently answered with the other's value — *"no exception, no log line, and a plausible-looking wrong number returned about a patient."*

The constraint behind it is confirmed by the vendor: *"A batchable API endpoint only accepts one parameter in addition to `bentoml.Context`."*

**What D15 did not know is that BentoML documents a second remedy**, and its example is literally ours — `image: Path` plus `threshold: float`. Group the parameters into a Pydantic model and make *that* the batched element; each item then carries its own `threshold`, and the handler applies each item's parameters to that item ([`adaptive-batching.md`](../third-party-docs/bentoml/adaptive-batching.md) §"Handle multiple parameters").

That reopened D15, which had been correct for one class of parameter and over-broad for another:

| Kind of parameter | Genuinely must be fixed? |
|---|---|
| Post-processing knobs — `threshold`, top-k, NMS IoU, output format | **No.** Applied per item after the batched forward pass |
| Parameters changing the batched computation — input resolution, dtype, a different model head, sliding-window size | **Yes.** These cannot vary within one batched call |

The obvious move was to narrow D15 to the second row. **The requester rejected that in favour of something simpler:**

> *"We need to keep the most consistent and simple API, if its simpler to have everything 'batched' then lets make it batched. We strive for simplicity here."*

## Decision

### 1. Every handler receives a list of typed items and returns a list of the same length. Always.

There is **one** calling convention, for every tool, batched or not:

```python
def predict(self, items: list[Input]) -> list[Output]:
    # len(result) == len(items), same order. Always.
```

`scalar_inputs: true` is **removed**. [`05 §4.4`](../05_RUNTIME_AND_BATCHING.md:242) already made lists-of-1 the default so that *"authors write one code path"*, then reintroduced a second path as an opt-out. This finishes that thought and deletes the exception.

### 2. `batching.enabled: false` means `max_batch_size: 1`, and nothing else

It stops being a switch between two calling conventions and becomes a performance setting. A CPU tool that never benefits from batching is written exactly like a GPU tool that does — the handler cannot tell, and does not need to.

### 3. Per-request knobs are fields of the item, so they are per-item by construction

`threshold` is declared in `inputs:` like any other field. The dispatcher batches a list of items each carrying its own value, and the handler applies item `i`'s parameters to item `i`.

**The D15 hazard cannot arise** — not because we detect it, but because there is no longer a way to express a per-request value that is shared across a batch. That is the same "make the state unrepresentable" instinct D15 had; this ADR relocates it to a place that costs the author nothing.

### 4. `params:` survives, narrowed to what it was always for

Static params remain, for values that are genuinely **per-deployment** and change the batched computation itself: a model head, an input resolution, a weights path, a dtype. These are part of the tool's identity, are passed to `load()`, and do not appear in the request schema.

**The test for `params:` versus `inputs:`** is now a real question with a real answer, rather than a workaround for a framework limitation: *does this value change what the batched forward pass computes?* If yes, `params:`. If it only shapes that item's own result, `inputs:`.

### 5. ⚠️ One premise is unverified, and M3.5 must settle it

The proposal that produced this ADR claimed the per-item pattern costs a **two-Service topology** via `bentoml.depends`, since that is what the vendor's example shows.

**On re-reading, that is probably wrong.** The wrapper Service in BentoML's example exists to expose a *non-list, multi-parameter* API to clients — `generate(image, threshold)` — and to fan single calls into the batchable one. **Our `/predict` contract is ours**, and our clients already post an item (or a list of them); the dispatcher concatenates the lists arriving from separate HTTP requests. So a wrapper may be unnecessary.

**This is the falsifier for the "simplicity" claim, and it is not yet checked.** If a wrapper Service *is* required, this ADR still holds — the adapter generates it and `handler.py` never sees it — but the runtime gains an extra hop, and that cost should be recorded rather than discovered. **M3.5 step 5 must establish which it is before M4 builds on it.**

## What this removes

| Artefact | Status |
|---|---|
| `scalar_inputs: true` | **Removed.** One convention, no opt-out |
| Two meanings for `batching.enabled: false` | **Removed.** It is now only `max_batch_size: 1` |
| The `tswap validate` hard error for a non-batchable input on a batched tool (D15's rule) | **Removed.** The state is unrepresentable, so there is nothing to detect |
| The `batchable: true` flag per input | **Removed** from the authoring surface. Every input is an item field; batching is a property of the *tool*, not of individual inputs |
| Two `/schema` and `?format=tools` shapes depending on batching | **Removed.** One shape |
| "Use the `native` backend for per-request knobs" ([`05 §4.3`](../05_RUNTIME_AND_BATCHING.md:227)) | **Withdrawn as a justification.** It was *"the first real use case for the D14 seam"*; that use case has evaporated. The seam still stands on dependency risk alone — see *What this does not license* |

**Net: the authoring surface loses two concepts and gains none.** That is the whole case for this ADR.

## What this costs

1. **A tool that would prefer a scalar signature must still accept a list of one.** Trivial, and it was already the default.
2. **The batch-length check becomes more load-bearing, not less.** With every tool on the batched path, an off-by-one in a handler now has the same consequence everywhere. [`16_COMPLEXITY_AUDIT.md`](../16_COMPLEXITY_AUDIT.md) §5 names batch attribution as never-trim; this ADR **raises** its importance and must not be read as reducing it.
3. **The per-item cost is unverified** — §5. Possibly zero, possibly one extra in-process hop.
4. **`x-batchable` in the compiled schema loses its per-input meaning.** [`04 §9`](../04_API_CONTRACT.md) and the M1 schema compiler need reworking, and the M9 test asserting *"a list on a non-batchable port is a 422"* is deleted rather than rewritten — there are no non-batchable ports.

## What this does not license

- **It does not weaken the batch-length check or `retry_singly`.** See cost 2. If anything here is ever cited to justify trimming batch attribution, the citation is wrong.
- **It does not remove `params:`.** Parameters that change the batched computation genuinely cannot vary within a batch, and the vendor's remedy does not change that.
- **It does not remove the `RuntimeBackend` seam.** The seam's *stated* first use case is withdrawn, but its original justification — a tool that cannot resolve BentoML's dependencies (**D14** §1.2) — is untouched, and it is the one M3.5 was already testing.
- **It does not make batching mandatory at runtime.** `max_batch_size: 1` is a valid and common configuration.

## Revisit if

| Trigger | What it would mean |
|---|---|
| M3.5 finds the per-item pattern **needs a wrapper Service and the extra hop is measurable** | Re-price this ADR. The simplicity argument survives; the "costs nothing" claim does not |
| A tool needs a per-request parameter that changes the batched computation | It goes in `params:` and becomes two config entries — **this is the designed answer**, not a failure |
| BentoML changes the single-argument rule for batchable APIs | The constraint that motivated D15 disappears entirely; this ADR becomes unnecessary rather than wrong |

## Notes

**The requester's answer was better than either option offered**, and the reason is worth recording. I proposed narrowing D15 to the row where the restriction is genuine — which would have left **two** classes of parameter, **two** rules for choosing between them, and an authoring surface that needs a paragraph to explain. The instruction *"if it's simpler to have everything batched then let's make it batched"* removes the distinction instead of refining it.

**The generalisable form:** when a decision splits a surface into two cases, check whether the cheaper move is to collapse the surface rather than to draw the line more accurately. [`16_COMPLEXITY_AUDIT.md`](../16_COMPLEXITY_AUDIT.md) §3 already scores **D4b** (*"exactly one kind of tool"*) as a *"model example of the right instinct"* with *"negative cost"* — this is the same instinct applied to the calling convention, and the two now agree: **one kind of tool, one way to call it.**
