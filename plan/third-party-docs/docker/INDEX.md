# docker-py documentation — annotated catalogue

**Root URL:** https://docker-py.readthedocs.io
**docker-py version at capture:** **7.2.0** (installed in `.venv`, `docker==7.2.0`, `types-docker==7.2.0.20260827`)
**Captured:** 2026-09-14
**Confirmation pass:** 2026-09-16 — every page below re-checked against the **same installed
7.2.0 tree** before behaviour 14's first test was written, as `plans/m2a-container-backend-seam.md`
§3 requires. Four pages were corrected and one was added; see §5 for the record. No Docker
daemon was used in either pass.
**Extracted by:** direct source reads of the **installed package** at `.venv/lib/python3.11/site-packages/docker/` — one page per behaviour 14–26 needs, as required by [`plans/m2a-container-backend-seam.md`](../../../plans/m2a-container-backend-seam.md) §3 (pre-condition on behaviours 14–26, blocking). No online documentation was fetched: the installed source is authoritative for the SDK's own behaviour, and every fact below is tagged **[READ]** (with file:line) or **[INFERRED]** where it rests on the Engine API contract rather than SDK source.

This directory is the blocking pre-condition for M2a behaviours 14–26 (`build_run_kwargs` and the `DockerBackend`). Behaviours 14–26 must **cite these files** rather than recall interface details. No Docker daemon was used: nothing here was verified against a live daemon — only against the SDK code.

---

## 1. What was captured

| Local file | Source (docker 7.2.0) | What it supplies | Bears on |
| --- | --- | --- | --- |
| [`containers-run-create.md`](containers-run-create.md) | `models/containers.py` (`run` :535, `create` :914, kwarg routing :1033–1147) | The **exact kwarg names** for detach, environment, labels, network, volumes/mounts, device requests, shm size, CPU quota, memory limit, published ports; `run(detach=True)` vs `create`+`start`; the auto-pull side effect of `run`; the client-side `TypeError` on unknown kwargs | **behaviours 14–26, the whole of `build_run_kwargs`** |
| [`gpu-device-requests.md`](gpu-device-requests.md) | `types/containers.py` (`DeviceRequest` :166) | `DeviceRequest` constructor arguments (`driver`, `count`, `device_ids`, `capabilities`, `options`), defaults, type checks, the `count` vs `device_ids` "set either" constraint (not client-enforced) | GPU device-request tests |
| [`containers-list-filters.md`](containers-list-filters.md) | `models/containers.py` (`list` :958, `get` :939) | `list(all=False, filters=...)` — **`all` is a parameter, not a filter key**; the `label` filter forms (`"key"`, `"key=value"`, list); `sparse`/`ignore_removed` and the documented `NotFound` race | reaping by label |
| [`errors.md`](errors.md) | `errors.py` (whole file) | The full `DockerException` hierarchy; `APIError` ↔ `requests.HTTPError`; the 404 → `ImageNotFound`/`NotFound` **string-matching** rule; which call raises which; the absence of any "daemon unavailable" exception class | every error-mapping decision in the backend |
| [`container-stop-wait.md`](container-stop-wait.md) | `models/containers.py` :441/:508, `api/container.py` :1187/:1315 | `stop(timeout=…)` — **seconds**; `None` means *daemon's* StopTimeout, not 10; blocks until the daemon reports stopped; `wait()` returns a **dict** with `StatusCode`; `condition` values; the one deprecation found (`start` config options) | lifecycle transitions, the soft-unload path |
| [`container-logs.md`](container-logs.md) | `models/containers.py` :294, `api/container.py` :821, `api/client.py` :485 | `logs(stdout, stderr, stream, timestamps, tail, since, follow, until)` — **output is always `bytes`**; `follow` silently equals `stream`; default `tail='all'` is unbounded; `CancellableStream.close()` | log tailing / crash diagnosis |
| [`container-attrs-reload.md`](container-attrs-reload.md) | `models/resource.py` :42, `models/containers.py` :20–83 | `attrs` is a **cached** inspect snapshot; `reload()` = full re-inspect; `status`/`health` properties; **exit code and start time are raw `attrs['State']` fields, not SDK properties** (flagged INFERRED; **§3.1 states exactly how far the evidence goes — read it before behaviour 24**) | state polling, TTL/scheduling reads |
| [`client-construction-and-env.md`](client-construction-and-env.md) | `client.py` :50–161/:283–284, `api/client.py` :115–219, `utils/utils.py` :353, `utils/config.py` :13–48, `context/api.py` :136 | **Added 2026-09-16.** Every client-construction path that reads ambient state, enumerated (15 entry points, 6 env var names); the `from_env` **alias vs classmethod** split; `APIClient.__init__` reads `~/.docker/config.json`; **construction performs a live daemon handshake when `version is None`** | **behaviour 20's no-ambient-environment guard** |

---

## 2. What was not captured, and why

### Deliberately excluded

| Area | Why skipped |
| --- | --- |
| `docker.api.*` APIClient layer beyond the cited methods | The backend uses the model layer (`docker.from_env()`); the API layer appears here only where the model layer forwards to it (timeout, params, 404 mapping) |
| `docker.types.Mount` (documented in [`containers-run-create.md`](containers-run-create.md) §2 by docstring citation) | Its full source is `types/services.py:221` — captured only if behaviour 14+ actually builds `Mount` objects; the `volumes` dict form is the documented "simpler" path and the likely one |
| Image build/pull/push, networks, exec, swarm | Not in scope for the container backend seam |
| Engine API (daemon) semantics | The SDK source documents only the client side. Where a fact needed daemon semantics (restart-policy interaction with `stop`, the `DeviceRequest.device_ids=['all']` convention, `State` field names), it is tagged **[INFERRED]** and the first live-daemon test must confirm it |

### Relevant, not yet captured — the honest list

| Item | Why it matters |
| --- | --- |
| One **live** `inspect` of a real tool container (full JSON) | To confirm `State.ExitCode` / `State.StartedAt` key names and the `NetworkSettings.Ports` shape for a bound tool port — the one INFERRED set in this directory. Needs a daemon; **deferred with §7 item 7's three daemon tests, and explicitly not M2a's**. [`container-attrs-reload.md`](container-attrs-reload.md) §3.1 states what behaviour 24 may and may not claim without it |
| The full set of `State.Status` strings | The SDK docstring names `running`/`exited` as *examples* only, and the `list` filter names four. The complete Engine set is **[INFERRED]**; behaviour 24's "unknown state maps to `EXITED` with a warning" is what makes the gap safe |
| `docker/tls.py` — `TLSConfig` construction | Reached from `kwargs_from_env` when `DOCKER_TLS_VERIFY`/`DOCKER_CERT_PATH` are set. Not needed by behaviours 14–27 (the seam takes an injected client); capture if `from_config` ever grows TLS support |
| `images.pull(...)` progress stream | Only if the backend ever auto-pulls (the `run` path does — see [`containers-run-create.md`](containers-run-create.md)) |
| `docker.types.Mount` full source (`types/services.py:221`) | Only if behaviour 15 builds `Mount` objects rather than using the `volumes` dict form |

**Closed by the 2026-09-16 pass:** `docker.from_env()` / `DockerClient` construction, which
this list previously carried as *"capture in behaviour 3's cycle"* — it is now
[`client-construction-and-env.md`](client-construction-and-env.md), captured because
**behaviour 20 needs the enumerated entry points** to write a guard without holes.

---

## 3. Findings — what this capture changes (for behaviours 14–26)

1. **`run(detach=True)` hides crashes.** It returns before any exit check and **auto-pulls** a missing image. A strict backend wants `create` + `start` + explicit poll, and must not rely on `ContainerError` ever firing on the detached path.
2. **Kwarg names are enforced client-side.** `_create_container_args` raises `TypeError` on any unknown kwarg and routes `ports`→`port_bindings`, `volumes`→`binds`, `network`→both `networking_config` and `network_mode`. `build_run_kwargs` output is validated before any daemon call — the unit tests for it can assert the full kwarg surface without a daemon.
3. **`network` and `network_mode` are mutually exclusive** (`RuntimeError` at `run` :864); `ports` is incompatible with `host` mode (docstring). `networking_config` requires `network`.
4. **`stop(timeout=None)` means "daemon default", not 10 s** — the model docstring and the API code disagree; pass `timeout` explicitly. `stop` blocks until the daemon reports stopped and returns `None`; exit code comes from `wait()['StatusCode']` (a **dict**, not an int) or `reload()` + `attrs['State']['ExitCode']`.
5. **Logs are `bytes`, unbounded by default, and `follow` follows `stream`.** Any log-tailing code must decode and bound itself; `CancellableStream.close()` is the documented abort.
6. **`list()` needs `all=True` for stopped containers** (separate parameter, not a filter key), and the default non-sparse path raises `NotFound` on a race — `ignore_removed=True` is the documented remedy.
7. **404s are classed by string-matching the daemon's message** (`errors.py:32–38`). A catch of `ImageNotFound` alone can silently degrade to `NotFound` if daemon wording changes; catch `NotFound` (the parent) where either is acceptable.
8. **A dead daemon is *sometimes* a `DockerException` — corrected 2026-09-16.** No *class* for it exists, but **where** the daemon is found dead decides what propagates: during **client construction** with `version=None`/`'auto'`, `APIClient.__init__` handshakes and `_retrieve_server_version` wraps `except Exception` into a **`DockerException`** (`api/client.py:203–207`, `:221–232`); on any **later call**, a connection failure propagates as a **`requests`** exception, since `_raise_for_status` only converts `HTTPError` (`:272–277`). `map_sdk_error` must handle **both**, and must match `APIError` before any broad `requests` catch, because `APIError` *is* an `HTTPError`. See [`errors.md`](errors.md) §3.
9. **`attrs` is a cache.** Every state read after a lifecycle event needs `reload()` (a full inspect); there is no watch primitive.

---

## 4. Reproducing or extending this capture

Everything here was read from the installed package — no web fetch was
performed, so there is nothing to re-fetch. To extend:

```
grep -n "def <method>" .venv/lib/python3.11/site-packages/docker/models/containers.py
```

and read the docstring + implementation (line numbers are cited per page).

**Two cautions when re-verifying:**

1. **Line numbers are 7.2.0 facts.** If the floor `docker>=7.0` ever resolves
   to a different patch release, re-verify — the kwarg routing tables
   (`RUN_CREATE_KWARGS`/`RUN_HOST_CONFIG_KWARGS`) are the most likely to drift.
2. **The `[INFERRED]` set needs one daemon.** The `State` field names and the
   restart-policy/`stop` interaction are Engine-contract facts; the first
   `@pytest.mark.docker` test should print a real `inspect` and a real
   `stop`-with-restart-policy outcome, and record them here.

---

## 5. The 2026-09-16 confirmation pass — what changed

Run before behaviour 14's first test, against the same installed 7.2.0 tree
(`docker/_version.py:21` re-read: `__version__ = version = '7.2.0'`). The
installed source was treated as authoritative throughout.

**Five of the seven §3 facts resolved unchanged, line for line:** the
`run`/`create` kwarg names and the detached-start choice; `DeviceRequest` and
its constructor arguments; the `containers.list` label-filter form and the
separate `all` flag; the `docker.errors` hierarchy and the 404 string-matching
rule; and `stop`'s `timeout` name, its seconds unit and the
docstring-vs-code disagreement over the default.

**Four pages corrected, one added:**

| Page | Change |
| --- | --- |
| [`container-logs.md`](container-logs.md) | **`CancellableStream`'s module was wrong** — cited as `utils/socket.py`, actually `types/daemon.py:8` (`grep "class CancellableStream"` matches only there). A test importing from the cited path would have failed. Also added: `__next__` turns `ProtocolError`/`OSError` into `StopIteration`, so a broken follow stream **ends quietly** |
| [`errors.md`](errors.md) | §3's "a dead daemon is **not** a `DockerException`" was **too strong** — true for operational calls, false for construction. Corrected with the two paths and their line citations (see finding 8 above) |
| [`containers-run-create.md`](containers-run-create.md) | §2's kwarg-routing subsection had **a heading and a conclusion but no table** — the very fact this INDEX flags as most drift-prone was unciteable. Filled in from `_create_container_args` (:1123–1182), with the routing destination of every kwarg `build_run_kwargs` emits |
| [`containers-list-filters.md`](containers-list-filters.md) | §4 ended in the dangling fragment *"concurrently-removed container bites:"*. Repaired; the `sparse`/`ignore_removed` trade-off is now explicit, with the consequence for behaviour 25 (label recovery rules out `sparse=True`, so non-sparse + `ignore_removed=True`) |
| [`client-construction-and-env.md`](client-construction-and-env.md) | **New.** Closes §2's "not yet captured" gap for **behaviour 20** |

**Two judgements recorded rather than facts corrected:**

1. **Behaviour 24's evidence has a ceiling, now written down.**
   [`container-attrs-reload.md`](container-attrs-reload.md) §3.1 separates what
   is `[READ]` (`attrs` caching, `reload()`, the `status` property and its
   `attrs['State']['Status']` path, and `wait()['StatusCode']`) from what stays
   `[INFERRED]` (`State.ExitCode`, `State.StartedAt`, and the full set of
   status strings). Re-greps confirmed the SDK references **`ExitCode` only
   once** — `exec_inspect`'s at `models/containers.py:222`, an *exec* result,
   not a container inspect — and **`StartedAt` not at all**. Since behaviour
   24's stub returns canned dicts, its tests would pass against a wrong key
   name; they must therefore document the assumption and cite §3.1 rather than
   claim SDK authority. **No daemon was used and none will be in M2a**, so
   nothing was promoted to `[READ]`.
2. **`from_env` is an alias, not only a classmethod.** `client.py:283` binds
   `DockerClient.from_env` to the module name at import time, so patching one
   name does not affect the other. Behaviour 20's guard must patch **both** —
   and, better, make the constructors themselves raise, since
   `APIClient.__init__` reads `~/.docker/config.json` (`:131`) even with an
   explicit `base_url`. Noted there too that **an unset `DOCKER_HOST` is not
   evidence of isolation**: it is exactly the condition under which the
   context/config-file path is taken.
