# docker-py — `container.attrs`, `reload()`, and where state lives

**Source:** installed `docker` package **7.2.0** (source read, not online docs):
- `Model` (base class: `attrs`, `id`, `reload`) — `.venv/lib/python3.11/site-packages/docker/models/resource.py:1–48`
- `Container` properties over `attrs` — `.venv/lib/python3.11/site-packages/docker/models/containers.py:20–83`
- `ContainerCollection.get` — `models/containers.py:939`

**Captured:** 2026-09-14, for M2a behaviours 14–26.

---

## 1. `attrs` is a **cached** snapshot **[READ]**

`Model.__init__` (models/resource.py:7–17) stores `self.attrs = attrs` —
*the raw dict returned by the daemon's inspect*. The `Container` class
docstring (models/containers.py:20–26) is explicit:

> *"Note that local attributes are cached; users may call `reload` to query
> the Docker daemon for the current properties, causing `attrs` to be
> refreshed."*

**Nothing in the SDK refreshes `attrs` automatically.** After `start()`,
`stop()`, or time passing, the object still carries the inspect from
whenever it was created (`create`/`get`/`list`). Every state read below must
be preceded by `container.reload()` (or a fresh `client.containers.get(id)`).

## 2. `reload()` **[READ]**

`Model.reload` (models/resource.py:42–48):

```python
def reload(self):
    new_model = self.collection.get(self.id)
    self.attrs = new_model.attrs
```

- Delegates to `ContainerCollection.get(self.id)` (models/containers.py:939),
  i.e. a full `inspect_container` call, then **replaces** `self.attrs` with
  the new dict (same object identity is kept for `self`, contents swapped).
- Raises `NotFound` (via `get`) if the container no longer exists, and
  `APIError` on transport/server errors.
- Return value: `None`.

## 3. Where state, exit code and start time live **[READ where the SDK says; INFERRED flagged]**

The SDK exposes only some `State` fields as properties (models/containers.py):

| Property | SDK line | Reads |
| --- | --- | --- |
| `container.status` | :59–67 | `self.attrs['State']['Status']` (string, e.g. `running`, `exited`) — with a legacy fallback to `self.attrs['State']` being a string (line 65–67) |
| `container.health` | :69–76 | `self.attrs['State']['Health']['Status']`, defaulting to `'unknown'` when absent |
| `container.name` | :28–34 | `self.attrs['Name'].lstrip('/')` |
| `container.labels` | :47–58 | `self.attrs['Config']['Labels']` — **raises `DockerException` on sparse objects** (i.e. from a `list(sparse=True)` without `reload()`, line 54–58) |
| `container.ports` | :78–83 | `self.attrs['NetworkSettings']['Ports']` |
| `container.id` / `.short_id` | resource.py:28–40 | `attrs['Id']` / first 12 chars |

**Exit code and start time are NOT properties.** The SDK never references
`State.ExitCode` or `State.StartedAt` in the model layer (verified by grep
over the package: the only `ExitCode` references in the SDK are
`exec_inspect`'s at models/containers.py:222 and the `wait()` response).
They live in the **raw inspect dict**, per the Engine API's `ContainerInspect`
shape:

- `attrs['State']['ExitCode']` — int; `0` while running / never exited
- `attrs['State']['StartedAt']` — RFC 3339 timestamp string (e.g.
  `"2026-09-14T19:40:00.123456789Z"`), `"0001-01-01T00:00:00Z"` before first
  start

These two field names come from the **Engine API schema, not from the SDK
source** — **[INFERRED from the Engine API contract; the SDK source neither
documents nor contradicts them]**. The SDK's own `run()` implementation
reads the exit code from `container.wait()['StatusCode']` instead
(models/containers.py:897), which is the *daemon wait response*, not an
inspect field. **Behaviour 14+ should read the exit code from
`wait()['StatusCode']` for the "did it exit" check and from
`attrs['State']['ExitCode']` (post-`reload()`) for persistent state — and
the first live-daemon test should print one real `inspect` to confirm the
exact keys, per this repository's no-guessing rule.**

Other fields in the same `State` dict the Engine API defines (not SDK
documented, **[INFERRED]**): `Running`, `Paused`, `Restarting`,
`Dead`, `Pid`, `ErrorMessage`, `FinishedAt`.

## 4. Consequence for the backend seam

- `status` is the *only* state the SDK gives you as a clean property; it is a
  coarse string, and it is **stale without `reload()`**.
- A "poll until running/exited" loop is: `container.reload()` → read
  `container.status` (or `attrs['State']['Running']`) → `sleep`. There is no
  watch/subscribe primitive in the SDK.
- `container.attrs` after `reload()` is a plain `dict` — safe to
  `copy.deepcopy` / log / assert in tests.
