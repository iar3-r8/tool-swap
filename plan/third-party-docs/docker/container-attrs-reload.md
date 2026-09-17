# docker-py — `container.attrs`, `reload()`, and where state lives

**Source:** installed `docker` package **7.2.0** (source read, not online docs):
- `Model` (base class: `attrs`, `id`, `reload`) — `.venv/lib/python3.11/site-packages/docker/models/resource.py:1–48`
- `Container` properties over `attrs` — `.venv/lib/python3.11/site-packages/docker/models/containers.py:20–83`
- `ContainerCollection.get` — `models/containers.py:939`

**Captured:** 2026-09-14, for M2a behaviours 14–26.
**Re-verified:** 2026-09-16 against the same installed 7.2.0 tree — the **[READ]** facts
resolved unchanged (`Model.__init__` at resource.py:7–17, `reload` at :42–48, `status` at
containers.py:60–67, `health` at :69–76, `name` at :28–34, `labels` at :46–58, `ports` at
:78–83, `id`/`short_id` at resource.py:28–40). The **[INFERRED]** exit-code/start-time
fields remain **[INFERRED]** and were re-confirmed as unciteable from SDK source; §3.1 now
states exactly how far the evidence goes, because **behaviour 24 depends on it**.

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

## 3.1 Exactly how far the evidence goes — read before writing behaviour 24

Added 2026-09-16, because behaviour 24 reads **state, exit code and start
time** from these paths and its tests must claim no more than is established.
**No Docker daemon was used, and none will be in M2a** — so this is the
ceiling, not a step toward one.

| Fact behaviour 24 needs | Status | What backs it |
| --- | --- | --- |
| `attrs` is the raw inspect dict, cached, refreshed only by `reload()` | **[READ]** | `Model.__init__` resource.py:7–17; `reload` :42–48; `Container` docstring containers.py:20–26 |
| **State** is readable as `container.status` | **[READ]** | containers.py:60–67 — returns `attrs['State']['Status']`, with a legacy branch for `attrs['State']` being a bare string |
| The *string values* `status` can take (`running`, `exited`, `created`, `paused`, `restarting`, `removing`, `dead`) | **[INFERRED]** | The SDK docstring names only *"`running`, or `exited`"* (containers.py:63) **as examples**. The full set is Engine-contract, and `containers.list`'s `status` filter names four (`restarting`, `running`, `paused`, `exited` — containers.py:976–977). **No SDK line enumerates all of them** |
| **Exit code** at `attrs['State']['ExitCode']` | **[INFERRED]** | Re-confirmed by grep over the whole installed package: the **only** `ExitCode` match is `exec_inspect`'s at containers.py:222, which is an **exec** result, not a container inspect. The SDK never reads a container's `State.ExitCode` |
| **Start time** at `attrs['State']['StartedAt']` | **[INFERRED]** | Re-confirmed by grep over the whole installed package: **zero** matches for `StartedAt` in any file. Nothing in the SDK references it at all |
| Exit code via `wait()['StatusCode']` | **[READ]** | The key is named in the `wait` docstring (containers.py:520–521, api/container.py:1329–1330) **and** consumed by the SDK's own `run` at containers.py:897 — this is the one exit-code path with SDK code behind it |

**What this means for behaviour 24's tests, concretely.** The stub client
returns canned attribute dicts, so the test author *chooses* the keys — which
means a test can pass while the real key name is wrong, and that is precisely
the failure this repository's no-guessing rule exists to prevent. Therefore:

1. **`ContainerState` mapping from `container.status` may be asserted as a
   contract** — the property and its `attrs['State']['Status']` path are
   `[READ]`. The *set* of input strings mapped is `[INFERRED]`, which is an
   argument for behaviour 24's "unknown state string maps to `EXITED` with a
   logged warning" edge case being the load-bearing one: it is what makes an
   incomplete string set safe rather than a crash.
2. **`State.ExitCode` and `State.StartedAt` must be treated as an assumption
   the test *documents*, not a fact it *proves*.** A test asserting
   "`inspect` reads `attrs['State']['ExitCode']`" proves only that our code
   reads the key our fixture wrote. It is still worth having — it pins our
   side against silent change — but its docstring must say it rests on the
   Engine API contract and cite this section, not claim SDK authority.
3. **Prefer `wait()['StatusCode']` wherever the exit code is needed at a
   moment the code controls**, since that key is `[READ]`. Reserve
   `attrs['State']['ExitCode']` for reading persistent state after `reload()`,
   where no `wait()` is available.
4. **The remaining gap is closable only by one live inspect**, which is
   deferred with §7 item 7's three daemon tests. Until then, no document in
   this directory may promote these two field names to `[READ]`.

## 4. Consequence for the backend seam

- `status` is the *only* state the SDK gives you as a clean property; it is a
  coarse string, and it is **stale without `reload()`**.
- A "poll until running/exited" loop is: `container.reload()` → read
  `container.status` (or `attrs['State']['Running']`) → `sleep`. There is no
  watch/subscribe primitive in the SDK.
- `container.attrs` after `reload()` is a plain `dict` — safe to
  `copy.deepcopy` / log / assert in tests.
