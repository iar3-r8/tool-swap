# Architecture Decision Records

Decisions taken **after** the main plan was written, each recording what changed and why. The plan documents are amended in place and link here; this directory is the audit trail.

| ADR | Title | Status | What it changes |
|---|---|---|---|
| [0001](0001-build-our-own-router.md) | Build our own router | Accepted | Closes the M−1 gate and [`13_OPEN_QUESTIONS.md`](../13_OPEN_QUESTIONS.md) Q1. All three de-risking spikes failed, so M2, M3, M6, M7 and M8 are all in scope. |
| [0002](0002-shared-node-soft-unload.md) | Shared DGX, and soft unload moves into v1 | Accepted | Reverses **D9**: soft unload becomes the default reclamation mechanism, hard stop the backstop. Adds **D25** (preemption), **D26** (`unload()` mandatory for GPU tools), **D27** (measure VRAM, never predict) and **D28** (a neighbour's memory usage is not a tool failure). |

## Where the decisions live

**D1–D28 remain in [`13_OPEN_QUESTIONS.md`](../13_OPEN_QUESTIONS.md) Part A**, which is still the single index of what has been decided. These ADRs carry the fuller reasoning for the two that were consequential enough to need it — a gate outcome and a reversal.

When they disagree, the ADR is the record of *why* and Part A is the record of *what*. Neither should be edited without the other.

## Writing the next one

Follow the existing shape: context, decision, evidence, consequences, and an explicit **revisit-if**. Two habits are worth keeping, because both are already load-bearing in 0002:

- **Preserve superseded reasoning rather than deleting it.** D9's original argument was correct given what was known; the premise moved, not the logic. A reader who cannot see that will not trust the next reversal either.
- **State what the decision does *not* license.** D27 permits measuring free VRAM and continues to forbid predicting a model's consumption. Decisions drift at their edges, and the edge is the part worth writing down.
