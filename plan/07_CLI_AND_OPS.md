# 07 — CLI and Operations

> Requirement **R1**: *"it should be simple to lunch the service and to check its logs and status."*
> Decision **D8**: a CLI on top of docker compose.
>
> The acceptance test for this document: **launch, status and logs must each be a single obvious command, and the first-time setup must be three commands.**

---

## 1. First-run experience

```bash
git clone <repo> && cd tool-swap
cp tools.example.yaml tools.yaml
cp .env.example .env            # HF_TOKEN, HF_HOME, TSWAP_TOKEN
tswap up
```

`tswap up` must, in order:
1. Validate the config, printing actionable errors and exiting non-zero on failure (before touching Docker).
2. Create the Docker network if absent.
3. Build any missing base images / model images, or say precisely which `tswap build` command to run.
4. Start the router.
5. Wait for the router's `/health` to report `ok`.
6. Preload `keep_warm` models (in the background; `--wait` to block).
7. Print a summary: the URL, the model count, group occupancy, and the next commands to try.

```
$ tswap up
✓ config tools.yaml valid (7 models, 4 groups)
✓ network tool-swap-net
✓ router healthy at http://localhost:8600
⠿ preloading keep_warm models: text_cleanup ... ready (1.8s)

  7 models registered · 1 resident · GPUs 0-3 available

  tswap status              show all models
  tswap logs -f             follow router logs
  open http://localhost:8600/ui
```

That output is not decoration: showing the next three commands is what makes a tool feel simple, and it costs nothing.

---

## 2. Command reference

### Service lifecycle

| Command | Does |
|---|---|
| `tswap up [-d]` | Start the router (and `keep_warm` models). `-d` detached, the default. |
| `tswap down [--keep-models]` | Stop the router; by default stop all model containers too. |
| `tswap restart` | Restart the router; model containers survive and are re-adopted. |
| `tswap status [model] [--json] [--watch]` | The main operator view. |
| `tswap ps` | Terse: only what is currently running. |

**Config changes are applied with `tswap restart`.** The router re-adopts running tool containers on boot, so a restart costs no cold starts and interrupts nothing that is idle. A no-downtime `tswap reload` with config diffing is deliberately deferred ([`04_API_CONTRACT.md`](04_API_CONTRACT.md) §8) — deciding which keys are hot and which require a rebuild is real complexity for a saving that restart already provides.

### Per-model control

| Command | Does |
|---|---|
| `tswap start <model> [--wait]` | Force start, bypassing `autostart: false`. Also clears `FAILED` and the failure counter, so there is no separate `reset` command. |
| `tswap stop <model> [--force]` | Graceful drain then stop. |
| `tswap stop-all` | The "free the GPUs now" button. A client-side loop over `stop`; there is no `stop-all` endpoint. |
| `tswap unload <model>` | Soft unload: release the weights, keep the container. **v1** — the default reclamation path on our shared node ([ADR-0002](adr/0002-shared-node-soft-unload.md)). The "give the GPU back now, but stay warm" button. |

### Authoring and debugging

| Command | Does |
|---|---|
| `tswap new <name> --template cuda\|cpu\|tensorflow\|function` | Scaffold a working tool directory. |
| `tswap validate [model\|--all]` | Config + handler + schema checks. **No Docker needed** — runs in CI. |
| `tswap build [model\|--all] [--no-cache]` | Build images. Prints the generated Dockerfile path. |
| `tswap test <model>` | Run `tool.yaml`'s `example` through the real container and diff against expectations. |
| **`tswap preflight <tool>`** `[--fast] [--strict] [--json] [--keep] [--stage N]` | **The deployment gate (D17).** Static checks → build → standalone `docker run` → readiness → contract → example → batching and attribution → teardown, ending in one go/no-go verdict and a suggested config snippet (§6.5). **Needs no router and no `tools.yaml` entry.** |
| `tswap dev <model>` | Bind-mount the source, hot-reload on change, stream logs. The inner loop. |
| `tswap run <model> --input k=v [--file k=@path] [--json '{...}']` | One-shot inference from the shell without writing curl. |
| `tswap warm [model\|--all]` | Pre-pull weights / pre-build images outside the request path. |
| `tswap shell <model>` | `docker exec` an interactive shell in the model container. |
| `tswap config show [model]` | Fully-resolved effective config **with the origin of every value**. |
| `tswap doctor` | Environment diagnosis (§6). |
| `tswap prune` | Remove stale images/containers, report reclaimed space. |

### Logs

| Command | Does |
|---|---|
| `tswap logs [-f] [--tail N]` | Router logs. |
| `tswap logs <model> [-f] [--tail N] [--since 10m]` | That model's logs. |
| `tswap logs --all -f` | Interleaved, prefixed and colour-coded by model. |
| `tswap logs <model> --json \| jq` | Structured lines for filtering. |

`tswap logs --all -f` matters more than it looks: when a workflow calls four models in sequence, an interleaved view is the only way to see the actual story. R8's approach — reader threads printing to the parent's stdout, but **only if `verbose`** — meant a model's diagnostics were discarded by default; here logs are always persisted and the user filters.

### Five commands that sound alike — what each is actually for

Authors were going to ask, so answer it in the reference rather than in support:

| Command | Subject | Question it answers |
|---|---|---|
| `tswap validate` | the declaration | Is `tool.yaml` coherent with the handler? (static, CI) |
| `tswap build` | the image | Does it compile? |
| `tswap test` | one happy path | Does the declared example return something? |
| `tswap doctor` | **the host** | Can this machine run tools at all? |
| **`tswap preflight`** | **the tool, end to end** | **Will my tool deploy successfully?** |

`preflight` subsumes the first three, so running it is never wrong — it is simply slower than the individual commands, which is why those remain for iterating ([`03_TOOL_AUTHORING.md`](03_TOOL_AUTHORING.md) §9). `doctor` is the odd one out and stays separate: when preflight fails on a machine with no NVIDIA toolkit, the fix is a `doctor` problem, not a tool problem, and conflating them would blame the author for a broken host.

---

## 3. `tswap status` output

Designed so the answer to "why is my request slow/failing?" is visible without opening a log file.

```
$ tswap status
ROUTER  http://localhost:8600  up 12h04m  config tools.yaml (loaded 12h04m ago)  v0.1.0

GROUPS
  gpu0   1/1  ██  cxr_to_embedding
  gpu1   1/2  █░  eeg_to_embedding
  gpu2   1/1  ██  ct_segmenter
  cpu    1/8  ░░  text_cleanup

MODELS
NAME                   STATE     GROUP  DEV   INFLT  QUEUE  IDLE    TTL IN   REQS  FAIL  P95      COLD
cxr_to_embedding       READY     gpu0   [0]       2      0    3s     9m57s   1841     2   902ms   5 (24.1s avg)
eeg_to_embedding       READY     gpu1   [1]       0      0   41s     4m19s    233     0   1.2s    3 (31.0s avg)
ct_segmenter           READY     gpu2   [2,3]     1      4    0s     29m      9021    1   2.4s    1 (96.2s avg)
text_cleanup           READY     cpu    []        0      0    2m     never   50122    0    12ms   1 (1.8s avg)
ct_to_embedding        STOPPED   gpu0   [0]       -      -   19m     -          12     0     -    2 (28.4s avg)
tb_from_cxr_embedding  STOPPED   cpu    []        -      -    2h     -         840     0     -    1 (0.9s avg)
organ_donor            FAILED    gpu1   [1]       -      -     -     -           0     3     -    0

⚠ organ_donor: readiness timeout after 600s (still LOADING) · retry in 47s · tswap logs organ_donor --tail 50
⚠ gpu0: 14 evictions in the last 10m (cxr_to_embedding ⇄ ct_to_embedding)
   consider: raise groups.gpu0.max_resident, or move one model to another group
```

Details that matter:
- **Group occupancy bars** answer "who is holding GPU 0?" instantly — the most common question on a shared box.
- **`TTL IN`** makes the swap behaviour legible instead of mysterious.
- **`COLD`** (count and average) is the data needed to tune TTL.
- **Warnings with a suggested fix.** Thrash detection ([`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](06_LIFECYCLE_TTL_AND_SCHEDULING.md) §5.3) is nearly impossible for a user to diagnose unaided, so the tool says it out loud and proposes the remedy.
- `--json` for scripting; `--watch` for a live view; `tswap status <model>` for a detailed single-model panel including the last error and recent state transitions.

---

## 4. Logging architecture

```
logs/
├── router.log                    human-readable, rotating
├── router.jsonl                  structured, rotating
└── models/
    ├── cxr_to_embedding.log      container stdout+stderr
    ├── cxr_to_embedding.jsonl    structured lines, if the tool emits them
    └── ct_segmenter.log
```

Rules:
1. **Always persist.** No `verbose` flag gating whether logs are kept.
2. **Rotate** by size with a retention count (defaults: 50 MB × 5). A chatty model must not fill the disk. Note that Docker also keeps its own copy — configure a `log-opts` max-size on our containers too, or the same output is retained twice.
3. **Retain after stop.** A model's logs must survive the container that produced them — otherwise a TTL-stop erases the evidence of the failure you are investigating. This is the single most important logging requirement here.
4. **Correlate.** `request_id` flows client → router → container and appears on every line.
5. **Structured JSON option**, as in R8 (`.jsonl` viewable with `jq` or a log viewer extension). Keep that pattern; it worked.
6. **Startup config dump.** The router logs its effective config at boot; each container logs its resolved knobs. Removes an entire class of "is my setting applied?" questions.
7. **Log the interesting events explicitly** at INFO: state transitions, cold start begin/end with duration, evictions with the victim and the reason, TTL stops, failures with the traceback, config reloads with the diff.

---

## 5. Docker compose relationship

Per **D8**, compose is the substrate — but with a specific division of labour:

- **Compose owns the router only.** `docker-compose.yml` defines the `router` service, the network and the volumes.
- **The router owns model containers**, created via the Docker API/CLI with our labels. They are deliberately *not* compose services, because compose is declarative about what should be running whereas the whole point here is that model containers come and go dynamically.

Consequence: `docker compose up` gives you a working router, and `tswap` is a friendly front end over both. A user who prefers raw compose is not locked out — they can `docker compose up -d router` and use the HTTP API directly. Document this so compose users are not confused by containers that compose does not know about (the labels are how they find them: `docker ps --filter label=com.tool-swap.model`).

```yaml
# docker-compose.yml (sketch)
services:
  router:
    build: { context: ., dockerfile: docker/router.Dockerfile }
    ports: ["${TSWAP_PORT:-8600}:8600"]
    volumes:
      - ./tools.yaml:/app/tools.yaml:ro
      - ./tools:/app/tools:ro
      - ./logs:/app/logs
      - /var/run/docker.sock:/var/run/docker.sock      # to manage sibling containers
      - ${HF_HOME:-~/.cache/huggingface}:/weights/hf
    environment:
      - TSWAP_CONFIG=/app/tools.yaml
      - HF_TOKEN=${HF_TOKEN:-}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8600/health"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 5s
    restart: unless-stopped
networks:
  default: { name: tool-swap-net }
```

**The docker socket mount deserves explicit acknowledgement**: mounting `/var/run/docker.sock` grants the router effective root on the host. Document it plainly, offer running the router directly on the host as an alternative (the backend abstraction supports it), and note rootless Docker / a socket proxy as hardening options. Do not bury this.

Also required: model containers must be started with a mount-propagation-safe view of host paths. If the router is itself containerised, paths in `mounts:` are **host** paths interpreted by the Docker daemon, not paths inside the router container — a classic and confusing trap. State it in the docs and validate what we can.

---

## 6. `tswap doctor`

The pre-flight check that turns a class of support questions into a self-service answer:

```
$ tswap doctor
✓ docker 27.3.1, daemon reachable
✓ docker compose v2.29
✓ nvidia container toolkit present
✓ 4 GPUs visible: 0:A100-40GB(38.1GB free) 1:A100-40GB(40GB free) 2:A100-40GB 3:A100-40GB
✓ network tool-swap-net exists
✓ weights cache /data/hf mounted, 412GB free
✓ config tools.yaml valid (7 models)
⚠ images: 6/7 built · missing: organ_donor  → tswap build organ_donor
⚠ runtime version: 2 images built with runtime 0.1.0, router expects 0.2.0 → tswap build --all
✓ router reachable at http://localhost:8600
```

Checks: Docker present and reachable; compose version; NVIDIA toolkit; GPU inventory with free VRAM; network; cache mounts and free disk; config validity; image presence and staleness; runtime contract-version skew ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §10); port availability; whether host paths in `mounts:` exist.

`doctor` diagnoses the **host**; `preflight` (§6.5) diagnoses a **tool**. Keeping them separate matters: a preflight failure on a machine with no NVIDIA toolkit is a `doctor` problem, and merging the two would blame an author for a broken laptop.

---

## 6.5 `tswap preflight` — the author's deployment gate

Specified in [`03_TOOL_AUTHORING.md`](03_TOOL_AUTHORING.md) §10.1 (**D17**). Reproduced here because operators will meet it too — it is what to ask an author for when their tool misbehaves in the zoo.

### A passing run

```
$ tswap preflight cxr_to_embedding
PREFLIGHT cxr_to_embedding                                    tool-swap 0.1.0

  ✓ 1 static        11 checks · tool.yaml, handler, schema, descriptions
  ✓ 2 build         image tool-swap/cxr_to_embedding:a3f9c1 · 4.2GB · cached (0.8s)
                    dockerfile .tswap/build/cxr_to_embedding/Dockerfile
  ✓ 3 boot          standalone `docker run` · server bound 0.0.0.0:8000 (2.1s)
  ✓ 4 readiness     /health 200 at 2.3s · /ready 503 while loading · 200 at 24.1s
                    cold start 24.1s
  ✓ 5 contract      /schema matches tool.yaml · /info runtime 0.1.0 backend bentoml
                    /health answered during a 5.0s inference
  ✓ 6 example       inputs {paths: /weights/samples/cxr.dcm} → 768 floats
                    output validates against the declared schema (11ms)
  ✓ 7 batching      32 concurrent → 6 handler invocations · all 32 results correct
                    retry_singly isolated the bad item · p95 41ms
  ⚠ 8 resources     skipped: no GPU on this host (run on a GPU host to verify
                    that unload() releases VRAM — required for GPU tools)
  ✓ 9 teardown      SIGTERM drained in 0.3s · exit 0 · no containers left

  VERDICT  READY TO DEPLOY          8 passed · 1 warning · 0 failed        58.4s

  Suggested tools.yaml entry (measured; review before use):

    cxr_to_embedding:
      path: ./tools/cxr_to_embedding
      group: gpu0                 # ← choose; preflight cannot know your layout
      ready_timeout: 90           # cold start 24.1s × 3 margin
      ttl: 600
      resources: { vram_gb: 4 }   # ← unverified, no GPU on this host
      batching: { max_batch_size: 8, max_latency_ms: 25 }
```

### A failing run

Every failure names the check, what was observed, and the fix. This is the difference between a gate people use and one they route around:

```
$ tswap preflight organ_donor
PREFLIGHT organ_donor                                         tool-swap 0.1.0

  ✓ 1 static        11 checks
  ⚠ 2 build         image built (312s) · pip layer rebuilt although only
                    handler.py changed
                    → requirements are copied after the code in your Dockerfile;
                      see .tswap/build/organ_donor/Dockerfile line 14
  ✓ 3 boot          standalone `docker run` · server bound 0.0.0.0:8000 (3.4s)
  ✗ 4 readiness     /ready returned 200 at 0.9s but load() finished at 47.2s
                    → your handler reports ready before the weights are loaded.
                      Move model loading out of __init__ and into load().
                      The router would send requests to a tool that cannot
                      serve them. See 03_TOOL_AUTHORING.md §11.
  ✗ 7 batching      32 concurrent → 32 results, 4 mismatched
                    → predict() returned 29 results for 32 inputs; every result
                      after the gap belongs to the wrong caller. Return exactly
                      one result per input, in input order.
                      THIS IS A PATIENT-SAFETY DEFECT. See 05 §4.4.
  ✓ 9 teardown      SIGTERM drained · no containers left

  VERDICT  NOT DEPLOYABLE           3 passed · 1 warning · 2 failed       371.2s

  Fix the two failures and re-run. To inspect the live container:
    tswap preflight organ_donor --stage 4 --keep && tswap shell organ_donor
```

Requirements on the output:
1. **Every failure carries a remedy**, not just an observation. A check that cannot suggest a fix is a check that will be ignored.
2. **Stages continue after a failure** where it is safe to (stage 7 still ran above), so an author fixes several things per cycle instead of one per 6-minute rebuild.
3. **Teardown always runs**, including after a failure, unless `--keep`. A preflight that leaks containers onto a shared box will be banned by whoever administers it.
4. **`--json` emits the same content** for CI and `/ui` — one report shape, three consumers.

---

## 7. Troubleshooting runbook

Ship this **in the repo README**, not only here — it is the page people will actually read at 2 a.m.

| Symptom | Likely cause | Action |
|---|---|---|
| Request hangs then 503 `TOOL_UNAVAILABLE` (`reason: queue_timeout`) | First-run weight download | `tswap logs <model> -f`; `tswap warm <model>`; raise `ready_timeout` |
| 503 `TOOL_UNAVAILABLE` (`reason: failed`), `last_error: CUDA out of memory` | Device shared with another resident model, or batch too large | Check `tswap status` occupancy; lower `max_batch_size`; move to its own group |
| 503 `TOOL_UNAVAILABLE` (`reason: vram_unavailable`) | **Another tenant on the shared DGX holds the memory.** The tool is fine and stays `IDLE_SOFT` | Nothing to fix in the tool. Retry; `nvidia-smi` shows who holds it. If persistent, `keep_warm: true` on the affected tool, or fewer soft-idle tools competing |
| A tool works but `tswap status` shows VRAM never returning after idle | `unload()` does not genuinely release — common with Keras | `tswap preflight <tool>` stage 8 names it; the tool is classified hard-stop-only and reclaimed by hard TTL instead |
| Everything is slow, GPUs busy but throughput low | Thrashing | The `tswap status` warning names the pair; raise `max_resident` or separate groups |
| Model never leaves `LOADING` | `load()` hung (a download with no timeout, or a lock) | `tswap logs`; `tswap shell <model>` and inspect; add a timeout in the handler |
| Model exits immediately | Bad `TSWAP_HANDLER`, import error | `tswap validate <model>` catches most; then `tswap logs` |
| `tswap build` reinstalls torch every time | Requirements copied after the code, breaking cache layers | Inspect the generated Dockerfile in `.tswap/build/<model>/` |
| Path exists on host, model says not found | Missing mount, or a host-vs-router path confusion (§5) | `tswap config show <model>` and check `mounts` |
| Container starts but the router cannot reach it | Wrong `container_port`, or the server bound to `127.0.0.1` | Bind `0.0.0.0` inside the container |
| Router restarted, models "disappeared" | Reconciliation ran with `orphans: stop` | Expected if the config changed; otherwise check the labels |
| Disk full | Image accumulation | `tswap prune`; consider not baking weights into images |
| Two people fighting over a GPU | No group discipline | Give each their own group, or a shared group with `max_resident: 1` and a documented etiquette |
| A newly-added tool fails in the zoo but "worked on my machine" | It was never preflighted | `tswap preflight <tool>` — ask for the output before debugging the router (§6.5) |
| Tool is `READY` immediately but the first requests fail | Readiness reported at server-up, not weights-loaded | Preflight stage 4 catches this; move loading from `__init__` into `load()` |
| Results look plausible but belong to the wrong patient/input | `predict()` returned a different number of results than inputs | Preflight stage 7. **Stop using the tool.** Return one result per input, in order ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §4.4) |
| Tool works under the router but not under plain `docker run` | Depends on something the router injects | Preflight stage 3 — it is a guardrail violation ([`13_OPEN_QUESTIONS.md`](13_OPEN_QUESTIONS.md) Part D, 11) and breaks portability |
| `preflight` exits 2 | Preflight itself broke — Docker unreachable, pull failed | `tswap doctor`; exit 2 means the host, not the tool |
| `preflight` passes but the tool `FAILED` on the GPU host with OOM | Stage 8 was skipped for lack of a GPU | Re-run preflight on the GPU host; set `resources.vram_gb` from the measured value |

---

## 8. Deployment

Per **D11** the host has network access and can download models and build/pull images, so deployment stays simple:

```bash
# on the GPU host
git clone <repo> && cd tool-swap
cp .env.example .env && $EDITOR .env
cp tools.example.yaml tools.yaml && $EDITOR tools.yaml
tswap doctor                 # verify the host before anything else
tswap build --all            # build every managed image
tswap warm --all             # pre-download weights (do this before users arrive)
tswap up
```

Operational notes:
- **Systemd unit** (provide one in `deploy/`): `ExecStart=/usr/local/bin/tswap up --foreground`, `Restart=always`. Or rely on compose `restart: unless-stopped`. Give both, recommend one.
- **Upgrades**: `git pull && tswap build --all && tswap restart`. Model containers survive a router restart, so a router upgrade is nearly zero-downtime; only images built against an older runtime contract need rebuilding, and `tswap doctor` says which.
- **Backups**: nothing to back up but `tools.yaml`, `.env` and the model directories — deliberately, since there is no database (non-goal). Say this explicitly; it is a feature.
- **Monitoring**: poll `/status` (JSON) and alert on any tool in `FAILED`, on the router's `/health`, and on a rising eviction rate. A Prometheus `/metrics` endpoint is deferred until someone actually runs Prometheus ([`04_API_CONTRACT.md`](04_API_CONTRACT.md) §8); `tswap status --json --watch` covers the interactive case.
- **Multi-user etiquette**: `/ui` plus `tswap status` make GPU ownership visible, which is most of what a shared research box needs.
