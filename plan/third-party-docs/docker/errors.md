# docker-py — `docker.errors`: class names and hierarchy

**Source:** installed `docker` package **7.2.0** (source read, not online docs):
`.venv/lib/python3.11/site-packages/docker/errors.py` (whole file, 210 lines).

**Captured:** 2026-09-14, for M2a behaviours 14–26.

---

## 1. The hierarchy **[READ]**

```
Exception
└── DockerException                      errors.py:13 — "catch all errors that
                                         the Docker SDK might raise"
    ├── APIError(requests.exceptions.HTTPError)   :42
    │   ├── NotFound                      :92
    │   └── ImageNotFound(NotFound)       :96
    ├── InvalidVersion                    :100
    ├── InvalidRepository                 :104
    ├── InvalidConfigFile                 :108
    ├── InvalidArgument                   :112
    ├── DeprecatedMethod                  :116
    ├── TLSParameterError                 :120
    ├── NullResource(ValueError)          :131
    ├── ContainerError                    :135
    ├── BuildError                        :158
    ├── ImageLoadError                    :165
    ├── MissingContextParameter           :180
    ├── ContextAlreadyExists              :188
    ├── ContextException                  :196
    └── ContextNotFound                   :204

RuntimeError └── StreamParseError         :153   (NOT a DockerException)
```

Key shape facts:

- **`APIError` inherits from `requests.exceptions.HTTPError`** (line 42).
  Catching it also requires `requests` in scope; it carries
  `.response` (the raw `requests.Response`) and `.explanation` (the daemon's
  `message` field, extracted in `create_api_error_from_http_exception`,
  lines 22–39).
- **`ContainerError` is a `DockerException`, not an `APIError`** — it is
  raised client-side by `run(detach=False)` when the exit code is non-zero
  (see [`containers-run-create.md`](containers-run-create.md) §3). Its
  attributes: `container`, `exit_status`, `command`, `image`, `stderr`
  (lines 139–145).
- **`StreamParseError` is a plain `RuntimeError`** (line 153) — a stream
  parse failure will NOT be caught by `except DockerException`.
- `NullResource` is also a `ValueError` (line 131) — raised by
  `@utils.check_resource` guards when `None`/empty is passed as a container
  id (decorator in `utils/decorators.py`).

## 2. Which call raises which (the load-bearing table)

Assembled from the docstrings of the model-layer methods
(`models/containers.py`, `models/resource.py`) — all **[READ]**:

| Call | Raises | Where stated |
| --- | --- | --- |
| `containers.run(..., detach=False)` | `ContainerError` (non-zero exit), `ImageNotFound` (image missing and auto-pull fails), `APIError` | run docstring, containers.py:842–849 |
| `containers.run(..., detach=True)` | `ImageNotFound`, `APIError` — **never** `ContainerError` (it never waits) | same |
| `containers.create(...)` | `ImageNotFound` (no auto-pull), `APIError` | create docstring, :924–928 |
| `containers.get(name_or_id)` | `NotFound`, `APIError` | get docstring, :949–952 |
| `containers.list(...)` | `APIError`; plus `NotFound` **re-raised** if a container disappears during the per-item inspect and `ignore_removed=False` | list docstring :1006–1008; code :1021–1023 |
| `container.start()` / `stop()` / `kill()` / `remove()` / `restart()` | `APIError` | docstrings :417–421, :449–451, :287–289, :364–367, :406–409 |
| `container.wait(timeout=…)` | `requests.exceptions.ReadTimeout` (client-side timeout), `APIError` | wait docstring :523–527 |
| `container.logs(...)` | `APIError`; plus `InvalidArgument` (client-side) for bad `since`/`until` values, `InvalidVersion` for `until` on API < 1.35 | api/container.py:872–892 |
| `container.reload()` | `NotFound` (delegated to `get`), `APIError` | `Model.reload`, models/resource.py:42–48 |
| `client.images.pull(...)` | `APIError` | (api layer) |

### The 404 mapping **[READ]** — errors.py:22–39, :32–38

Every non-2xx HTTP response becomes an `APIError` via
`create_api_error_from_http_exception`. On **404**, the daemon's
`message` text decides the subclass:

- message contains any of `no such image` / `not found: does not exist or no
  pull access` / `repository does not exist` / `was found but does not match
  the specified platform` (lowercased) → **`ImageNotFound`**
- any other 404 → **`NotFound`**

So "image missing" and "container missing" are distinguished **by string
matching on the daemon's message**, which is why the docstrings can promise
`ImageNotFound` from `create`/`run`. If the daemon wording ever changes, the
mapping silently falls through to `NotFound` — a catch of `ImageNotFound`
alone would then miss the case.

### `APIError` conveniences **[READ]** — errors.py:73–89

`err.status_code` (property, `None` when built without a response),
`err.is_client_error()` (4xx), `err.is_server_error()` (5xx),
`err.is_error()`. `str(err)` appends the daemon's `explanation`.

## 3. What is NOT in `docker.errors`

There is **no** `DockerUnavailableError`, `ConnectionError` subclass, or
"daemon not running" exception in `docker.errors` **[READ]**. An unreachable
daemon surfaces as a **`requests` exception** (e.g. `requests.exceptions.
ConnectionError` from the underlying `requests` session, wrapped by the
transport layer) — **not** as a `DockerException`. Behaviours that catch
"daemon down" must catch the `requests` hierarchy (or `OSError`) explicitly.
This was verified by reading the full file (210 lines, no other classes).
