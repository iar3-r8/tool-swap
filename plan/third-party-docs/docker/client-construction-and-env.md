# docker-py — client construction and every path that reads the environment

**Source URL:** <https://docker-py.readthedocs.io/en/stable/client.html>
(the SDK's client documentation; **nothing below was taken from it** — every
fact is read from the installed source, and the URL is recorded because this
directory's convention requires the upstream source of each page)

**Source (authoritative for this page):** installed `docker` package **7.2.0**,
read directly at `.venv/lib/python3.11/site-packages/docker/`:

- `docker/__init__.py` — the public re-exports
- `docker/client.py` — `DockerClient`, `from_env`, `from_context`
- `docker/api/client.py` — `APIClient.__init__`
- `docker/utils/utils.py` — `kwargs_from_env`
- `docker/utils/config.py` — `find_config_file`, `config_path_from_environment`, `home_dir`
- `docker/context/api.py` — `ContextAPI.kwargs_from_context`
- `docker/context/config.py` — `get_current_context_name`
- `docker/auth.py`, `docker/credentials/utils.py` — credential-store environment

**Captured:** 2026-09-16, during the confirmation pass on this directory, to
close the gap `INDEX.md` §2 listed as *"`docker.from_env()` / `DockerClient`
construction — relevant, not yet captured"*.

**Why this page exists:** **M2a behaviour 20** is a guardrail requiring that
`DockerBackend`'s constructor **never** reads the ambient environment, and its
test monkeypatches the SDK's environment-reading entry points to raise. That
test can only be as good as the list of entry points it patches — a missed one
is a guardrail with a hole in it. This page enumerates them from source.

---

## 1. The three public ways to build a client **[READ]**

`docker/__init__.py` re-exports exactly these (lines 1–5):

```python
from .api import APIClient
from .client import DockerClient, from_context, from_env
```

so the reachable constructors are:

| Entry point | Defined | Reads the environment? |
| --- | --- | --- |
| `docker.from_env(...)` | `client.py:283` — a module-level **alias**: `from_env = DockerClient.from_env` | **Yes** — see §2 |
| `docker.DockerClient.from_env(...)` | `client.py:50–116` (classmethod) | **Yes** — see §2 |
| `docker.from_context(...)` | `client.py:284` — alias: `from_context = DockerClient.from_context` | **Yes** — see §3 |
| `docker.DockerClient.from_context(...)` | `client.py:118–161` (classmethod) | **Yes** — see §3 |
| `docker.DockerClient(base_url=..., ...)` | `client.py:47–48` — `__init__`, which is only `self.api = APIClient(*args, **kwargs)` | **Yes, partially** — see §4 |
| `docker.APIClient(base_url=..., ...)` | `api/client.py:115–219` | **Yes, partially** — see §4 |

**`from_env` is an alias, which is the subtle part for behaviour 20.**
`client.py:283` binds the *function object* `DockerClient.from_env` to the
module-level name `docker.from_env` at import time. Monkeypatching
`docker.from_env` therefore does **not** affect `docker.DockerClient.from_env`,
and patching the classmethod does not rebind the already-created alias. **A
complete guard patches both names.**

## 2. `DockerClient.from_env` — the env-reading path in full **[READ]**

`client.py:50–116`. Two distinct environment reads:

```python
# client.py:101–108
use_context = kwargs.pop('use_context', True)
environment = kwargs.get('environment') or os.environ      # :102

params = kwargs_from_env(**kwargs)                          # :104
if use_context and 'base_url' not in params:
    for k, v in ContextAPI.kwargs_from_context(
            environment=environment).items():               # :106–107
        params.setdefault(k, v)
```

1. **`kwargs_from_env`** (`utils/utils.py:353–388`) — reads
   **`DOCKER_HOST`** (:356), **`DOCKER_CERT_PATH`** (:359) and
   **`DOCKER_TLS_VERIFY`** (:363), defaulting to `os.environ` when no
   `environment` dict is passed (:354–355). When TLS is implied but no cert
   path is given it falls back to `os.path.expanduser('~')/.docker` (:379) —
   **a home-directory read, not only an env-var read**.
2. **`ContextAPI.kwargs_from_context`** — reached **only** when `use_context`
   is true (the default) *and* `DOCKER_HOST` was absent. See §3.

The documented env vars, from the docstring (:58–69): `DOCKER_HOST`,
`DOCKER_TLS_VERIFY`, `DOCKER_CERT_PATH`. The docstring also documents
`environment (dict)` — *"The environment to read environment variables from.
Default: the value of `os.environ`"* (:77–78) — and `use_context` (:84–87).

## 3. The context path — the non-obvious one **[READ]**

`ContextAPI.kwargs_from_context` (`context/api.py:136–160`):

```python
if environment is None:
    environment = os.environ            # :146–147
if name is None:
    name = environment.get("DOCKER_CONTEXT")   # :148–149
ctx = cls.get_context(name)
```

and when no `DOCKER_CONTEXT` is set, `get_context(None)` resolves through
`get_current_context_name` (`context/config.py:12–21`), which **opens
`~/.docker/config.json`** and reads its `currentContext` field.

So this path reads **`DOCKER_CONTEXT`** *and* **the user's Docker config
file**. `DockerClient.from_context` (`client.py:147–161`) calls
`kwargs_from_context(name=name)` with **no `environment` argument**, so it
always falls through to `os.environ` (:146–147).

**Consequence for behaviour 20:** ambient configuration reaches a client from
**two** sources — environment variables *and* `~/.docker/config.json`. A guard
that patches only env-var readers leaves the file path open.

## 4. `APIClient.__init__` reads the filesystem environment too **[READ]**

`api/client.py:115–219`. Even with an explicit `base_url` and no `from_env`,
construction reads ambient state:

| Line | What it reads |
| --- | --- |
| `:131` | `self._general_configs = config.load_general_config()` → `find_config_file()` → **`DOCKER_CONFIG`** env var (`utils/config.py:33–37`), then `~/.docker/config.json`, then `~/.dockercfg` (:13–19). `home_dir()` reads **`USERPROFILE`** on Windows, `expanduser('~')` on POSIX (:40–48) |
| `:133–139` | Proxy configuration taken from that config file's `proxies` key |
| `:141–143` | `auth.load_config(...)` — credential configuration from the same file |

So **`docker.APIClient(base_url=...)` is not environment-free.** It does not
read `DOCKER_HOST`, but it does read `DOCKER_CONFIG` and the user's Docker
config file.

**And one further fact that matters more than it looks [READ]:**

```python
# api/client.py:203–207
if version is None or (isinstance(version, str) and version.lower() == 'auto'):
    self._version = self._retrieve_server_version()
```

`version` defaults to `None`, so **constructing a client performs a live
daemon round-trip** (`_retrieve_server_version`, :221–232) unless an explicit
version string is passed. Two consequences:

- A constructor that touches a daemon cannot be exercised in a no-daemon test
  suite — which is exactly why §4.5's injected-client seam is the right design
  and why `from_config` is the only place M2a builds a real one.
- On failure it raises **`DockerException`** *"Error while fetching server API
  version: …"* (:230–232), because `_retrieve_server_version` catches bare
  `except Exception` (:229). See [`errors.md`](errors.md) §3.

`DEFAULT_TIMEOUT_SECONDS = 60` and `DEFAULT_DOCKER_API_VERSION = '1.45'`
(`constants.py:5,7`); the latter is *not* applied by `APIClient.__init__`,
which handshakes instead when `version is None`.

## 5. The enumerated list for behaviour 20's guard

Every environment-or-ambient-state reader on a client-construction path, read
from the installed source. **The first four are the ones a monkeypatch guard
should make raise**; the rest are why the guard must also assert *that no
client was built at all*, since they are reached indirectly.

| # | Entry point | Location | Ambient state read |
| --- | --- | --- | --- |
| 1 | `docker.from_env` (module alias) | `client.py:283` | via `DockerClient.from_env` |
| 2 | `docker.DockerClient.from_env` | `client.py:50–116` | `DOCKER_HOST`, `DOCKER_CERT_PATH`, `DOCKER_TLS_VERIFY`, `DOCKER_CONTEXT`, `~/.docker/config.json` |
| 3 | `docker.from_context` (module alias) | `client.py:284` | via `DockerClient.from_context` |
| 4 | `docker.DockerClient.from_context` | `client.py:118–161` | `DOCKER_CONTEXT`, `~/.docker/config.json` |
| 5 | `docker.utils.kwargs_from_env` | `utils/utils.py:353–388` | `DOCKER_HOST`, `DOCKER_CERT_PATH`, `DOCKER_TLS_VERIFY`, `~/.docker` |
| 6 | `docker.context.ContextAPI.kwargs_from_context` | `context/api.py:136–160` | `DOCKER_CONTEXT`, then the config file |
| 7 | `docker.context.config.get_current_context_name` | `context/config.py:12–21` | `~/.docker/config.json` (`currentContext`) |
| 8 | `docker.utils.config.find_config_file` | `utils/config.py:13–30` | `DOCKER_CONFIG`, `~/.docker/config.json`, `~/.dockercfg` |
| 9 | `docker.utils.config.config_path_from_environment` | `utils/config.py:33–37` | `DOCKER_CONFIG` |
| 10 | `docker.utils.config.home_dir` | `utils/config.py:40–48` | `USERPROFILE` (Windows) / `~` (POSIX) |
| 11 | `docker.utils.config.load_general_config` | `utils/config.py:51–66` | the resolved config file |
| 12 | `docker.APIClient.__init__` | `api/client.py:115–219` | items 8–11 via `:131`, plus a **live daemon handshake** at `:203–207` |
| 13 | `docker.DockerClient.__init__` | `client.py:47–48` | everything item 12 reads |
| 14 | `docker.auth.load_config` | `auth.py:348–349` | the config file; `DOCKER_CONFIG` via item 8 |
| 15 | `docker.credentials.utils.create_environment_dict` | `credentials/utils.py:4–9` | `os.environ.copy()` — only when a credential store subprocess runs |

**The full list of environment variable names** appearing on these paths:
`DOCKER_HOST`, `DOCKER_CERT_PATH`, `DOCKER_TLS_VERIFY`, `DOCKER_CONTEXT`,
`DOCKER_CONFIG`, `USERPROFILE`. (Verified by grepping `os.environ` / `getenv`
over the package: the only direct `os.environ` reads are `client.py:102`,
`utils/utils.py:355`, `utils/config.py:34,46`, `context/api.py:147` and
`credentials/utils.py:8`.)

### What this implies for behaviour 20's test

- **Patch items 1–4 by name** — all four, because of the alias/classmethod
  split in §1. Patching `docker.from_env` alone is insufficient.
- **Patching `DockerClient.__init__` or `APIClient.__init__` to raise is the
  strongest single guard**, since items 5–11 and 14–15 are only reachable
  *through* a constructor, and item 12 shows construction itself reads the
  config file. A test that constructs and uses `DockerBackend` with the
  injected stub while **both** constructors raise proves the seam holds
  regardless of which entry point a future regression reaches for.
- **`DOCKER_HOST` being unset is not evidence.** §3 shows the context path is
  taken *precisely when* `DOCKER_HOST` is absent, so clearing the variable
  makes the config-file path *more* likely, not less. Do not write a guard
  that relies on an unset variable.
- This is a **no-daemon** test by construction, consistent with M2a's
  commitment: the assertion is that nothing was constructed from ambient
  state, and item 12 means a real construction would need a daemon anyway.
