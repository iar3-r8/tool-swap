# docker-py — `ContainerCollection.list()` and label filters

**Source:** installed `docker` package **7.2.0** (source read, not online docs):
`.venv/lib/python3.11/site-packages/docker/models/containers.py`
- `ContainerCollection.list` — line 958
- `ContainerCollection.get` — line 939
- `Container.labels` property — line 47

**Captured:** 2026-09-14, for M2a behaviours 14–26 (reaping by label).

---

## 1. Signature **[READ]**

```python
def list(self, all=False, before=None, filters=None, limit=-1, since=None,
         sparse=False, ignore_removed=False): ...
```

Returns `list[Container]`.

## 2. Stopped containers: yes, an explicit `all` flag is required **[READ]**

Docstring (lines 963–965): *"all (bool): Show all containers. **Only running
containers are shown by default**."* So:

- `client.containers.list()` → running only.
- `client.containers.list(all=True)` → running + exited + paused + …
- There is **no `all=` in the label-filter dict** — `all` is a separate
  positional/keyword parameter, not a `filters` key. The filter dict cannot
  substitute for it.

The call is passed straight through to the API layer
(`self.client.api.containers(all=all, ...)`, line 1010–1012).

## 3. The `filters` dict and the label form **[READ]**

`filters` (dict) is documented at lines 972–992. Available keys (verbatim):

| Key | Value form | Verbatim |
| --- | --- | --- |
| `exited` | int | *"Only containers with specified exit code"* |
| `status` | str | One of `restarting`, `running`, `paused`, `exited` |
| `label` | **str or list** | format either `"key"`, `"key=value"` or a list of such |
| `id` | str | *"The id of the container."* |
| `name` | str | *"The name of the container."* |
| `ancestor` | str | `<image-name>[:tag]`, `<image-id>`, or `<image@digest>` |
| `before` / `since` | str | container name or id |

The docstring ends: *"A comprehensive list can be found in the documentation
for `docker ps`."* — the SDK's list is illustrative, and the **daemon** is the
authority on which filter keys/values it accepts.

**Label-filter forms (all three shown in the docstring):**

```python
client.containers.list(all=True, filters={"label": "tswap.owner=me"})
client.containers.list(all=True, filters={"label": ["a=1", "b=2"]})  # AND semantics at the daemon
client.containers.list(filters={"label": "tswap"})  # key only
```

The SDK performs **no client-side interpretation** of `filters` — it is
serialized and sent to the daemon. Whether `"a=1", "b=2"` is AND or OR, and
what a bare `"key"` matches, is daemon behaviour, not SDK behaviour.

## 4. `sparse` / `ignore_removed` — relevant to reaping races **[READ]**

- `sparse=True` (line 994–997): *"Do not inspect containers. Returns partial
  information, but guaranteed not to block. Use `Container.reload` on resulting
  objects to retrieve all attributes."* With `sparse=True` the `labels`
  property raises `DockerException` until `reload()` is called (line 54–58).
  concurrently-removed container bites:
- `ignore_removed=False` (default): if a container vanished between the list
  call and its inspect, `NotFound` is **raised** (line 1021–1023).
  `ignore_removed=True` swallows it: *"Set to `True` if race conditions are
  likely."* A reaper that lists and then acts must set `ignore_removed=True`
  or catch `NotFound` — this is the documented remedy.

## 5. Getting one container by name **[READ]**

`client.containers.get(container_id)` (line 939) accepts a name or ID,
performs a full inspect, and raises `NotFound` if missing (line 950–952).
`client.containers.get` is the same call `list()` uses internally
(line 1019), so its `NotFound` behaviour is the one to catch.
