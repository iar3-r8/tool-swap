# llama-swap — project README

**Source URL:** https://github.com/mostlygeek/llama-swap (`README.md` on `main`)
**Upstream version at capture:** **v249** (latest release, published 2026-08-10); README read from `main`, which is at or ahead of that tag
**Captured:** 2026-08-13
**Relevance to tool-swap:** llama-swap is the acknowledged inspiration for this project (**D1**) and the source of its swap semantics (**D4**). [`00_CONTEXT_AND_MOTIVATION.md`](../../00_CONTEXT_AND_MOTIVATION.md) §4 instructs *"Read its README before designing the config"*, and until now no copy of it existed in the plan. It is also the **sibling service** that serves our LLMs ([`04_API_CONTRACT.md`](../../04_API_CONTRACT.md) §0).
**Completeness:** **verbatim**, with image markup and shields.io badges stripped and the collapsed `<details>` block on Docker tags inlined. No prose or code has been altered.

> **Read from `main`, not from the `v249` tag.** As with [`bentoml/health-endpoints-and-lifecycle-source.md`](../bentoml/health-endpoints-and-lifecycle-source.md), content read from a moving branch may be ahead of the released version. Re-verify against the pinned tag before relying on any specific behaviour.

---

# llama-swap

Run multiple generative AI models on your machine and hot-swap between them on demand. llama-swap works with any OpenAI and Anthropic API compatible server and is used by thousands of people to power their local AI workflows.

Built in Go for performance and simplicity, llama-swap has zero dependencies and is incredibly easy to set up. Get started in minutes - just one binary and one configuration file.

## Features:

- ✅ Easy to deploy and configure: one binary, one configuration file. no external dependencies
- ✅ On-demand model switching
- ✅ Use any local OpenAI compatible server (llama.cpp, vllm, tabbyAPI, stable-diffusion.cpp, etc.)
  - future proof, upgrade your inference servers at any time.
- ✅ OpenAI API supported endpoints:
  - `v1/completions`
  - `v1/chat/completions`
  - `v1/responses`
  - `v1/embeddings`
  - `v1/models` - list available models
  - `v1/audio/speech` (#36)
  - `v1/audio/transcriptions` (docs)
  - `v1/audio/voices`
  - `v1/images/generations`
  - `v1/images/edits`
- ✅ Anthropic API supported endpoints:
  - `v1/messages`
  - `v1/messages/count_tokens`
- ✅ llama-server (llama.cpp) supported endpoints
  - `v1/rerank`, `v1/reranking`, `/rerank`
  - `/infill` - for code infilling
  - `/completion` - for completion endpoint
  - `/models` - list available models. same behavior as `v1/models`
  - `/props` - requires `?model={model_id}` query parameter to be provided. The autoload parameter is not supported and will be ignored.
- ✅ SDAPI via stable-diffusion.cpp's server
  - `/sdapi/v1/txt2img`
  - `/sdapi/v1/img2img`
  - `/sdapi/v1/loras` - requires `model` in request body to fetch the correct loras
- ✅ llama-swap API
  - `/ui` - web UI
  - `/upstream/:model_id` - direct access to upstream server (demo)
  - `/comfyui/` - ComfyUI compatible endpoint (#1001)
  - `/running` - list currently running models (#61)
  - `POST /api/models/unload` - manually unload all running models (#58)
  - `POST /api/models/unload/:model_id` - unload a specific model
  - `GET /api/profiles` - list configured profiles and the active selection
  - `PUT /api/profiles/active` - activate a profile or select none
  - `/logs` - remote log monitoring
    - `GET /logs` returns buffered plain text logs.
    - If `Accept: text/html` is sent, `/logs` redirects to `/ui/`.
    - `GET /logs/stream` keeps the connection open for live log streaming.
    - Stream endpoints send buffered history first by default; add `?no-history` to stream only new lines.
    - `GET /logs/stream/proxy` streams proxy logs only.
    - `GET /logs/stream/upstream` streams upstream process logs only.
    - `GET /logs/stream/{model_id}` streams logs for one model (including IDs with slashes, like `author/model`).
  - `/health` - just returns "OK"
  - `/metrics` - system and GPU metrics for prometheus
- ✅ API Key support - define keys to restrict access to API endpoints
- ✅ Customizable
  - Switch model ID routing at runtime with profiles
  - Run concurrent models with a custom DSL swap matrix (#643)
  - Automatic unloading of models after timeout by setting a `ttl`
  - Docker and Podman support using `cmd` and `cmdStop` together
  - Preload models on startup with `hooks` (#235)
  - Apply filters to requests to control inference with `stripParams`, `setParams` and `setParamsByID`

### Web UI

llama-swap includes a real time web interface with a playground for testing out all sorts of local models:

*(screenshot: playground)*

View detailed token metrics:

*(screenshot: token metrics)*

Inspect request and responses:

*(screenshot: request/response inspector)*

Manually load and unload models:

*(screenshot: manual load/unload)*

Real time log streaming:

*(screenshot: log streaming)*

## Installation

llama-swap can be installed in multiple ways

1. Docker
2. Homebrew (macOS and Linux)
3. MacPorts (macOS)
4. WinGet
5. From release binaries
6. From source

### Docker Install (download images)

Two types of container images are built nightly for llama-swap:

1. A unified container with llama-server, ik-llama-server, stable-diffusion.cpp, whisper.cpp and llama-swap built from source. This is only available for cuda and vulkan but has more capabilities. This one is recommended for use.
2. A legacy image that is based on llama.cpp's images and llama-swap copied into the container. Use this one if you prefer to stay close to llama.cpp's container images.

#### Unified container (Recommended)

```shell
$ docker pull ghcr.io/mostlygeek/llama-swap:unified-cuda

# run with a custom configuration and models directory
$ docker run -it --rm --runtime nvidia -p 9292:8080 \
  -v /path/to/models:/models \
  -v /path/to/custom/config.yaml:/etc/llama-swap/config/config.yaml \
  ghcr.io/mostlygeek/llama-swap:unified-cuda
```

#### Legacy container

```shell
$ docker pull ghcr.io/mostlygeek/llama-swap:cuda

# run with a custom configuration and models directory
$ docker run -it --rm --runtime nvidia -p 9292:8080 \
  -v /path/to/models:/models \
  -v /path/to/custom/config.yaml:/app/config.yaml \
  ghcr.io/mostlygeek/llama-swap:cuda
```

more examples

```shell
# pull latest images per platform
docker pull ghcr.io/mostlygeek/llama-swap:cpu
docker pull ghcr.io/mostlygeek/llama-swap:cuda
docker pull ghcr.io/mostlygeek/llama-swap:vulkan
docker pull ghcr.io/mostlygeek/llama-swap:intel
docker pull ghcr.io/mostlygeek/llama-swap:musa

# tagged llama-swap, platform and llama-server version images
docker pull ghcr.io/mostlygeek/llama-swap:v166-cuda-b6795

# non-root cuda
docker pull ghcr.io/mostlygeek/llama-swap:cuda-non-root
```

### Homebrew Install (macOS/Linux)

```shell
brew tap mostlygeek/llama-swap
brew install llama-swap
llama-swap --config path/to/config.yaml --listen localhost:8080
```

### MacPorts (macOS)

> [!NOTE]
> Maintained by MacPorts community - llama-swap port. It is not an official part of llama-swap.

```shell
sudo port install llama-swap
llama-swap --config path/to/config.yaml --listen localhost:8080
```

### WinGet Install (Windows)

> [!NOTE]
> WinGet is maintained by community contributor Dvd-Znf (#327). It is not an official part of llama-swap.

```shell
# install
C:\> winget install llama-swap

# upgrade
C:\> winget upgrade llama-swap
```

### Pre-built Binaries

Binaries are available on the release page for Linux, Mac, Windows and FreeBSD.

### Building from source

1. Building requires Go and Node.js (for UI).
1. `git clone https://github.com/mostlygeek/llama-swap.git`
1. `make clean all`
1. look in the `build/` subdirectory for the llama-swap binary

## Configuration

```yaml
# minimum viable config.yaml
models:
  model1:
    cmd: llama-server --port ${PORT} --model /path/to/model.gguf
```

That's all you need to get started:

1. `models` - holds all model configurations
2. `model1` - the ID used in API calls
3. `cmd` - the command to run to start the server.
4. `${PORT}` - an automatically assigned port number

Almost all configuration settings are optional and can be added one step at a time:

- Advanced features
  - `matrix` to run concurrent models with a custom swap logic DSL
  - `hooks` to run things on startup
  - `macros` reusable snippets
- Model customization
  - `ttl` to automatically unload models
  - `unloadTimeout` to tune graceful unloads (manual, API and `ttl` expiry)
  - `aliases` to use familiar model names (e.g., "gpt-4o-mini")
  - `env` to pass custom environment variables to inference servers
  - `cmdStop` gracefully stop Docker/Podman containers
  - `useModelName` to override model names sent to upstream servers
  - `${PORT}` automatic port variables for dynamic port assignment
  - `filters` rewrite parts of requests before sending to the upstream

See the configuration documentation for all options.

## How does llama-swap work?

When a request is made to an OpenAI compatible endpoint, llama-swap will extract the `model` value and load the appropriate server configuration to serve it. If the wrong upstream server is running, it will be replaced with the correct one. This is where the "swap" part comes in. The upstream server is automatically swapped to handle the request correctly.

In the most basic configuration llama-swap handles one model at a time. For more advanced use cases, using a `matrix` allows multiple models to be loaded at the same time. You have complete control over how your system resources are used.

## Reverse Proxy Configuration (nginx)

If you deploy llama-swap behind nginx, disable response buffering for streaming endpoints. By default, nginx buffers responses which breaks Server‑Sent Events (SSE) and streaming chat completion. (#236)

Recommended nginx configuration snippets:

```nginx
# SSE for UI events/logs
location /api/events {
  proxy_pass http://your-llama-swap-backend;
  proxy_buffering off;
  proxy_cache off;
}

# Streaming chat completions (stream=true)
location /v1/chat/completions {
  proxy_pass http://your-llama-swap-backend;
  proxy_buffering off;
  proxy_cache off;
}
```

As a safeguard, llama-swap also sets `X-Accel-Buffering: no` on SSE responses. However, explicitly disabling `proxy_buffering` at your reverse proxy is still recommended for reliable streaming behavior.

## Monitoring Logs on the CLI

```sh
# sends up to the last 10KB of logs
$ curl http://host/logs

# streams combined logs
curl -Ns http://host/logs/stream

# stream llama-swap's proxy status logs
curl -Ns http://host/logs/stream/proxy

# stream logs from upstream processes that llama-swap loads
curl -Ns http://host/logs/stream/upstream

# stream logs only from a specific model
curl -Ns http://host/logs/stream/{model_id}

# stream and filter logs with linux pipes
curl -Ns http://host/logs/stream | grep 'eval time'

# appending ?no-history will disable sending buffered history first
curl -Ns 'http://host/logs/stream?no-history'
```

## Do I need to use llama.cpp's server (llama-server)?

Any OpenAI compatible server would work. llama-swap was originally designed for llama-server and it is the best supported.

For Python based inference servers like vllm or tabbyAPI it is recommended to run them via podman or docker. This provides clean environment isolation as well as responding correctly to `SIGTERM` signals for proper shutdown.

---

## tool-swap notes

Everything above this line is llama-swap's own words. Everything below is ours.

### 1. The five sentences that define the philosophy we are copying

> *"one binary, one configuration file. no external dependencies"*

> *"Almost all configuration settings are optional and can be added one step at a time"*

> *"When a request is made … llama-swap will extract the `model` value and load the appropriate server configuration to serve it. If the wrong upstream server is running, it will be replaced with the correct one."*

> *"Automatic unloading of models after timeout by setting a `ttl`"*

> *"future proof, upgrade your inference servers at any time"*

The first two are **R4** and **R1** stated by someone else. The third is our request lifecycle ([`01_ARCHITECTURE.md`](../../01_ARCHITECTURE.md) §5) with `model` replaced by a path segment. The fourth is **D9**. The fifth is what **D2** buys us at a stronger granularity — they decouple the router from the *server binary*, we decouple it from the *entire Python environment*.

**The graduated-config principle is the one most worth internalising.** A five-line config that works, and every other key optional, is guardrail 10 ([`13_OPEN_QUESTIONS.md`](../../13_OPEN_QUESTIONS.md) Part D) — and llama-swap demonstrates that the principle survives a schema with well over a hundred keys, which is the reassurance that guardrail needs. Their minimum viable config is three lines; the full schema is 40 KB.

### 2. Facts here that contradict the plan's description of llama-swap

**The plan says it manages processes, not containers.** [`00_CONTEXT_AND_MOTIVATION.md`](../../00_CONTEXT_AND_MOTIVATION.md) §4: *"it manages processes not containers"*. [`14_ALTERNATIVES_EVALUATION.md`](../../14_ALTERNATIVES_EVALUATION.md) §3.1 goes further, presenting `cmd: docker run …` as an observation of ours: *"But note carefully — a configured llama-swap command **can** be `docker run ...`."*

The README lists **"Docker and Podman support using `cmd` and `cmdStop` together"** as a headline feature, and closes with a recommendation to use exactly that for Python servers:

> *"For Python based inference servers like vllm or tabbyAPI it is recommended to run them via podman or docker. This provides clean environment isolation as well as responding correctly to `SIGTERM` signals for proper shutdown."*

That is upstream's own documented practice, and — read closely — it is **upstream endorsing the reasoning behind D2**: containers for *clean environment isolation* of Python inference servers. The plan's framing understates the overlap. Recorded as finding F1 in [`INDEX.md`](INDEX.md) §3.

**This does not reopen ADR-0001.** See finding F2: the rejection stands, but for a narrower reason than the one recorded.

### 3. The API surface, sorted into three piles

| Endpoint | Our position |
| --- | --- |
| `/upstream/:model_id` | **Taken.** Our `/upstream/{tool}/...` ([`04_API_CONTRACT.md`](../../04_API_CONTRACT.md), **D4**) is this endpoint |
| `/running`, `/health`, `/metrics`, `/ui` | **Taken.** Our `/status`, `/health`, `/metrics` and `/ui` (**R1**) |
| `/logs/stream/{model_id}` | **Taken in spirit**, as `tswap logs {tool} -f` (**D8**). Note they offer it over **HTTP** as well as the CLI, with `?no-history` |
| `POST /api/models/unload/:model_id` | **Not in v1.** Distinct from the `POST /unload` that [ADR-0004](../../adr/0004-hard-stop-only-in-v1.md) removed: theirs *stops* the upstream, ours would have asked a live container to *release its weights*. A stop-this-tool-now endpoint remains available to us, and is a smaller thing than what was cut |
| `v1/*` — OpenAI and Anthropic doors, SDAPI, `/comfyui/` | **Refused, permanently.** Every one of these exists to speak somebody's generative-AI protocol. We serve none ([`04_API_CONTRACT.md`](../../04_API_CONTRACT.md) §0). **D13**'s `?format=tools` is our door instead |
| `GET /api/profiles`, `PUT /api/profiles/active` | **Refused.** Runtime model-ID rewriting is meaningless without `body.model` resolution |

**Note what the split reveals.** Their non-`/v1/` surface — `/upstream/`, `/running`, `/logs`, `/health`, `/metrics`, `/ui` — is **entirely protocol-agnostic**, and we take essentially all of it. The LLM-specific part is confined to the generative endpoints. That is the precise boundary **D4** draws when it says *"adopt llama-swap's behaviours, not its surface"*.

### 4. What their scale tells us

*"used by thousands of people to power their local AI workflows"*, 249 releases, and nightly multi-platform container builds. Two consequences worth holding onto:

- **Their semantics are load-tested; ours are not.** Where our design and theirs disagree on something behavioural — graceful-stop timeouts, eviction ordering, concurrency limits — the burden of proof is on us. §5 of [`17_LLAMA_SWAP_PHILOSOPHY.md`](../../17_LLAMA_SWAP_PHILOSOPHY.md) lists the four places this bites.
- **The feature list is a forecast of our own backlog.** Preload hooks, per-model env, graceful stop, concurrency limits, remote log streaming and Prometheus metrics all arrived in a project that started as *"one binary, one config file"*. Anything on their list we lack is a thing our users will eventually ask for, and the ones we have already anticipated are a decent signal that the design is sound.
