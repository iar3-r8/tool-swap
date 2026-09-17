# docker-py — GPU device requests (`docker.types.DeviceRequest`)

**Source:** installed `docker` package **7.2.0** (source read, not online docs):
`.venv/lib/python3.11/site-packages/docker/types/containers.py`
- `class DeviceRequest(DictType)` — line 166, `__init__` at line 187

**Captured:** 2026-09-14, for M2a behaviours 14–26.
**Re-verified:** 2026-09-16 against the same installed 7.2.0 tree — **no correction needed**.
`class DeviceRequest(DictType)` is at types/containers.py:166 and `__init__` at :187, as
cited. Every default and every `ValueError` type-check re-read at :194–213; the five
PascalCase wire keys at :215–221; the snake/Pascal dual spellings at :188–192. The
`count` vs `device_ids` docstring constraint is at :176–177 and is still **not** enforced in
code. The export was additionally confirmed: `DeviceRequest` is named in
`types/__init__.py:1`, so `docker.types.DeviceRequest` resolves — and the import-path
caution in §2 holds (`grep -rn "class DeviceRequest"` matches only types/containers.py).

---

## 1. Constructor arguments (verbatim from the docstring, lines 166–185)

```python
DeviceRequest(driver=None, count=None, device_ids=None,
              capabilities=None, options=None)
```

All arguments are **keyword arguments** (`__init__(self, **kwargs)`, line 187).
Both snake_case and PascalCase spellings are accepted (`count`/`Count`,
`device_ids`/`DeviceIDs`, `capabilities`/`Capabilities`, `driver`/`Driver`,
`options`/`Options` — lines 188–192). The wire dict keys are the PascalCase
ones: `Driver`, `Count`, `DeviceIDs`, `Capabilities`, `Options` (lines 215–221).

| Argument | Type | Default | Verbatim doc |
| --- | --- | --- | --- |
| `driver` | str | `''` (empty string) | *"Which driver to use for this device. Optional."* |
| `count` | int | `0` | *"Number of devices to request. Set to -1 to request all available devices."* |
| `device_ids` | list of str | `[]` | *"List of strings for device IDs."* |
| `capabilities` | list of lists of str | `[]` | *"The global list acts like an OR, and the sub-lists are AND. The driver will try to satisfy one of the sub-lists."* |
| `options` | dict | `{}` | *"Driver-specific options."* |

Type validation (lines 194–213): wrong type raises `ValueError`
(`DeviceRequest.count must be an integer`, etc.) — **not** a docker exception.

### Mutually exclusive / constraint **[READ]**

- `count` vs `device_ids`: docstring (line 176–177): *"Set either `count` or
  `device_ids`."* The SDK **does not enforce this client-side** — it happily
  sends both. Enforcement is the daemon's.
- Canonical GPU form (inferred from the arguments, **not** documented by the
  SDK; the docstring only links the nvidia driver's capability list at
  github.com/NVIDIA/nvidia-container-runtime, line 182–183):
  `DeviceRequest(driver='nvidia', device_ids=[...])` for specific devices, or
  `device_ids=['all']` / `count=-1` for all. **`'all'` is a daemon-side
  convention, not an SDK constant — verify against the daemon in behaviour 14+
  tests rather than assuming it.**

## 2. How it reaches the daemon **[READ]**

`device_requests` is in `RUN_HOST_CONFIG_KWARGS`
(`models/containers.py` line 1079), so it is accepted by **both**
`client.containers.run(...)` and `create(...)` as a **list of `DeviceRequest`
instances**:

```python
client.containers.run(
    image, ...,
    device_requests=[docker.types.DeviceRequest(driver='nvidia', count=1)],
)
```

`DeviceRequest` is exported from `docker.types`
(`types/containers.py` defines it; `docker.types.__init__` re-exports it).

**Import path note:** the class lives in `docker/types/containers.py`, *not*
`docker/types/services.py`. Do not import it from the wrong module.
