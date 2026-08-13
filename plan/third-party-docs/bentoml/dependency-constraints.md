# BentoML's dependency constraints — **packaging metadata, not documentation**

> **Source:** the PyPI JSON API, `https://pypi.org/pypi/bentoml/json`, read 2026-08-13. The `requires_dist` field of the released distribution — i.e. the package's own declared requirements, not prose from the documentation site.
> **BentoML version:** **1.4.39**, published 2026-05-07, `requires_python >=3.9`, licence Apache-2.0.
> **Relevance to tool-swap:** **D14**'s stated risk is that BentoML's pins conflict with real model stacks ([`05_RUNTIME_AND_BATCHING.md`](../../05_RUNTIME_AND_BATCHING.md) §1.1). This file is the evidence for what those pins actually are. It is the input to **M3.5** step 1 and 2 ([`09_IMPLEMENTATION_PLAN.md`](../../09_IMPLEMENTATION_PLAN.md:129)), to the `resolve.yml` CI gate ([`08_REPO_LAYOUT.md`](../../08_REPO_LAYOUT.md) §6), and to the pin chosen in `pyproject.toml`.
> **Completeness:** the core `requires_dist` set is reproduced in full. The optional extras are summarised by name; none is installed by a default `pip install bentoml`.

---

## 1. Release facts

| Field | Value |
| --- | --- |
| Latest version | **1.4.39** |
| Published | 2026-05-07 |
| `requires_python` | `>=3.9` |
| Licence | Apache-2.0 |
| Classifiers | Python 3.9, 3.10, 3.11, 3.12 |
| Version R8 ran ([`12_REFERENCE_CODE.md`](../../12_REFERENCE_CODE.md:1547)) | 1.4.30 |
| **Yanked releases** | **1.4.31** (no reason given), **1.4.9** (*"bad release"*), 1.0.6 (*"a critical module import issue"*), 0.8.0, 0.8.2, and the 1.0.0 dev releases |

## 2. Core requirements — installed by `pip install bentoml`

Verbatim from `requires_dist`, grouped by kind:

**Upper-bounded or windowed — the ones that can actually conflict**

```
cattrs<23.2.0,>=22.1.0
pydantic<3
```

**Coordinated OpenTelemetry family — seven packages, pinned compatible-release, one on a beta series**

```
opentelemetry-api~=1.20
opentelemetry-sdk~=1.20
opentelemetry-instrumentation~=0.41b0
opentelemetry-instrumentation-aiohttp-client~=0.41b0
opentelemetry-instrumentation-asgi~=0.41b0
opentelemetry-semantic-conventions~=0.41b0
opentelemetry-util-http~=0.41b0
```

**Lower-bounded only**

```
a2wsgi>=1.10.7          aiohttp-asgi-connector>=1.1.2   aiosqlite>=0.20.0
attrs>=22.2.0           click>=7.0                      cloudpickle>=2.0.0
fsspec>=2025.7.0        httpx-ws>=0.6.0                 jinja2>=3.0.1
kantoku>=0.18.3         packaging>=22.0                 pip-requirements-parser>=31.2.0
prometheus-client>=0.10.0                               pyyaml>=5.0
rich>=11.2.0            rich-toolkit>=0.15.1            simple-di>=0.1.4
starlette>=0.24.0       uvicorn>=0.22.0                 watchfiles>=0.15.0
tomli>=1.1.0; python_version < "3.11"
```

**Unconstrained**

```
aiohttp    click-option-group    httpx    numpy    nvidia-ml-py    pathspec
psutil     python-dateutil       python-json-logger    python-multipart
schema     tomli-w
```

## 3. Optional extras — none installed by default

`all`, `aws`, `grpc`, `grpc-channelz`, `grpc-reflection`, `io`, `io-image`, `io-pandas`, `monitor-otlp`, `tracing`, `tracing-jaeger`, `tracing-otlp`, `tracing-zipkin`, `triton`, `unsloth`.

Notable contents: `io` brings `pandas>=1`, `pillow` and `pyarrow`; `grpc` brings `grpcio` and `protobuf`; `triton` brings `tritonclient>=2.29.0`. **We install none of these**, which keeps `pandas`, `pyarrow`, `protobuf` and `grpcio` out of every tool image.

---

## tool-swap notes

Everything above is BentoML's packaging metadata. Everything below is ours.

### 1. ⚠️ **The plan's central factual claim about D14's risk is wrong in its specifics.**

The phrase *"BentoML's locked pins (pydantic, starlette, click)"* — or a close variant — appears in at least five places:

- [`05_RUNTIME_AND_BATCHING.md`](../../05_RUNTIME_AND_BATCHING.md:29) §1, [§1.1](../../05_RUNTIME_AND_BATCHING.md:38)
- [`13_OPEN_QUESTIONS.md`](../../13_OPEN_QUESTIONS.md:108) **D14**
- [`08_REPO_LAYOUT.md`](../../08_REPO_LAYOUT.md:200) §3
- [`00_CONTEXT_AND_MOTIVATION.md`](../../00_CONTEXT_AND_MOTIVATION.md:223) §4
- [`09_IMPLEMENTATION_PLAN.md`](../../09_IMPLEMENTATION_PLAN.md:129) M3.5 step 1, which instructs the spike to *"record the resolved versions of pydantic, starlette and click"*

Those three packages are **the loosest constraints in the distribution**:

| Package | Plan says | Actually |
| --- | --- | --- |
| `pydantic` | "locked pin" | `<3` — an upper bound only. Any pydantic 2.x satisfies it |
| `starlette` | "locked pin" | `>=0.24.0` — a **lower** bound. Cannot conflict with a newer starlette |
| `click` | "locked pin" | `>=7.0` — a **lower** bound, and permissive |

A lower bound is not a lock and cannot cause the conflict **D14** worries about. **The stated risk is aimed at three packages that are nearly incapable of causing it.**

**This does not overturn D14 — it sharpens it.** The decision was to accept a dependency until a concrete model proves an unresolvable conflict; that framing is unchanged. What changes is *where to look*.

### 2. **The constraints that can actually bite**

**`cattrs<23.2.0,>=22.1.0`** — the only genuine window, and it is narrow and old. `cattrs` is a serialisation library used by `attrs` ecosystems; anything else in a tool image needing `cattrs>=23.2` **cannot coexist with BentoML**. This is the single most likely source of the failure **D14** anticipates, and it is named nowhere in the plan.

**The OpenTelemetry family** — seven packages, `~=1.20` for API/SDK and `~=0.41b0` for the instrumentation set. Two problems: it is a *coordinated* set (upgrading one demands the rest), and `0.41b0` is a **beta** series. Any tool image whose own stack pulls a different OTel — increasingly common in observability-aware ML libraries — resolves against seven simultaneous constraints. Also worth noting: our runtime therefore ships an OTel tracer in every image whether or not we use tracing.

**`fsspec>=2025.7.0`** — a floor barely a year old at capture. On an older vendor base image ([`03_TOOL_AUTHORING.md`](../../03_TOOL_AUTHORING.md) §6, `nvcr.io`) with a pinned older `fsspec`, this forces an upgrade that may drag `s3fs`/`gcsfs` behaviour with it. A plausible Level-3 failure.

**`numpy` unconstrained** — no bound at all. Benign for resolution, and *dangerous* for behaviour: the tool's own numpy wins, which is right, but it means BentoML is untested against whatever that is. Relevant to the TensorFlow stack in M3.5 step 2, historically the most numpy-sensitive.

**`nvidia-ml-py`** — an NVIDIA management binding pulled into **every** image, including CPU-only ones. Harmless, but worth knowing before someone asks why a CPU tool image has an NVIDIA package.

**`kantoku>=0.18.3`** — a low-profile third-party dependency most readers will not recognise. Named here so it is not a surprise in a lock file.

### 3. **Proposed amendment to M3.5 step 1 — measure the right things**

[`09 M3.5`](../../09_IMPLEMENTATION_PLAN.md:129) step 1 currently says: *"Record the resolved versions of pydantic, starlette and click."* Those three will resolve to whatever the tool wants and prove nothing.

**Record instead:**

| Record | Why |
| --- | --- |
| `cattrs` | the only narrow window; the most likely hard conflict |
| the seven `opentelemetry-*` versions | a coordinated beta-pinned family |
| `fsspec` | a recent floor against older vendor images |
| `numpy` | unconstrained by BentoML, constrained by every ML stack |
| `pydantic` | still worth recording — not as a conflict risk but because **our own schema layer uses pydantic** (**D13**, M1), so we care which 2.x lands |

Keep the two stacks the step already names (torch/monai/transformers, and tensorflow/tf-keras) — those are the right realistic worst cases.

### 4. **Yanked releases make the pinning policy a real requirement, not a formality**

**1.4.31 is yanked.** So were 1.4.9 (*"bad release"*) and 1.0.6 (*"a critical module import issue"*). Three yanks in the recent history of a package we intend to pin into **every image in the zoo**.

[`08 §3`](../../08_REPO_LAYOUT.md:202) already argues the pin is the point. Add two rules:

1. **Check the yank status before pinning**, and again before any upgrade. `pip` will refuse a yanked version by default, but a version already baked into built images does not un-bake itself.
2. **`tswap doctor` should report the BentoML version in each built image** ([`05 §1.2`](../../05_RUNTIME_AND_BATCHING.md:54) already asks for resolved versions) — which is how a zoo-wide "we are on a yanked release" is discovered at all.

Note the practical shape of the risk: images are built at different times ([`09 M5`](../../09_IMPLEMENTATION_PLAN.md)), so **a zoo can span several BentoML versions simultaneously**. That is exactly the gradual, per-image upgrade path [`15_RAY_SERVE_EVALUATION.md`](../../15_RAY_SERVE_EVALUATION.md:86) contrasts favourably with Ray's all-at-once lockstep — a real advantage, and one that only holds if `doctor` can tell us what is where.

### 5. **`requires_python >=3.9` — no constraint on us, and a note for Level 3**

BentoML supports 3.9 through 3.12. Our base images ([`03 §6`](../../03_TOOL_AUTHORING.md:334)) choose the interpreter, so this is not binding. Worth contrasting with Ray's *"the Ray version and Python version in the container must match those of the host environment exactly… down to the patch number"* ([ADR-0003](../../adr/0003-ray-serve-not-adopted.md:33)): **BentoML constrains the interpreter to a four-version range and nothing else.** That is the concrete form of the "per-image and gradual versus global and simultaneous" argument in [`15_RAY_SERVE_EVALUATION.md`](../../15_RAY_SERVE_EVALUATION.md:88), and it is worth citing there since that section currently argues it without numbers.

For Level 3 authoring on a vendor base image, the only real question is whether the image's Python is ≥3.9 — true of every current `nvcr.io` image.

### 6. **The extras we do not install are a quiet win worth protecting**

A default `pip install bentoml` brings **no** `pandas`, `pyarrow`, `protobuf`, `grpcio` or `tritonclient`. All are behind extras. That materially reduces the conflict surface in every tool image and is worth stating in [`05 §1.1`](../../05_RUNTIME_AND_BATCHING.md:42), which currently accepts *"BentoML's own tree wholesale"* without noting that the tree is smaller than it first appears.

**Corollary for the pin:** the runtime distribution must depend on `bentoml==X.Y.Z` with **no extras**. If a tool ever needs `bentoml[io]`, that is a per-tool decision and a new resolution to test — not a change to the base.

### 7. How to re-check this

```
curl -s https://pypi.org/pypi/bentoml/json | jq '.info.version, .info.requires_dist, .info.requires_python'
```

For a specific pinned version, `https://pypi.org/pypi/bentoml/<version>/json`. **Re-run before pinning in M3.5 and before any upgrade**; `requires_dist` changes between releases, and every constraint above is a fact about 1.4.39 only.
