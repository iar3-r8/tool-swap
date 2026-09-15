# docker-py — `Container.stop()` and `Container.wait()`

**Source:** installed `docker` package **7.2.0** (source read, not online docs):
- `Container.stop` — `.venv/lib/python3.11/site-packages/docker/models/containers.py:441`
- `APIClient.stop` — `.venv/lib/python3.11/site-packages/docker/api/container.py:1187`
- `Container.wait` — `models/containers.py:508`
- `APIClient.wait` — `api/container.py:1315`

**Captured:** 2026-09-14, for M2a behaviours 14–26.

---

## 1. `container.stop()`

### Argument name and units **[READ]**

- `Container.stop(**kwargs)` (models/containers.py:441) → forwards to
  `self.client.api.stop(self.id, **kwargs)` (line 453). The model docstring
  documents one kwarg: **`timeout (int)` — "Timeout in **seconds** to wait for
  the container to stop before sending a `SIGKILL`. Default: 10"** (lines
  446–447).
- The API signature is explicit (api/container.py:1187):
  `def stop(self, container, timeout=None)`. The **API-level default is
  `None`, not 10** — and the code (lines 1202–1204) does:
  `if timeout is None: params = {}; timeout = 10` — i.e. when you pass
  nothing, **no `t` parameter is sent at all** and the *daemon's own
  configured StopTimeout* applies; the `10` is only used to bound the
  **client-side HTTP request timeout** (`conn_timeout += timeout`, line
  1208–1210). Passing an explicit `timeout=N` sends `params={'t': N}`
  (line 1206) and extends the HTTP timeout by N seconds.

  So: **the model docstring's "Default: 10" and the API code disagree** —
  omitting `timeout` means "daemon default", not "10 s" **[READ, both
  docstrings and code]**. Always pass `timeout` explicitly if a bound matters.

### Does it return before the container has exited? **[READ]**

**No.** `APIClient.stop` POSTs to `/containers/{id}/stop` with
`params={'t': timeout}` and blocks until the daemon responds (line 1207–1212).
Per the Engine API that endpoint only returns **after the container has
stopped** (this is daemon semantics — docker-py's code simply waits for the
HTTP response and has no early-return path; the only documented return value
is none). The method:

- returns `None` on success (no `return` statement, line 1187–1212);
- raises `APIError` on a non-2xx response (`self._raise_for_status(res)`,
  line 1212);
- takes up to `timeout` + the client's base `self.timeout` as HTTP timeout.

The only way to get an explicit exit code is `container.wait()` (below) or
re-reading `attrs['State']['ExitCode']` after `reload()`.

### Interaction with restart policies **[INFERRED — flagged]**

docker-py says nothing in `stop` about restart policies. Docker Engine
semantics (from the daemon side, not the SDK) are that `stop` on a container
with an `always`/`on-failure` restart policy can be re-started by the daemon
after the stop completes. The SDK does not guard against this. Verify against
the daemon in behaviour 14+ tests; do not rely on `stop()` giving a
permanent stop when a restart policy is set.

## 2. `container.wait()` **[READ]**

- `Container.wait(**kwargs)` (models/containers.py:508) → `api.wait(self.id,
  **kwargs)` (line 529). Kwarg: **`timeout (int)`** — but here it is the
  **HTTP request timeout** (api/container.py:1323), *not* a stop timeout.
- API signature (api/container.py:1315): `def wait(self, container,
  timeout=None, condition=None)`.
- **`condition` (str)**: one of `"not-running"` (default), `"next-exit"`, or
  `"removed"`; requires **API version ≥ 1.30** — raises `InvalidVersion`
  below that (lines 1340–1345).
- **Returns a dict**, not an int: *"The API's response as a Python
  dictionary, including the container's exit code under the `StatusCode`
  attribute"* (lines 1328–1330). Usage: `container.wait()['StatusCode']` —
  exactly how `run` itself does it (models/containers.py:897).
- Raises `requests.exceptions.ReadTimeout` if the request timeout is
  exceeded (line 1333–1334) and `APIError` on server error.

## 3. The one deprecation found in the container API **[READ]**

`api/container.py:1106` — `start()` carries a deprecation warning: passing
configuration options to `start` is deprecated and raises
`errors.DeprecatedMethod` (line 1129). This is the **only**
`DeprecationWarning`/`DeprecatedMethod` site in the three container files
(verified by grep over `models/containers.py`, `types/containers.py`,
`api/container.py`). The `stop`/`wait`/`logs` paths are clean — importing
`docker` under `filterwarnings = ["error"]` did not surface any
`DeprecationWarning` (the full pytest suite, which imports the SDK, passed
with the zero-warning policy in place).
