# docker-py — `ContainerCollection.run()` / `create()`

**Source:** installed `docker` package **7.2.0** (source read, not online docs):
`.venv/lib/python3.11/site-packages/docker/models/containers.py`
- `ContainerCollection.run` — line 535
- `ContainerCollection.create` — line 914
- `RUN_CREATE_KWARGS` — line 1033
- `RUN_HOST_CONFIG_KWARGS` — line 1056
- `_create_container_args` — line 1123

**Captured:** 2026-09-14, for M2a behaviours 14–26 (`build_run_kwargs`, `DockerBackend`).
**Re-verified:** 2026-09-16 against the same installed 7.2.0 tree. All five line citations
above resolved **exactly**; every kwarg name in §2 was re-read from the docstring and the
routing tables. §2's routing subsection was **filled in** — it had a heading and a conclusion
but no table (see **[CORRECTED 2026-09-16]** there), which mattered because `INDEX.md` names
`RUN_CREATE_KWARGS`/`RUN_HOST_CONFIG_KWARGS` the most drift-prone facts in this directory.

---

## 1. Signatures

```python
# models/containers.py:535
def run(self, image, command=None, stdout=True, stderr=False,
        remove=False, **kwargs): ...

# models/containers.py:914
def create(self, image, command=None, **kwargs): ...
```

`create`'s docstring (line 918): *"Takes the same arguments as `run`, except for
`stdout`, `stderr`, and `remove`."*

### Which call for a detached start

**[READ]** `run(..., detach=True)` is the right call for a detached start.
Implementation (lines 876–887): `run` = `self.create(...)` → `container.start()`
→ `if detach: return container`. It returns a `Container` **immediately after
start**, without waiting for exit. Consequences:

- `run(detach=True)` does **not** raise `ContainerError` even if the container
  exits with a non-zero code one second later — it never checks `wait()`.
- `run` **auto-pulls the image** if `create` raises `ImageNotFound`
  (lines 879–882: `self.client.images.pull(image, platform=platform)` then
  retries `create` once). **`create` does NOT pull** — it propagates
  `ImageNotFound`. A backend that wants a strict "image must pre-exist"
  contract must use `create` (plus explicit pull) and accept that `run`
  hides that failure mode.
- `create(...)` + `container.start()` is the two-phase alternative; it gives
  an explicit window to observe a failed `start` (`APIError`) before the
  container is expected to run, and skips the pull side effect.

### Client-side guards (raised before any daemon call) **[READ]**

| Condition | Raised | Line |
| --- | --- | --- |
| `network` and `network_mode` both given | `RuntimeError` | 864–868 |
| `networking_config` without `network` | `RuntimeError` | 870–874 |
| `detach=True` + `remove=True` on API < 1.25 | `RuntimeError`; on ≥ 1.25 silently converted to `auto_remove=True` | 857–862 |
| Any kwarg not in the known sets (see §3) | `TypeError` via `create_unexpected_kwargs_error` | 1123 ff. (`errors.create_unexpected_kwargs_error`, errors.py:169) |

A typo'd kwarg name (e.g. `env=` instead of `environment=`) therefore fails
fast with `TypeError`, not at the daemon.

## 2. The kwarg names we must pass (verbatim)

From the `run` docstring (lines 560–826) and the routing tables
(§3). **These are the exact names** — the architect's refusal to write them
into the plan is resolved here:

| Purpose | kwarg | Type / form (verbatim from docstring) |
| --- | --- | --- |
| Detached start | `detach` | bool; returns `Container` |
| Environment | `environment` | `dict` or list of `"KEY=VALUE"` strings |
| Labels | `labels` | `dict` of name→value, or `list` of bare names (empty values) |
| Network | `network` | str — network name at creation time. **Incompatible with `network_mode`** |
| Volumes (bind) | `volumes` | dict `{host_path_or_volume_name: {"bind": container_path, "mode": "rw"\|"ro"}}` or list of `"/host:/container"` strings |
| Mounts | `mounts` | `list[docker.types.Mount]` — *"More powerful alternative to `volumes`"* (line 676–679) |
| Device requests (GPU) | `device_requests` | `list[docker.types.DeviceRequest]` |
| Host devices | `devices` | list of `"<host>:<container>:<perms>"` strings |
| shm size | `shm_size` | `str or int` — *"Size of /dev/shm (e.g. `1G`)"* (line 757) |
| CPU quota | `cpu_quota` | int — *"Microseconds of CPU time that the container can get in a CPU period"*; pair with `cpu_period` (int, microseconds) or use `nano_cpus` (int, 1e-9 CPUs) |
| Memory limit | `mem_limit` | `int or str` — bytes, or string with unit char (`100000b`, `1000k`, `128m`, `1g`); unitless string = bytes (line 665–670). Also `mem_reservation` (soft), `memswap_limit` (mem+swap) |
| Published ports | `ports` | dict — container port (`2222/tcp` form, int, or `port/protocol` with `tcp`/`udp`/`sctp`) → host port int, `None` (random), `(address, port)` tuple, or list of ints (line 715–737). **Incompatible with `host` network mode** |
| Name | `name` | str |
| Container command | `command` (positional 2nd arg) | str or list |
| Entrypoint override | `entrypoint` | str or list |
| Restart policy | `restart_policy` | dict `{"Name": "on-failure"\|"always", "MaximumRetryCount": int}` (line 744–752). Note: docstring names are `on-failure`/`always` — no `no`/`unless-stopped` listed; the daemon accepts more, but the SDK only documents two |
| Stop signal | `stop_signal` | str, e.g. `SIGINT` |
| Auto-remove | `auto_remove` | bool |
| TTY | `tty` | bool |
| User | `user` | str or int |
| Working dir | `working_dir` | str |

Also available and relevant to tool images: `cap_add` / `cap_drop` (list of
str), `security_opt` (list), `read_only` (bool), `pids_limit` (int), `tmpfs`
(dict), `ulimits` (list of `docker.types.Ulimit`), `stop_signal`, `healthcheck`
(dict), `log_config` (`docker.types.LogConfig`).

### How kwargs are routed (why the names matter) **[READ]**

**[CORRECTED 2026-09-16]** This subsection previously held only the heading and
the closing sentence — the table it refers to was absent, so §2's claim that
the names are "the exact names" rested on nothing a reviewer could check. The
routing is read from `_create_container_args` (lines 1123–1182) and the two
module-level lists.

`_create_container_args(kwargs)` splits one flat kwargs dict into the two
halves the API layer wants, in this order (lines 1127–1165):

| Step | Code | Effect |
| --- | --- | --- |
| 1 | lines 1129–1131 | Every key in **`RUN_CREATE_KWARGS`** (line 1033) is **popped** into `create_kwargs` |
| 2 | lines 1133–1135 | Every key in **`RUN_HOST_CONFIG_KWARGS`** (line 1056) is **popped** into `host_config_kwargs` |
| 3 | lines 1138–1140 | `ports` → `host_config_kwargs['port_bindings']` — **only if truthy**; an empty dict is dropped |
| 4 | lines 1142–1144 | `volumes` → `host_config_kwargs['binds']` — **only if truthy** |
| 5 | lines 1146–1158 | `network` → `create_kwargs['networking_config'] = {network: None}` **and** `host_config_kwargs['network_mode'] = network` — one kwarg, two destinations |
| 6 | lines 1162–1163 | **Anything left raises `TypeError`** via `create_unexpected_kwargs_error('run', kwargs)` |
| 7 | line 1165 | `create_kwargs['host_config'] = HostConfig(**host_config_kwargs)` |
| 8 | lines 1168–1181 | `ports`/`volumes` are *additionally* back-filled into `create_kwargs` as the exposed-port list and the container-path list |

**The routing destination of every kwarg `build_run_kwargs` emits** — the set
that matters for behaviours 14–18, each verified present in the named list:

| Our kwarg | List it is in | Line | Goes to |
| --- | --- | --- | --- |
| `image` | `RUN_CREATE_KWARGS` | 1041 | create |
| `name` | `RUN_CREATE_KWARGS` | 1044 | create |
| `command` | `RUN_CREATE_KWARGS` | 1034 | create |
| `detach` | `RUN_CREATE_KWARGS` | 1035 | create |
| `environment` | `RUN_CREATE_KWARGS` | 1038 | create |
| `labels` | `RUN_CREATE_KWARGS` | 1042 | create |
| `mounts` | `RUN_HOST_CONFIG_KWARGS` | 1097 | host_config |
| `device_requests` | `RUN_HOST_CONFIG_KWARGS` | 1079 | host_config |
| `shm_size` | `RUN_HOST_CONFIG_KWARGS` | 1109 | host_config |
| `cpu_quota` | `RUN_HOST_CONFIG_KWARGS` | 1067 | host_config |
| `cpu_period` | `RUN_HOST_CONFIG_KWARGS` | 1066 | host_config |
| `nano_cpus` | `RUN_HOST_CONFIG_KWARGS` | 1098 | host_config |
| `mem_limit` | `RUN_HOST_CONFIG_KWARGS` | 1093 | host_config |
| `runtime` | `RUN_HOST_CONFIG_KWARGS` | 1119 | host_config |
| `network_mode` | `RUN_HOST_CONFIG_KWARGS` | 1099 | host_config |
| `volumes` | **neither list** — special-cased | 1142 | host_config as `binds` (+ create as `volumes`) |
| `ports` | **neither list** — special-cased | 1138 | host_config as `port_bindings` (+ create as `ports`) |
| `network` | **neither list** — special-cased | 1146 | create as `networking_config` **and** host_config as `network_mode` |

**Three consequences for `build_run_kwargs`, all [READ]:**

1. **`volumes` and `ports` are dropped when falsy** (lines 1139, 1143 test
   truthiness, not presence). Emitting `ports={}` is therefore *equivalent to*
   omitting it — but behaviours 15 and 18 should still omit the key, since
   equivalence at this layer is not a contract and a snapshot test that pins
   the omission is the stricter assertion.
2. **`network` is not a pass-through.** Passing it also sets `network_mode`
   internally, which is exactly why passing **both** is rejected at `run`
   (line 864). `build_run_kwargs` must emit `network` **or** `network_mode`,
   never both.
3. **`runtime` is a host-config kwarg** (line 1119). If `gpu_runtime` is ever
   translated to `runtime=` rather than to a `DeviceRequest(driver=…)`, that
   is the name and it is accepted — but the two are different mechanisms, and
   behaviour 16 must pick one deliberately. Note `DeviceRequest`'s own
   `driver` field is the nvidia hook (see
   [`gpu-device-requests.md`](gpu-device-requests.md)).

Leftover kwargs → `TypeError`. **There is no `**rest` passthrough to the
daemon**: every kwarg of `run`/`create` must be one docker-py knows.

## 3. What `run` does after start (the `detach=False` path) **[READ]**

Lines 886–912: reads the container's logging driver from
`attrs['HostConfig']['LogConfig']['Type']`; only streams logs if the driver is
`json-file` or `journald` (otherwise returns `None`); calls `container.wait()`
→ `{'StatusCode': N}`; on `N != 0` captures stderr and raises
`ContainerError`; `remove=True` deletes the container before raising.
`run` returns `b''.join(out)` (bytes) by default, or a generator when
`stream=True`.

**Surprising / load-bearing for behaviours 14–26:**

- **`run(detach=True)` + a bad command does not raise.** The backend must
  poll `status`/`wait` itself (or use `create`+`start` and then check).
- **`run` mutates the world**: it may pull an image. `create` is side-effect
  free apart from the container record.
- **`detach` is itself forwarded to the API layer** (it is in
  `RUN_CREATE_KWARGS`, line 1035) — the model-level `detach` does double duty.
- `stdout`/`stderr` defaults differ between the two read paths: `run` defaults
  `stdout=True, stderr=False` (signature), but `Container.logs` / `API.logs`
  default `stdout=True, stderr=True` (see [`container-logs.md`](container-logs.md)).
  Do not rely on implicit stderr capture from `run`.

## 4. Returns / raises (verbatim)

- `run` (line 828–849): returns logs (or `Container` if `detach=True`); raises
  `ContainerError` (non-zero exit, `detach=False`), `ImageNotFound` (image
  missing *and* the auto-pull also fails), `APIError` (server error).
- `create` (line 921–928): returns `Container`; raises `ImageNotFound`,
  `APIError`.
- `get` (line 950–952): raises `NotFound` if the container does not exist.
