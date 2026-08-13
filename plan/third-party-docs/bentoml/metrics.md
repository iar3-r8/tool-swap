# Metrics — BentoML

> **Source:** https://docs.bentoml.com/en/latest/build-with-bentoml/observability/metrics.html
> **BentoML version at capture:** 1.4.39 (latest on PyPI, published 2026-05-07) · **Captured:** 2026-08-13
> **Relevance to tool-swap:** [`05_RUNTIME_AND_BATCHING.md`](../../05_RUNTIME_AND_BATCHING.md) §9 tabulates six runtime metrics and attributes **four of them to BentoML**. This page is the authoritative list of what BentoML actually provides. It also bears on **R1** (observability), on the M3.5 batching measurement ([`09_IMPLEMENTATION_PLAN.md`](../../09_IMPLEMENTATION_PLAN.md:132)), and on the `deploy/prometheus` and `deploy/grafana` trees already present in this repository.
> **Completeness:** **condensed.** The Prometheus-install, Grafana-dashboard and per-type custom-metric walkthroughs (`Counter`, `Summary`, `Gauge` — all identical in shape to the `Histogram` example) are summarised. The default-metrics table, the configuration options and the bucket rules are verbatim.

---

Metrics are important measurements that provide insights into the usage and performance of Services. BentoML provides a set of default metrics for performance analysis while you can also define custom metrics with Prometheus.

## Understand metrics

You can access metrics via the `metrics` endpoint of a BentoML Service. This endpoint is enabled by default and outputs metrics that Prometheus can scrape to monitor your Services continuously.

### Default metrics

BentoML automatically collects a set of default metrics for each Service. These metrics are tracked across different dimensions to provide detailed visibility into Service operations:

| Name | Type | Dimension |
| --- | --- | --- |
| `bentoml_service_request_in_progress` | Gauge | `endpoint`, `runner_name`, `service_name`, `service_version` |
| `bentoml_service_request_total` | Counter | `endpoint`, `service_name`, `runner_name`, `service_version`, `http_response_code` |
| `bentoml_service_request_duration_seconds_sum`, `bentoml_service_request_duration_seconds_count`, `bentoml_service_request_duration_seconds_bucket` | Histogram | `endpoint`, `service_name`, `runner_name`, `service_version`, `http_response_code` |
| `bentoml_service_adaptive_batch_size_sum`, `bentoml_service_adaptive_batch_size_count`, `bentoml_service_adaptive_batch_size_bucket` | Histogram | `method_name`, `service_name`, `runner_name`, `service_version`, `worker_index` |

* `request_in_progress`: The number of requests that are currently being processed by a Service.
* `request_total`: The total number of requests that a Service has processed.
* `request_duration_seconds`: The time taken to process requests, including the total sum of request processing time, count of requests processed, and distribution across specified duration buckets.
* `adaptive_batch_size`: The adaptive batch sizes used during Service execution, which is relevant for optimizing performance in batch processing scenarios. **You need to enable adaptive batching to collect this metric.**

### Metric types

BentoML supports all metric types provided by Prometheus: `Gauge`, `Counter`, `Histogram`, `Summary`.

### Dimensions

Dimensions tracked for the default BentoML metrics include:

* `endpoint`: The specific API endpoint being accessed.
* `runner_name`: The name of the running Service handling the request.
* `service_name`: The name of the Bento Service handling the request.
* `service_version`: The version of the Service.
* `http_response_code`: The HTTP response code of the request.
* `worker_index`: The worker instance that is running the inference.

## Configure default metrics

To customize how metrics are collected and reported in BentoML, use the `metrics` parameter within the `@bentoml.service` decorator:

```python
@bentoml.service(metrics={
    "enabled": True,
    "namespace": "custom_namespace",
})
class MyService:
    # Service implementation
```

* `enabled`: This option is enabled by default. When enabled, you can access the metrics through the `metrics` endpoint of a BentoML Service.
* `namespace`: Follows the labeling convention of Prometheus. The default namespace is `bentoml_service`, which covers most use cases.

### Customize the duration bucket size

You can customize the duration bucket size of `request_duration_seconds` in the following two ways:

* **Manual bucket definition**. Specify explicit steps using `buckets`:

  ```python
  @bentoml.service(metrics={
      "enabled": True,
      "namespace": "bentoml_service",
      "duration": {
          "buckets": [0.1, 0.2, 0.5, 1, 2, 5, 10]
      }
  })
  class MyService:
      # Service implementation
  ```
* **Exponential bucket generation**. Automatically generate exponential buckets with any given `min`, `max` and `factor` values.

  + `min`: The lower bound of the smallest bucket in the histogram.
  + `max`: The upper bound of the largest bucket in the histogram.
  + `factor`: Determines the exponential growth rate of the bucket sizes.

  ```python
  @bentoml.service(metrics={
      "enabled": True,
      "namespace": "bentoml_service",
      "duration": {
          "min": 0.1,
          "max": 10,
          "factor": 1.2
      }
  })
  class MyService:
      # Service implementation
  ```

> **Note**
>
> * `duration.min`, `duration.max` and `duration.factor` are mutually exclusive with `duration.buckets`.
> * `duration.factor` must be greater than 1 to ensure each subsequent bucket is larger than the previous one.
> * **The buckets for the `adaptive_batch_size` Histogram are calculated based on the `max_batch_size` defined. The bucket sizes start at 1 and increase exponentially up to the `max_batch_size` with a factor of 2.**

By default, BentoML provides optimized histogram buckets ranging from 5ms to 180s, carefully distributed to monitor both fast API calls and long-running LLM/GenAI inference requests. The buckets are strategically placed to cover key latency ranges: fast API calls (5ms-50ms), regular API calls (100ms-1s), long API calls (2.5s-10s), and LLM inference (30s-180s).

## Create custom metrics

You can define and use custom metrics of `Counter`, `Histogram`, `Summary`, and `Gauge` within your BentoML Service using the `prometheus_client` API. Install the Prometheus Python client package (`pip install prometheus-client`).

To define custom metrics, use the metric classes from the `prometheus_client` module and set `name`, `documentation`, `labelnames` and (for histograms) `buckets`. Of `labelnames`, upstream notes: *"Once you define a label for a metric, all instances of that metric must include that label with some value."*

```python
import bentoml
from prometheus_client import Histogram

# Define Histogram metric
inference_duration_histogram = Histogram(
    name="inference_duration_seconds",
    documentation="Time taken for inference",
    labelnames=["endpoint"],
    buckets=(
      0.005, 0.01, 0.025, 0.05,         # Fast API calls (5ms - 50ms)
      0.1, 0.25, 0.5, 1.0,              # Regular API calls (100ms - 1s)
      2.5, 5.0, 10.0,                   # Long API calls (2.5s - 10s)
      30.0, 60.0, 120.0, 180.0,         # LLM models (30s - 180s)
      float("inf"),
    ),
)

@bentoml.service
class HistogramService:
    @bentoml.api
    def infer(self, text: str) -> str:
        inference_duration_histogram.labels(endpoint='summarize').observe(512)
        # Implementation logic
```

`Counter` (`.inc()`), `Summary` (`.observe()`) and `Gauge` (`.inc()` / `.dec()`) follow the same shape: a module-level `prometheus_client` object, labelled at the call site.

Custom metrics appear on the same `/metrics` endpoint:

```
curl -X 'GET' 'http://localhost:3000/metrics' -H 'accept: */*' | grep -E 'inference_time_seconds|summary_requests_total'
```

## Use Prometheus to scrape metrics *(summarised)*

A scrape job pointed at the Service's `/metrics` path, e.g.:

```yaml
global:
  scrape_interval: 5s
  evaluation_interval: 15s

scrape_configs:
  - job_name: prometheus
    metrics_path: "/metrics" # The metrics endpoint of the BentoML Service
    static_configs:
      - targets: ["0.0.0.0:3000"] # The address where the BentoML Service is running
```

Example query — the 99th percentile of request durations to `/encode` over the last minute:

```
histogram_quantile(0.99, rate(bentoml_service_request_duration_seconds_bucket{endpoint="/encode"}[1m]))
```

## Create a Grafana dashboard *(summarised)*

Install Grafana, add Prometheus as a data source, and build panels on metrics such as `bentoml_service_request_duration_seconds_bucket`. Upstream notes that **Grafana's default port 3000 collides with BentoML's default port** and shows how to move Grafana to another port.

---

## tool-swap notes

Everything above is BentoML's. Everything below is ours.

### 1. ⚠️ **[`05 §9`](../../05_RUNTIME_AND_BATCHING.md:353)'s metric table over-attributes to BentoML. Two of the four claimed metrics do not exist.**

The plan's table, with what this page actually supports:

| [`05 §9`](../../05_RUNTIME_AND_BATCHING.md:353) name | Claimed source | Reality |
| --- | --- | --- |
| `tswap_requests_total` | BentoML | ✅ `bentoml_service_request_total` |
| `tswap_request_duration_seconds` | BentoML | ✅ `bentoml_service_request_duration_seconds` |
| `tswap_batch_size` | BentoML dispatcher | ✅ `bentoml_service_adaptive_batch_size` |
| `tswap_queue_wait_seconds` | BentoML dispatcher | ❌ **No such metric.** Nothing on this page or in the source exposes time-spent-waiting-in-the-dispatcher |
| `tswap_tool_loaded` | Ours | ✅ ours to write |
| *(not listed)* | — | ➕ `bentoml_service_request_in_progress` (Gauge) exists and is useful |

**`tswap_queue_wait_seconds` must be built or dropped.** It is not free. That matters because queue wait is *the* diagnostic for "is batching helping or hurting?" — the question [`02 §7`](../../02_CONFIGURATION.md:345) expects operators to answer when tuning `max_wait_ms`. Options:

- **Approximate it above the seam**: the adapter timestamps arrival in the predict wrapper and observes the delta when the handler is entered. Cheap, ours, backend-agnostic — and it belongs above the seam anyway under [`05 §2.4`](../../05_RUNTIME_AND_BATCHING.md:129).
- **Or drop it** and rely on `request_duration` minus handler duration.

The first is better and is a handful of lines. Either way, **[`05 §9`](../../05_RUNTIME_AND_BATCHING.md:353) currently promises a metric nobody will find.** Proposed amendment in [`INDEX.md`](INDEX.md).

Add `bentoml_service_request_in_progress` to our table too: an in-flight gauge is exactly what distinguishes "saturated" from "idle" when diagnosing the `ServiceUnavailable("process is overloaded")` 503 ([`health-endpoints-and-lifecycle-source.md`](health-endpoints-and-lifecycle-source.md) §6).

### 2. **`namespace` gives us the `tswap_` prefix for free** ⭐

`metrics={"namespace": "..."}` renames the whole default set. Setting `namespace: "tswap"` yields `tswap_request_total`, `tswap_request_duration_seconds`, `tswap_adaptive_batch_size` — **very nearly the names [`05 §9`](../../05_RUNTIME_AND_BATCHING.md:353) already specifies**, with no relabelling in Prometheus and no wrapper metrics of our own.

Two consequences:

- The adapter should set the namespace from a single constant, so every tool in the zoo exposes identically-named series and one Grafana dashboard covers all of them. That is **R1** delivered nearly for free.
- Adjust [`05 §9`](../../05_RUNTIME_AND_BATCHING.md:353) to the names the namespace actually produces (`tswap_request_total`, not `tswap_requests_total`; `tswap_adaptive_batch_size`, not `tswap_batch_size`), or accept a rename layer. **Match the framework's suffixes rather than inventing near-misses** — a metric named nearly-but-not-quite what the collector exports is a debugging tax forever.

Relevant to the existing [`deploy/prometheus/`](../../../deploy/prometheus/) and [`deploy/grafana/`](../../../deploy/grafana/) trees in this repo: they should be written against the namespaced names, and a scrape job per tool container on the internal network (**D21** means no published ports, so Prometheus must be on that network).

### 3. **`adaptive_batch_size` is labelled by `worker_index` — this is M3.5's measurement instrument** ⭐

Dimensions: `method_name`, `service_name`, `runner_name`, `service_version`, **`worker_index`**.

M3.5 step 4 ([`09`](../../09_IMPLEMENTATION_PLAN.md:132)) asks whether 32 concurrent requests produce far fewer than 32 handler invocations, and whether latency stays near `max_latency_ms`. **The framework already measures the first thing.** The spike should scrape `/metrics` and report the `adaptive_batch_size` histogram rather than instrumenting by hand — the same lesson as [`ray-serve/INDEX.md`](../ray-serve/INDEX.md) §3.4 item 15, where using the vendor's own metrics beat ad-hoc timing.

The `worker_index` label also gives an independent check on the 1-vs-0 indexing contradiction found in [`workers-and-devices.md`](workers-and-devices.md) §1: run two workers, look at the label values.

**A caveat with teeth for the spike:** *"The buckets for the `adaptive_batch_size` Histogram are calculated based on the `max_batch_size` defined … start at 1 and increase exponentially up to the `max_batch_size` with a factor of 2."* With our default `max_batch_size: 8`, the buckets are 1, 2, 4, 8 — four buckets. Fine for a smoke test, coarse for tuning. If the spike wants resolution, raise `max_batch_size` **for the spike only**, and do not let that value leak into the shipped default, which is deliberately conservative for CT-volume payloads ([`02 §7`](../../02_CONFIGURATION.md:344)).

### 4. `adaptive_batch_size` is only collected when batching is on — a free contract assertion

*"You need to enable adaptive batching to collect this metric."*

Which makes it an observable proxy for a configuration fact. The M4 contract suite asserts that `batching.enabled: false` still calls the handler with lists of length 1 ([`09 M4`](../../09_IMPLEMENTATION_PLAN.md:163)); the **absence** of this metric series is a second, independent confirmation that the dispatcher really is disengaged rather than merely batching in ones. Similarly, its presence proves batching is genuinely active — the thing `tswap preflight` should report ([`07_CLI_AND_OPS.md`](../../07_CLI_AND_OPS.md:255)).

### 5. Duration buckets are configurable, and the defaults are LLM-shaped

The default buckets span 5 ms to 180 s, explicitly tuned for *"LLM inference (30s-180s)"*. Our zoo is embeddings, classifiers and segmentation ([`00_CONTEXT_AND_MOTIVATION.md`](../../00_CONTEXT_AND_MOTIVATION.md)), where a CT segmentation might take 30 s but a text embedding takes 20 ms. The default range covers both, so **leave it alone in v1** — but the knob (`duration.buckets`, or `min`/`max`/`factor`) is per-service, so a tool with an unusual latency profile can tune it. Worth noting as a future `tool.yaml` key **only if someone asks**; adding it now is a config key with no demonstrated need ([`16_COMPLEXITY_AUDIT.md`](../../16_COMPLEXITY_AUDIT.md) territory).

### 6. `prometheus-client` is already a BentoML dependency — our custom metrics cost nothing

PyPI metadata lists `prometheus-client>=0.10.0` as a direct BentoML requirement, so the *"Prerequisites: `pip install prometheus-client`"* step is already satisfied inside any tool image. `tswap_tool_loaded` and the queue-wait histogram from §1 add **no new dependency** to `tool_swap_runtime`, which matters given the strict dependency budget in [`05 §1.1`](../../05_RUNTIME_AND_BATCHING.md:42) (*"BentoML plus its transitive set, and nothing further of our own choosing"*).

Note the label rule — *"all instances of that metric must include that label with some value"* — is a real source of runtime errors in Prometheus clients. Our custom metrics should be defined once at module scope in the adapter, with a fixed label set, never constructed per request.

### 7. **Metrics are per-container, and nothing aggregates them — that is the router's job**

Every tool container exposes its own `/metrics` with `service_name` distinguishing it. There is no aggregation layer, because BentoML's is BentoCloud, which we do not use. So the zoo-wide view — which tools are loaded, which are thrashing, what the eviction rate is — comes from **the router's** metrics ([`07_CLI_AND_OPS.md`](../../07_CLI_AND_OPS.md)), not from these.

Clean division worth recording: **per-tool performance is BentoML's `/metrics`; zoo-wide residency and scheduling is ours.** The two are joined by `service_name` and by our container labels. Neither side needs to know the other's internals — which is the same seam **D14** draws everywhere else.
