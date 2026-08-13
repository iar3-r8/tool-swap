# Customize error responses — BentoML

> **Source:** https://docs.bentoml.com/en/latest/build-with-bentoml/error-handling.html
> **BentoML version at capture:** 1.4.39 (latest on PyPI, published 2026-05-07) · **Captured:** 2026-08-13
> **Relevance to tool-swap:** the error envelope and code→HTTP mapping in [`04_API_CONTRACT.md`](../../04_API_CONTRACT.md) §6, the per-item failure isolation of `retry_singly` ([`05_RUNTIME_AND_BATCHING.md`](../../05_RUNTIME_AND_BATCHING.md) §4), and guardrail 6 — *"errors are actionable: they name what failed, why, and the command that helps"* ([`09_IMPLEMENTATION_PLAN.md`](../../09_IMPLEMENTATION_PLAN.md:347)).
> **Completeness:** complete. This is a genuinely short page — the entire body is reproduced below. Its brevity is itself a finding; see note 4.

---

Effective error handling is important for building user-friendly AI applications. BentoML facilitates this by allowing you to customize error handling logic for a Service.

## Custom exception class

To define a custom exception, inherit from `BentoMLException` or one of its subclasses, such as `InvalidArgument` in the example below.

> **Note**
>
> **BentoML reserves error codes 401, 403, and any above 500. Avoid using these in custom exceptions.**

```python
import bentoml
from bentoml.exceptions import InvalidArgument, BentoMLException
from http import HTTPStatus

# Define a custom exception for method not allowed errors
class MyCustomException(BentoMLException):
    error_code = HTTPStatus.METHOD_NOT_ALLOWED

# Define a simple custom exception for invalid argument errors
class MyCustomInvalidArgsException(InvalidArgument):
    pass


@bentoml.service
class MyService:

    @bentoml.api
    def test1(self, text: str) -> str:
        # Raise the custom method not allowed exception
        raise MyCustomException("This is a custom error message.")

    @bentoml.api
    def test2(self, text: str) -> str:
        # Raise the custom invalid argument exception
        raise MyCustomInvalidArgsException("This is a custom error message.")
```

For more information, see exception APIs.

---

## tool-swap notes

Everything above is BentoML's. Everything below is ours.

### 1. ⚠️ **"BentoML reserves … any above 500" collides with our contract — and the source explains why**

Our contract uses **503** in two distinct senses:

- `/ready` returns `503 {"ready": false, "reason": "loading"}` while weights load ([`05 §3.2`](../../05_RUNTIME_AND_BATCHING.md:148));
- the router returns 503 `TOOL_UNAVAILABLE` on cold-start queue timeout ([`04_API_CONTRACT.md`](../../04_API_CONTRACT.md) §6, [`09 M3`](../../09_IMPLEMENTATION_PLAN.md:115)).

BentoML reserves ≥500 for itself, and [`health-endpoints-and-lifecycle-source.md`](health-endpoints-and-lifecycle-source.md) §7 shows the enforcement:

```python
elif status >= 500:
    detail = {"error": "An unexpected error has occurred, please check the server log."}
```

**Any exception carrying a ≥500 code has its message replaced with a fixed string.** So a custom exception meaning *"the model is still loading"* or *"this tool is saturated"* would reach the router as an unexplained 503. That is precisely the failure guardrail 6 exists to prevent, and it would be diagnosed as "the tool is broken" rather than "the tool is busy".

**Three consequences for M4, and they are cheap:**

1. **Our `/ready` is a mounted ASGI route, not a `@bentoml.api`**, so it never passes through this handler and can return its 503 with `reason` and `detail` intact. The design already sidesteps the restriction — worth stating explicitly in `bentoml_backend.py` so nobody "simplifies" `/ready` into a service API later.
2. **Errors on the `/predict` path must not rely on a ≥500 status to carry meaning.** Our envelope puts the machine-readable code in the **body** ([`04 §6`](../../04_API_CONTRACT.md)), which survives; keep it that way and never encode meaning only in the status.
3. **`ServiceUnavailable("process is overloaded")` loses its message this way** ([`health-endpoints-and-lifecycle-source.md`](health-endpoints-and-lifecycle-source.md) §6). To distinguish saturation from cold start at the router, the adapter must catch it *before* BentoML's handler and re-emit it in our envelope.

### 2. `InvalidArgument` is the right base for validation failures — but ours fire above the seam

`InvalidArgument` maps to 400, which matches our `INVALID_INPUT`. But our predict wrapper validates **above the seam** ([`05 §2`](../../05_RUNTIME_AND_BATCHING.md)) and produces our envelope directly, so the framework's exception classes are not on our error path at all.

That is the correct arrangement under [`05 §2.4`](../../05_RUNTIME_AND_BATCHING.md:131) rule 2 — *"no BentoML type in any signature above the seam"* — and `bentoml.exceptions` is one more symbol confined to `backends/bentoml_backend.py` by the import-linter rule ([`08_REPO_LAYOUT.md`](../../08_REPO_LAYOUT.md) §5). Noted because subclassing `BentoMLException` is the documented, obvious thing to do, and doing it in the wrapper would breach the seam for no gain.

### 3. **This page says nothing about per-item failure within a batch — the `retry_singly` gap**

[`05 §4`](../../05_RUNTIME_AND_BATCHING.md) and [`09 M4`](../../09_IMPLEMENTATION_PLAN.md:161) require that one bad item in a batch fails **alone**, attributed to its own caller, with the rest served normally. Nothing here, on [`adaptive-batching.md`](adaptive-batching.md), or in the dispatcher wiring read in [`health-endpoints-and-lifecycle-source.md`](health-endpoints-and-lifecycle-source.md) §6 describes per-item error semantics. The dispatcher's documented failure mode is whole-batch (`ServiceUnavailable` on latency overrun).

**The reasonable reading is that an exception raised inside a batched handler fails the whole batch** — every caller in it receives the error. That is exactly why `retry_singly` exists on our side: catch the batch failure, re-run the items individually, and attribute each failure to its own caller. R8's design had the same instinct ([`12_REFERENCE_CODE.md`](../../12_REFERENCE_CODE.md) §5, per-item validation).

**This is an assumption, not a documented fact.** Add it to M3.5 step 4: send a batch containing one poisoned item and observe whether the other callers get results or errors. If whole-batch failure is confirmed, `retry_singly` is load-bearing rather than a nicety, and its cost — one retry pass per failed batch — is justified. If BentoML isolates per item, we may need less machinery. Either way it should be measured before M4 builds on the guess.

### 4. **The page's brevity is itself the finding: error handling is largely ours**

One concept, one code sample, no discussion of error bodies, retries, partial failure, timeouts or client-visible shapes. Compare what [`04_API_CONTRACT.md`](../../04_API_CONTRACT.md) §6 specifies: a structured envelope, a code vocabulary, a code→HTTP mapping, a `reason` field on `TOOL_UNAVAILABLE`, and `Retry-After`.

This is **D14** behaving exactly as designed — we bought a batching engine and a worker model, not an error contract. It also means the error surface is **entirely ours to own**, so nothing here constrains [`04 §6`](../../04_API_CONTRACT.md) except the ≥500 rule in note 1. Recorded so that a future reader does not go looking for a richer framework error model that does not exist.
