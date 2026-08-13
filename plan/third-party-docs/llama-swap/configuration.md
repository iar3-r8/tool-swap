# llama-swap — configuration documentation

**Source URL:** https://github.com/mostlygeek/llama-swap/blob/main/docs/configuration.md
**Upstream version at capture:** **v249** (latest release, published 2026-08-10); file read from `main`
**Captured:** 2026-08-13
**Relevance to tool-swap:** the direct model for [`02_CONFIGURATION.md`](../../02_CONFIGURATION.md). **D4** adopts llama-swap's behaviours, and this page is where those behaviours are configured. It is also the evidence for guardrail 10 — *"the five-line minimal config must keep working"* ([`13_OPEN_QUESTIONS.md`](../../13_OPEN_QUESTIONS.md) Part D).
**Completeness:** **verbatim**. The narrative page only; the exhaustive key list is in [`config-schema.md`](config-schema.md).

---

# config.yaml

llama-swap is designed to be very simple: one binary, one configuration file.

## minimal viable config

```yaml
models:
  model1:
    cmd: llama-server --port ${PORT} --model /path/to/model.gguf
```

This is enough to launch `llama-server` to serve `model1`. Of course, llama-swap is about making it possible to serve many models:

```yaml
models:
  model1:
    cmd: llama-server --port ${PORT} -m /path/to/model.gguf
  model2:
    cmd: llama-server --port ${PORT} -m /path/to/another_model.gguf
  model3:
    cmd: llama-server --port ${PORT} -m /path/to/third_model.gguf
```

With this configuration models will be hot swapped and loaded on demand. The special `${PORT}` macro provides a unique port per model which is useful if you want to run multiple models at the same time with the `matrix` feature.

## Advanced control with `cmd`

llama-swap is also about customizability. You can use any CLI flag available:

```yaml
models:
  model1:
    cmd: | # support for multi-line
      llama-server --PORT ${PORT} -m /path/to/model.gguf
      --ctx-size 8192
      --jinja
      --cache-type-k q8_0
      --cache-type-v q8_0
```

## Support for any OpenAI API compatible server

llama-swap supports any OpenAI API compatible server. If you can run it on the CLI llama-swap will be able to manage it. Even if it's run in Docker or Podman containers.

```yaml
models:
  "Q3-30B-CODER-VLLM":
    name: "Qwen3 30B Coder vllm AWQ (Q3-30B-CODER-VLLM)"

    # cmdStop provides a reliable way to stop containers
    cmdStop: docker stop vllm-coder

    cmd: |
      docker run --init --rm --name vllm-coder
      --runtime=nvidia --gpus '"device=2,3"'
      --shm-size=16g
      -v /mnt/nvme/vllm-cache:/root/.cache
      -v /mnt/ssd-extra/models:/models -p ${PORT}:8000
      vllm/vllm-openai:v0.10.0
      --model "/models/cpatonn/Qwen3-Coder-30B-A3B-Instruct-AWQ"
      --served-model-name "Q3-30B-CODER-VLLM"
      --enable-expert-parallel
      --swap-space 16
      --max-num-seqs 512
      --max-model-len 65536
      --max-seq-len-to-capture 65536
      --gpu-memory-utilization 0.9
      --tensor-parallel-size 2
      --trust-remote-code
```

## Many more features..

llama-swap supports many more features to customize how you want to manage your environment.

| Feature | Description |
| --------- | ---------------------------------------------- |
| `ttl` | automatic unloading of models after a timeout |
| `macros` | reusable snippets to use in configurations |
| `matrix` | run multiple models at a time |
| `hooks` | event driven functionality |
| `env` | define environment variables per model |
| `aliases` | serve a model with different names |
| `filters` | modify requests before sending to the upstream |
| `profiles` | switch model ID replacements at runtime |
| `...` | And many more tweaks |

## Full Configuration Example

Check config.example.yaml for the most up to date reference for all example configurations. It has grown quite complex but your favorite local LLM can help with a local configuration.

---

## tool-swap notes

### 1. The `docker run` example is upstream's, not ours

The section headed *"Support for any OpenAI API compatible server"* is the single most consequential thing in this capture. It is a **complete, worked, GPU-pinned container example** — `--gpus '"device=2,3"'`, cache and model mounts, `-p ${PORT}:8000`, and `cmdStop: docker stop vllm-coder` — presented as ordinary usage.

Compare [`14_ALTERNATIVES_EVALUATION.md`](../../14_ALTERNATIVES_EVALUATION.md) §3.1, which introduces the same idea as our own inference:

> *"But note carefully — a configured llama-swap command **can** be `docker run ...`. That single observation makes the following genuinely viable…"*

It is not an observation about a latent capability. It is a documented, first-class pattern with a dedicated config key (`cmdStop`) built to support it. Recorded as finding **F1** in [`INDEX.md`](INDEX.md) §3.

Note also that this example is **almost exactly the R8 vLLM compose service** reproduced in [`12_REFERENCE_CODE.md`](../../12_REFERENCE_CODE.md) §12 — same device pinning, same `--gpu-memory-utilization 0.9`, same cache mounts. Two independent projects converged on the same shape for the same reason.

### 2. Where their config and ours genuinely diverge

The divergence is **not** process-versus-container. It is *what the router is given*:

| | llama-swap | tool-swap |
| --- | --- | --- |
| Unit of configuration | **A command line** (`cmd`) | **An image** plus declarative fields (**D2**, **D21**) |
| Who decides the port | The router, via `${PORT}` into the command | Nobody — container name on a shared network, no host ports published (**D21**) |
| Who decides the device | The **author**, by writing `--gpus` into `cmd` | The **scheduler**, from `devices: [0,1]` (**D7**) |
| Who stops the upstream | A second command line (`cmdStop`) | The container backend, by construction |
| What the router knows about the tool | Nothing beyond the string | An input/output **schema** (**D13**) |

Their model is *maximum flexibility, minimum knowledge*: give the router an opaque command and it will run it. That is right for their problem — arbitrary third-party servers with flags nobody can enumerate.

Ours is the opposite trade. Because every tool is one we build ([`03_TOOL_AUTHORING.md`](../../03_TOOL_AUTHORING.md)), the router can know a tool's schema, which is precisely what makes **D13**'s `?format=tools` possible. **A `cmd:` string cannot be introspected by an LLM. A JSON Schema can.** That single sentence is why we could not have adopted their config shape wholesale even if the API had matched.

**The cost of our choice, stated honestly:** their config supports any server ever written, ours supports only tools built on our runtime. §5 of [`17_LLAMA_SWAP_PHILOSOPHY.md`](../../17_LLAMA_SWAP_PHILOSOPHY.md) asks whether an escape hatch — a raw `image:` + `command:` tool with no schema — is worth having. **D4b** and [`01_ARCHITECTURE.md`](../../01_ARCHITECTURE.md) §7 currently say no, on the grounds that a second class of tool means a permanent column of caveats.

### 3. `${PORT}` and the R8 port-index defect

`${PORT}` is *"an automatically assigned port number"*, allocated from `startPort` (default 5800) and incremented per model that uses it.

This is worth noting precisely because **we rejected it**. **D21** publishes no host ports at all, addressing tools by container name on a shared network. The reason is in [`00_CONTEXT_AND_MOTIVATION.md`](../../00_CONTEXT_AND_MOTIVATION.md) §2.3: R8 assigned ports by registry index, so *"reorder the registry and every port changes"*. llama-swap's allocation is by iteration order too, and carries the same hazard in principle — but it does not bite them, because their ports are internal to a config the user already controls, and their upstreams are addressed by `proxy:` URL.

**Our stronger property comes free from Docker networking**, not from cleverness. Worth remembering if `expose_host_port` ever grows beyond debugging use.

### 4. The graduated-complexity ladder is the same ladder

> *"Almost all configuration settings are optional and can be added one step at a time"*

Three lines to start; `cmd:` as a multi-line block when flags are needed; `macros`, `groups`/`matrix`, `hooks`, `filters` when the deployment demands them. That is **D3**'s Level 0 → Level 4 ladder ([`03_TOOL_AUTHORING.md`](../../03_TOOL_AUTHORING.md)) applied to configuration rather than authoring.

Their closing line is also a warning we should heed, since it is an admission:

> *"It has grown quite complex but your favorite local LLM can help with a local configuration."*

A config that needs an LLM to write is a config that has outgrown **R4**. Guardrail 10 exists to stop us arriving there; llama-swap is the evidence that arriving there is the default outcome of success, not a hypothetical.
