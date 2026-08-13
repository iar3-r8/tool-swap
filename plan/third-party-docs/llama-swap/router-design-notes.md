# llama-swap — router rewrite notes (`docs/newrouter-todo.md`)

**Source URL:** https://github.com/mostlygeek/llama-swap/blob/main/docs/newrouter-todo.md
**Upstream version at capture:** **v249** (latest release, published 2026-08-10); file read from `main`
**Captured:** 2026-08-13
**Relevance to tool-swap:** this is llama-swap **rewriting its own router**, in public, after four years and 249 releases. It is the only document in any of our three captures that shows what a mature version of *our* component looks like from the inside — the decomposition it settles on, the concerns it found were tangled, and the seven gaps a careful review still missed. It is design input for [`01_ARCHITECTURE.md`](../../01_ARCHITECTURE.md) and M2/M6, not a decision-bearing reference.
**Completeness:** ⚠️ **CONDENSED EXCERPT.** Phase headings, the architectural rationale, the gap findings and the cross-cutting concerns are verbatim; per-phase implementation detail naming their internal Go symbols is summarised, and repository-internal links are flattened to plain text. Fetch the source for the full text.

> **This is an internal working document, not published documentation.** It describes work in progress on `main` (Phase X, "Cutover", is still open). Treat it as a design diary — informative about their reasoning, not authoritative about released behaviour.

---

## What the document is

> *"This document tracks the work needed for `cmd/newrouter/main.go` and `internal/router/` to reach feature parity with the legacy entrypoint at `llama-swap.go` plus `proxy/proxymanager.go`. The work is split into phases so each can land and be tested independently. Earlier phases unblock later ones."*

Ten phases. Phases 1–8 are marked **Completed**; Phase X (cutover) is open.

## The problem they are solving

> *"The legacy `ProxyManager` collapses three concerns into one struct: the HTTP mux, the model→process router, and the cross-cutting services (loggers, metrics, perf, inflight counter, version). The new layout keeps the `router.Router` implementations focused on model dispatch and lets `internal/server.Server` own the mux and all cross-cutting middleware."*

The resulting decomposition:

| Their component | Responsibility |
| --- | --- |
| `internal/router` (`Router` interface) | **Model dispatch only** — which upstream serves this model, and swapping to make it so |
| `router.LocalRouter` | `Router` plus `RunningModels()` and `Unload(timeout, models...)` |
| `router.Group` / `router.Matrix` | Two `Router` implementations — static groups, and the solver |
| `router.Peer` | A `Router` that forwards to a remote llama-swap |
| `internal/server` | The mux, lifecycle, custom endpoints, filters, auth/CORS, upstream passthrough, logging, metrics, SSE, UI |
| `internal/chain` | Middleware composition — *"`chain.New(mws...).Then(final)`… `Append` returns an extended Chain without mutating the receiver"* |
| `internal/process` | One upstream process; emits `ProcessStateChangeEvent` from `setState` |

## Phase list, abridged

| Phase | Goal (their words, abridged) | Status |
| --- | --- | --- |
| 1 | *"move shared infrastructure packages out from under `proxy/` so the new router does not depend on the legacy proxy tree"* | Completed |
| 2 | *"make `cmd/newrouter` a drop-in replacement for the legacy binary's process model, without yet adding any extra HTTP endpoints"* | Completed |
| 3 | `internal/chain` — middleware composition | Completed |
| 4a–4e | `internal/server` scaffolding: mux and model routes; custom endpoints; request-body filters; auth & CORS; upstream passthrough | Completed |
| 5 | Operations endpoints — `/unload`, `/running`, preload hook | Completed |
| 6, 6f | Metrics, perf monitor, SSE event stream, request/response captures | Completed |
| 7 | Embedded UI serving | Completed |
| 8a–8c | Two review passes against the legacy implementation | Completed |
| X | Cutover: retire the legacy entrypoint, drop `gin-gonic` | **Open** |

Notable phase details:

- **Phase 5** — *"A new `router.LocalRouter` interface embeds `Router` and adds `RunningModels()` and `Unload(timeout, models...)`, both implemented once on `baseRouter` so `Group` and `Matrix` share them — the legacy matrix/group divergence collapses since `baseRouter` already unifies process storage. `Peer` does not implement it."*
- **Phase 5** — *"`startPreload` fires a background `GET /` at each `Hooks.OnStartup.Preload` model"*. Preloading is implemented as **a synthetic request**, not a separate code path.
- **Phase 6** — process state changes are published as events (`ProcessStateChangeEvent`), consumed by an SSE endpoint (`GET /api/events`: `modelStatus` / `logData` / `metrics` / `inflight`).
- **Phase 4e** — upstream passthrough does *"multi-segment name resolution, canonical-form redirect (301/308), and prefix stripping"*.

## The seven gaps found by review

Phases 8a and 8c were review passes comparing the new implementation against the old. They found seven defects **after** all functional phases were marked complete:

| Gap | Description (their words, abridged) | Status |
| --- | --- | --- |
| 1 | *"Request logging middleware missing"* — one access-log line per request | Resolved |
| 2 | *"Per-model log streaming not supported"* — `getLogger` handled only `""`, `"proxy"`, `"upstream"`; *"Callers of `GET /logs/stream/<model>` will get a 400 instead of the model's live log stream"* | Resolved |
| 3 | *"`UseModelName` not applied to multipart form endpoints"* — the JSON filter path had it; the multipart path did not | Resolved |
| 4 | *"`LogToStdout` config ignored"* — *"hardcoded `proxyLog`/`upstreamLog` to `os.Stdout`, and the old `muxlog()` helper built a Monitor that nothing wrote into — so `logToStdout` had no effect and `/logs` (combined history) was always empty"* | Resolved |
| 5 | *"`LogTimeFormat` config ignored"* | Resolved |
| 6 | *"`LogRequests` deprecation warning missing"* | **Left open**, low priority |
| 7 | *"PID debug log missing"* | Resolved |

Also recorded: a list of functions at **0% test coverage** after the rewrite, and a numeric gate — *"Test coverage at or exceeds the level from the proxy package — `internal/server` now at 76.6% vs 73.9%"*.

## Cross-cutting concerns (verbatim, abridged)

> - **Single body read**: legacy and newrouter both buffer the request body once. When adding filters, make sure the buffered bytes flow through `Content-Length` / `transfer-encoding` cleanup.
> - **Streaming flag in context**: legacy stashes `streaming` and `model` under `proxyCtxKey`. The new router uses `ModelKey` / `ModelIDKey` — pick one set of keys and use them consistently for metrics + log handlers.
> - **Matrix vs Group divergence**: any handler that calls `swapProcessGroup` or `findGroupByModelName` in the legacy needs a matrix branch too. The new router's `Router` interface already abstracts this — **preserve that abstraction rather than reintroducing the branch in every handler**.
> - **Shutdown ordering**: `httpServer.Shutdown` must drain inflight requests *before* `Server.Shutdown` tears down processes, otherwise inflight requests 502.

---

## tool-swap notes

### 1. Their decomposition is ours, arrived at independently

Strip the Go and the OpenAI specifics and their target architecture is [`01_ARCHITECTURE.md`](../../01_ARCHITECTURE.md):

| llama-swap (after rewrite) | tool-swap |
| --- | --- |
| `internal/server.Server` — mux, middleware, cross-cutting services | Router: FastAPI app, proxy, `/status`, `/ui` |
| `router.Router` — *"focused on model dispatch"* | Scheduler — `request_slot`, groups, devices |
| `router.Group` / `router.Matrix` behind one interface | Our scheduling policy, currently one implementation |
| `internal/process` — one upstream, emits state-change events | `ContainerBackend` + the tool state machine |
| `router.Peer` | *(none — see [`config-schema.md`](config-schema.md) §7)* |

**This is convergent evidence for the seam we already drew.** The strongest form of it is their own warning: *"preserve that abstraction rather than reintroducing the branch in every handler."* They are describing what happens when a scheduling policy leaks into request handlers — the exact failure that guardrail on scheduler purity ([`16_COMPLEXITY_AUDIT.md`](../../16_COMPLEXITY_AUDIT.md), never-trim item 2) exists to prevent. **We have the warning before writing the code; they got it after writing it twice.**

### 2. What the gap list is actually evidence of

Read the seven gaps as a group and a pattern falls out. **Five of the seven are logging and observability** (1, 2, 4, 5, 7), and gap 4 is the sharpest: a config key silently doing nothing, and `/logs` *"always empty"*, in a completed, reviewed, tested rewrite.

Two consequences for us:

- **Observability regressions are invisible to functional tests.** Nothing 500s when logs go missing. [`10_TESTING_STRATEGY.md`](../../10_TESTING_STRATEGY.md) should assert that `tswap logs {tool}` returns the tool's lines and that `logToStdout`-equivalent settings take effect — **R1** is *"simple to launch and to check its logs and status"*, so a silent logging failure is a requirement failure, not a cosmetic one.
- **Gap 2 is a warning about our own log routing.** Per-model log streaming was the thing most easily lost, because it needs the request handler to resolve a *model ID* against *live process state*. Our `tswap logs {tool} -f` (**D8**) needs the same resolution against container state, and [`07_CLI_AND_OPS.md`](../../07_CLI_AND_OPS.md) should say what it does for a tool that is `STOPPED` — theirs returned 400.

Gap 3 is worth its own line: **a behaviour applied on the JSON path and forgotten on the multipart path**. Our analogue is any per-request transformation that must apply identically to `/run/{tool}` and to `/upstream/{tool}/...`. **D18**'s reference resolution is exactly such a transformation.

### 3. Preload as a synthetic request

> *"`startPreload` fires a background `GET /` at each `Hooks.OnStartup.Preload` model"*

`keep_warm` in our config is the same feature, and this is the cheapest possible implementation: **no separate warm-up path, just a request through the ordinary machinery**. Everything the normal path does — slot acquisition, readiness polling, state transitions, failure accounting — happens for free and cannot drift.

This is the same argument **D24** makes in refusing `tswap exec`: *"A separate one-shot command would be a second code path that drifts from the real request path and then reassures about behaviour it no longer shares."* Worth stating explicitly in M6 that preload issues a real request rather than calling the scheduler directly.

### 4. Shutdown ordering, which we have not specified

> *"`httpServer.Shutdown` must drain inflight requests before `Server.Shutdown` tears down processes, otherwise inflight requests 502."*

[`01_ARCHITECTURE.md`](../../01_ARCHITECTURE.md) and [`07_CLI_AND_OPS.md`](../../07_CLI_AND_OPS.md) describe `tswap down` but do not fix this ordering. Ours is strictly harder than theirs: a request may be **queued behind a cold start** (**D22**) rather than merely in flight, so "drain" has two meanings — let running requests finish, and decide what happens to requests waiting for a container that we are about to stop.

Not a gap in the design so much as an unwritten paragraph. Cheap to specify now, and a source of flaky integration tests if left to implementation.

### 5. Their `Router` interface has three implementations; ours has one

`Group`, `Matrix` and `Peer` all satisfy one interface, and Phase 5's `LocalRouter` split is precisely the seam that lets `Peer` opt out of `RunningModels()`/`Unload()` — a remote router cannot enumerate or stop what it does not own.

We have one scheduling policy and no remote case, so a second implementation would be speculative. **But the interface shape is worth copying even with one implementation**, because it is what makes `Peer` addable later without touching handlers ([`config-schema.md`](config-schema.md) §7 notes federation as an unpriced alternative to Kubernetes). That is the same reasoning as our `ContainerBackend` and `RuntimeBackend` seams: *"a future `KubernetesBackend` is a new implementation, not a rewrite"* ([`14_ALTERNATIVES_EVALUATION.md`](../../14_ALTERNATIVES_EVALUATION.md) §7).

### 6. The honest caveat about this capture

This is a working document on a moving branch. Phase X is open, so **the legacy `proxy/proxymanager.go` is still the shipping code path at v249** — the architecture described here is where they are going, not what our users run today. Nothing in the plan should cite it as a description of llama-swap's released behaviour. Cite it, if at all, as *"llama-swap's own router rewrite notes describe…"*.
