# Configuration reference

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: python scripts/gen_config_reference.py -->

Every key tool-swap understands, with its type, default and meaning.
Generated from the Pydantic models in `src/tool_swap/config/schema.py`.

## The document root

The top-level config document (`tools.yaml`).

| Key | Type | Default | Description |
|---|---|---|---|
| `version` | an integer or null | null | Config schema version; this build understands version 1 only. |
| `router` | a RouterConfig block or null | null | The router block: the always-on HTTP entry point's own settings. |
| `backend` | a BackendConfig block or null | null | The backend block: how containers are named, networked and cleaned up. |
| `defaults` | a DefaultsConfig block or null | null | The defaults block: values every tool inherits unless it overrides them. |
| `groups` | a mapping | {} | Scheduling groups by name; each caps how many of its member tools run at once. |
| `tools` | a mapping | {} | The tools this router serves, by name; each entry is one tool. |

## `router:`

The `router:` block — the HTTP front door (`plan/02` §3).

| Key | Type | Default | Description |
|---|---|---|---|
| `host` | a string | "0.0.0.0" | Interface the router's HTTP server binds to; 0.0.0.0 accepts connections on every interface. |
| `port` | an integer | 8600 | TCP port the router listens on. |
| `log_level` | a string | "INFO" | Minimum severity the router logs: DEBUG, INFO, WARNING, ERROR or CRITICAL. |
| `log_dir` | a string | "./logs" | Directory holding the router log and one subdirectory per tool. |
| `log_json` | a boolean | true | Also write structured JSONL logs alongside the human-readable console output. |
| `cors_origins` | a list of a string | ['*'] | Browser origins allowed to call the API; ["*"] allows any, which suits the status page and local clients. |
| `auth_token` | a string or null | null | When set, every request must carry an Authorization: Bearer header with this token; null disables authentication. |
| `status_page` | a boolean | true | Serve the HTML status page at /ui. |

## `backend:`

The `backend:` block — container-runtime knobs (`plan/02` §3).

| Key | Type | Default | Description |
|---|---|---|---|
| `type` | a string | "docker" | Container backend to drive: docker for real containers, fake for tests. |
| `network` | a string | "tool-swap-net" | Docker network every tool container joins; created if absent. |
| `container_prefix` | a string | "ms-" | Prefix for managed container names — a container is named <prefix><tool name>. |
| `label_namespace` | a string | "com.tool-swap" | Label namespace stamped on managed containers, used for reconciliation and pruning. |
| `gpu_runtime` | a string | "nvidia" | GPU runtime requested from the backend when a tool declares devices. |
| `orphans` | a string | "stop" | What to do with a running container whose tool left the config: stop, adopt or ignore. |
| `port_range` | a list of an integer | [7000, 7999] | Inclusive [low, high] host-port range used when a tool asks for an auto-allocated debug port. |
| `registry_prefix` | a string | "tool-swap" | Image-name prefix for the images tool-swap builds. |

## `defaults:`

The `defaults:` block — values applied to every tool (`plan/02` §3).

| Key | Type | Default | Description |
|---|---|---|---|
| `ttl` | an integer | 900 | Idle seconds before a tool's container is stopped: -1 inherits, 0 never stops, above 0 is a timeout. The only idle timer in v1 (ADR-0004). |
| `keep_warm` | a boolean | false | Start every tool at boot and exempt it from TTL. |
| `autostart` | a boolean | true | Start a stopped tool on its first request; false returns 503 instead of starting it. |
| `group` | a string | "default" | Scheduling group a tool joins when it names none; the group must exist in groups:. |
| `devices` | a list of an integer | [] | GPU indices visible to a tool, e.g. [0] or [0,1]; [] means CPU-only. Set here it outranks every group's devices:. |
| `cpus` | a number or null | null | Docker CPU quota per tool, e.g. 4.0; null leaves it unlimited. |
| `memory` | a string or null | null | Docker memory limit per tool, e.g. "16g"; null leaves it unlimited. |
| `shm_size` | a string | "1g" | Shared-memory size for each container, e.g. "1g"; raise it for torch DataLoader workers. |
| `max_batch_size` | an integer | 8 | Upper bound on how many requests the runtime groups into one batch. |
| `max_wait_ms` | an integer | 20 | Latency target the adaptive batcher aims to keep, in milliseconds; not a fixed wait. |
| `workers` | an integer | 1 | In-container worker processes per tool; above 1 with devices: set, VRAM multiplies. |
| `runtime_server` | a string | "bentoml" | In-container serving backend: bentoml is implemented, native is reserved and rejected in v1. |
| `start_timeout` | an integer | 120 | Seconds to wait for a container to start before declaring the tool failed. |
| `ready_timeout` | an integer | 600 | Seconds to wait for a started container to report ready; measure a cold start and add margin. |
| `queue_timeout` | an integer | 300 | Seconds a request may wait in the queue before it is rejected. |
| `request_timeout` | an integer | 300 | Seconds a single request may take once dispatched to the tool. |
| `drain_timeout` | an integer | 30 | Seconds to let in-flight requests finish when a tool is being stopped. |
| `stop_timeout` | an integer | 30 | Seconds to wait for a container to stop before it is killed. |
| `max_queue_depth` | an integer | 64 | Maximum queued requests per tool; beyond it, new requests are rejected. |
| `health_path` | a string | "/health" | HTTP path the router probes for container liveness. |
| `ready_path` | a string | "/ready" | HTTP path the router probes to decide a tool is ready to serve. |
| `probe_interval` | a number | 1.0 | Seconds between health and readiness probes. |
| `env` | a mapping | {} | Environment variables applied to every tool; merged with a tool's own env, the tool winning. |
| `mounts` | a list of a string | [] | Mounts applied to every tool as host:container[:ro|rw]; concatenated with a tool's own mounts. |
| `soft_ttl` | a Any | null | RESERVED and rejected (TSWAP-C400): plan/adr/0004-hard-stop-only-in-v1.md (ADR-0004 — v1 reclaims resources by stopping containers; soft unload is deferred). ttl: is the only idle timer in v1. |
| `max_batch_bytes` | a Any | null | RESERVED and rejected (TSWAP-C405): no such key exists; set max_batch_size low for large payloads. |

## `groups.<name>:`

One `groups.<name>:` entry (`plan/02` §3).

| Key | Type | Default | Description |
|---|---|---|---|
| `max_resident` | an integer | 4 | How many of this group's tools may run at once; the rest are evicted or wait. |
| `eviction` | a string | "lru" | Which resident tool to evict when the group is full: lru, lifo or none. |
| `devices` | a list of an integer or null | null | GPU indices shared by this group's tools; null leaves each tool's own devices: in force. |

## `tools.<name>:`

One inline `tools.<name>:` entry in the top-level config.

| Key | Type | Default | Description |
|---|---|---|---|
| `path` | a string or null | null | Directory holding this tool's tool.yaml; everything in it is inherited by this entry. |
| `handler` | a string or null | null | Entry point as file.py:ClassName, resolved against the tool directory or the config file. |
| `requirements` | a string or null | null | Requirements file installed into this tool's image. |
| `build` | a BuildConfig block or null | null | Build this tool's image from a Dockerfile the author supplies, instead of the managed build. |
| `image` | a string or null | null | Pin a pre-built image of this tool instead of building it (plan/02 §5.2). Exactly one of image:, build: or a managed handler: may be present (TSWAP-C510 / TSWAP-C511). |
| `group` | a string or null | null | Scheduling group for this tool; overrides defaults.group and must exist in groups:. |
| `ttl` | an integer or null | null | Idle seconds for this tool; overrides defaults.ttl. -1 inherits, 0 never stops. |
| `devices` | a list of an integer or null | null | GPU indices for this tool; overrides both its group's devices: and defaults.devices. |
| `workers` | an integer or null | null | Number of runtime-server workers per tool (plan/02 §5.5). With a non-empty devices: list, workers > 1 multiplies the tool's VRAM invisibly to the scheduler (TSWAP-C523). |
| `expose_host_port` | a boolean or an integer or null | null | Publish a host port for debugging (plan/02 §5.2): false publishes nothing, true auto-allocates from backend.port_range, an int publishes exactly that port (TSWAP-C530 / TSWAP-C531). |
| `keep_warm` | a boolean or null | null | Keep this tool started and TTL-exempt; overrides defaults.keep_warm. |
| `autostart` | a boolean or null | null | Whether a request to a stopped tool starts it (plan/02 §5.3): false returns 503 for a stopped tool instead of starting it. Contradicts keep_warm: true (TSWAP-C600). |
| `max_concurrent` | an integer or null | null | Optional cap on in-flight requests to a READY tool (plan/02 §5.3): 429 beyond it. A cap below 1 rejects every request (TSWAP-C602) — use autostart: false to disable a tool. |
| `max_batch_size` | an integer or null | null | Batch-size cap for this tool; overrides defaults.max_batch_size. Lower it for large payloads. |
| `max_wait_ms` | an integer or null | null | Batching latency target for this tool, in milliseconds; overrides defaults.max_wait_ms. |
| `mounts` | a list of a string or null | null | Extra mounts for this tool; concatenated after defaults.mounts, not replacing them. |
| `env` | a mapping or null | null | Extra environment variables for this tool; merged over defaults.env, this tool winning. |
| `description` | a string or null | null | What this tool does. Required, and the text an LLM agent reads to decide whether to call it. |
| `soft_ttl` | a Any | null | RESERVED and rejected (TSWAP-C400): plan/adr/0004-hard-stop-only-in-v1.md (ADR-0004 — v1 reclaims resources by stopping containers; soft unload is deferred). ttl: is the only idle timer in v1. |
| `scalar_inputs` | a Any | null | RESERVED and rejected (TSWAP-C403): plan/adr/0005-one-uniform-batched-calling-convention.md (ADR-0005 — One uniform calling convention: every handler takes and returns a list). |
| `max_batch_bytes` | a Any | null | RESERVED and rejected (TSWAP-C405): no such key exists; set max_batch_size low for large payloads. |

## `build:` (inside a tool)

The `build:` sub-block of a tool (`plan/02` §5.2).

| Key | Type | Default | Description |
|---|---|---|---|
| `context` | a string | — | Directory used as the Docker build context, relative to the config file. |
| `dockerfile` | a string | "Dockerfile" | Dockerfile to build, resolved inside the context; it must install tool-swap-runtime. |

## `tool.yaml`

Schema for a tool directory's own `tool.yaml` (`plan/02` §4).

| Key | Type | Default | Description |
|---|---|---|---|
| `name` | a string or null | null | The tool's own name; it must equal the key this tool has in the config's tools: map. |
| `version` | a string or null | null | The tool author's version string for this tool; informational. |
| `description` | a string or null | null | What this tool does. Required, and the text an LLM agent reads to decide whether to call it. |
| `handler` | a string or null | null | Entry point as file.py:ClassName, resolved against this tool's own directory. |
| `inputs` | a list of a mapping or null | null | Per-request inputs, each with name, type and description; compiled into the tool's JSON Schema. |
| `outputs` | a list of a mapping or null | null | Per-request outputs, each with name, type and description; compiled into the tool's JSON Schema. |
| `params` | a list of a mapping or null | null | Load-time values passed to the handler's constructor; not per-request, and not agent-visible. |
| `json_schema` | a mapping or null | null | Raw JSON Schema for the inputs, passed through untouched; the escape hatch instead of inputs:. |
| `soft_ttl` | a Any | null | RESERVED and rejected (TSWAP-C400): plan/adr/0004-hard-stop-only-in-v1.md (ADR-0004 — v1 reclaims resources by stopping containers; soft unload is deferred). ttl: is the only idle timer in v1. |
| `scalar_inputs` | a Any | null | RESERVED and rejected (TSWAP-C403): plan/adr/0005-one-uniform-batched-calling-convention.md (ADR-0005 — One uniform calling convention: every handler takes and returns a list). |
| `max_batch_bytes` | a Any | null | RESERVED and rejected (TSWAP-C405): no such key exists; set max_batch_size low for large payloads. |

## Troubleshooting: every diagnostic code

| Code | Cause | Fix |
|---|---|---|
| `TSWAP-C000` | The config file named on the command line does not exist. | Check the path, or run from the directory holding tools.yaml. |
| `TSWAP-C001` | The file is not valid YAML, or its version: is not 1. | Fix the YAML syntax; set version: 1 (or omit the key), since this build reads only config version 1. |
| `TSWAP-C002` | The same mapping key appears twice in the YAML. | Remove the duplicate key so the mapping has one of each. |
| `TSWAP-C003` | The config file is empty. | Add at least a 'tools:' block, e.g. the minimal config. |
| `TSWAP-C004` | The top level of the config is a list or a scalar, not a mapping. | Make the top level a YAML mapping of keys to values. |
| `TSWAP-C005` | A tool directory named by path: exists but has no tool.yaml. | Create tool.yaml in that directory, or drop the 'path:' key and configure the tool inline. |
| `TSWAP-C006` | A tool's path: points at a file, not a directory. | Point 'path:' at the directory that holds tool.yaml, e.g. ./tools/t. |
| `TSWAP-C007` | An included tool.yaml contains a 'path:' key; include recursion is not supported (one level only). | Remove the 'path:' key from tool.yaml; nested includes are not allowed. |
| `TSWAP-C010` | An interpolated variable is unset and the reference declares no default. | Set the variable, or write ${VAR:-default} to give it one. |
| `TSWAP-C011` | The --env-file named on the command line does not exist. | Create the file, or drop --env-file to auto-discover .env next to the config. |
| `TSWAP-C012` | A line of the .env file is not KEY=value. | Write the line as KEY=value, or prefix it with '#' to comment it out. |
| `TSWAP-C013` | A ${...} reference is never closed with }. | Add the missing } to close the reference. |
| `TSWAP-C101` | A key is not valid in the block it appears in. | Rename the key to the suggested alternative, or remove it. |
| `TSWAP-C104` | devices: is a bare number, which reads like a device index but behaves like a count. | Replace the number with a list of GPU indices, e.g. devices: [0,1,2]. |
| `TSWAP-C105` | A value has the wrong shape for its key (any other schema error). | Check the documented type and fix the value. |
| `TSWAP-C106` | A tool.yaml block key does not map to any tool field. | Remove the key, or use one of the mapped keys named in the message. |
| `TSWAP-C201` | tool.yaml's name: does not equal the tools: map key. | Make 'name:' in tool.yaml equal the tools: map key, or remove the 'name:' key if the tool.yaml is shared. |
| `TSWAP-C202` | Two tools: entries point at the same path: directory. | Give each tool its own directory, unless the entries deliberately differ only by params:. |
| `TSWAP-C210` | a tool name outside `^[a-z0-9][a-z0-9_-]*$`. | Rename the tool to match ^[a-z0-9][a-z0-9_-]*$: start with a lowercase letter or digit, then lowercase letters, digits, '_' and '-' only. |
| `TSWAP-C211` | two or more tools resolve to the same name. | Give each tool a unique name: a name may resolve to at most one tool, across every config layer. |
| `TSWAP-C220` | a tool references a group absent from `groups:`. | Either define the group under 'groups:' or point the tool's 'group' field at an existing one (or drop it to use 'default'). |
| `TSWAP-C221` | `groups.*.max_resident` below 1. | Set the group's max_resident to 1 or higher; a group must be able to hold at least one tool. |
| `TSWAP-C222` | `groups.*.eviction` outside the valid set. | Set the group's eviction to one of: lru, lifo or none. |
| `TSWAP-C223` | a group defined but referenced by no tool. | If the group is still needed, point at least one tool's 'group' field at it; otherwise remove it from 'groups:'. |
| `TSWAP-C300` | a tool whose own description is missing or blank. | Add a non-blank 'description' field for the tool — add it to the tool's 'tool.yaml', or its inline 'tools.<name>' entry. |
| `TSWAP-C301` | an `inputs:` entry missing its description. | Add a non-blank 'description' to the input entry — add it to the tool's 'tool.yaml', or its inline 'tools.<name>' entry. |
| `TSWAP-C302` | an `outputs:` entry missing its description. | Add a non-blank 'description' to the output entry — add it to the tool's 'tool.yaml', or its inline 'tools.<name>' entry. |
| `TSWAP-C303` | a `params:` entry missing its description. | Add a non-blank 'description' to the param entry — add it to the tool's 'tool.yaml', or its inline 'tools.<name>' entry. |
| `TSWAP-C400` | a reserved `soft_ttl` present at any level. | remove soft_ttl; use ttl: — it is the only idle timer in v1 |
| `TSWAP-C401` | `runtime.server: native` (not implemented). | set runtime.server: bentoml (or remove the key) |
| `TSWAP-C402` | `runtime.server` outside {bentoml, native}. | set runtime.server to one of: bentoml, native |
| `TSWAP-C403` | a reserved `scalar_inputs` present. | remove scalar_inputs; the handler already takes a list |
| `TSWAP-C404` | a per-input `batchable:` key (inputs ONLY). | remove 'batchable' from the input entry; batching is a tool-level property |
| `TSWAP-C405` | a reserved `max_batch_bytes` present. | remove max_batch_bytes and set max_batch_size low for large payloads |
| `TSWAP-C501` | A resolved ttl is not -1 (inherit), 0 (never stop) or a positive number of seconds. | Set ttl to -1, 0, or a positive number of seconds. |
| `TSWAP-C503` | Two mounts map different host paths to the same container path. | Remove one of the duplicate mounts so each container path is mounted once. |
| `TSWAP-C510` | more than one image source. | Keep exactly one image source: an image: (pre-built), a build: block (we build it), or a managed handler: — remove the others from the tool's inline 'tools.<name>' entry |
| `TSWAP-C511` | no image source at all. | Give the tool exactly one image source: an image: (pre-built), a build: block, or a managed handler: in its inline 'tools.<name>' entry, or a tool.yaml (via path:) that supplies a handler: |
| `TSWAP-C512` | a `handler` outside the `file.py:ClassName` form. | Write the handler as file.py:ClassName — a .py file relative to the tool directory, a ':' and a Python class name that is not a keyword |
| `TSWAP-C513` | the handler file does not exist (or is a directory). | Create the handler file at the path shown, or fix the path: it is relative to the tool's directory (its path: directory, or the root config's directory for an inline tool) |
| `TSWAP-C514` | a named `requirements` file that does not exist. | Create the requirements file at the path shown, or fix the path: it is relative to the tool's directory |
| `TSWAP-C515` | `build.context` or `build.dockerfile` missing. | Create the context directory (or the Dockerfile within it) at the paths shown, or fix build.context / build.dockerfile: they are relative to the tool's directory, and the dockerfile resolves within the context |
| `TSWAP-C516` | a path escaping the tool directory (WARNING). | Keep the path inside the tool's directory (no ../ walking out, no absolute path elsewhere): escaping it breaks the portability that path: exists to provide |
| `TSWAP-C520` | a negative or non-integer device index. | Replace every device index with a non-negative integer GPU index, wherever the list was set — the tool's devices: entry, the defaults: block, or the tool's group |
| `TSWAP-C521` | a device index exceeding the visible GPUs. | Use device indices below the visible GPU count on the target host, or deploy on a host with enough GPUs: this config may target another machine |
| `TSWAP-C522` | a duplicate index within one tool's `devices`. | Remove the duplicate device index from the tool's devices: list, or from the defaults: block or group that supplies it |
| `TSWAP-C523` | `workers > 1` AND a non-empty `devices` list. | Reduce workers: to 1, or keep workers: and size the group's max_resident: so the multiplied VRAM still fits |
| `TSWAP-C530` | two tools sharing an explicit host port. | Give each tool a distinct expose_host_port int, or set true to auto-allocate from backend.port_range |
| `TSWAP-C531` | an explicit host port outside `backend.port_range`. | Pick an expose_host_port inside backend.port_range (both endpoints inclusive), or true for auto-allocation; 0 is not a supported spelling |
| `TSWAP-C532` | an inverted or malformed `backend.port_range`. | Write backend.port_range as a two-int list [low, high] with 1 <= low <= high <= 65535 (low == high is a legal one-port range) |
| `TSWAP-C540` | an unparseable mount entry. | Rewrite the entry as host:container or host:container:ro|rw; a host path containing ':' (a Windows drive letter, for example) is not supported — mount entries are split on ':' |
| `TSWAP-C541` | a mount mode outside `{ro, rw}`. | Use ro or rw as the third part, exactly lowercase; a host path containing ':' (a Windows drive letter, for example) is not supported — mount entries are split on ':' |
| `TSWAP-C542` | a non-absolute container path. | Make the container path absolute (start it with '/') |
| `TSWAP-C543` | the host path does not exist (WARNING). | Confirm the path exists on the host running the daemon — mount entries are host paths interpreted by the Docker daemon, not paths inside the router container — wherever the entry was set: the tool's mounts:, the defaults: block, or its tool.yaml; the path may also be created before the container starts |
| `TSWAP-C600` | `keep_warm: true` AND `autostart: false`. | Resolve the contradiction, one of two: set keep_warm: false — the tool then starts on demand and idle-stops after ttl — or set autostart: true — the tool then starts at boot and stays resident, exempt from TTL. Either key may live in the tool's entry or the defaults: block |
| `TSWAP-C601` | `keep_warm: true` AND an EXPLICIT `ttl > 0`. | Remove the ttl from this tool if keep_warm is what you want, or set keep_warm: false if the idle timeout is what you want |
| `TSWAP-C602` | `max_concurrent` at or below zero. | Set max_concurrent to a positive integer, or drop the key to leave the tool uncapped; use autostart: false to disable a tool |
| `TSWAP-C603` | an out-of-range batching or timeout number. | Set the named field to a value in its range: max_batch_size >= 1, max_wait_ms >= 0, workers >= 1, and each of start_timeout, ready_timeout, queue_timeout, request_timeout, drain_timeout and stop_timeout > 0 |
| `TSWAP-C610` | every member keep_warm while `max_resident` < count. | Raise the group's max_resident to its keep-warm member count, or set eviction: none on the group if pinning these tools was the intent |
| `TSWAP-C612` | two or more groups sharing a device index. | Give each group its own device, or lower the groups' max_resident so their combined total fits the device; tool-swap cannot verify VRAM capacity in v1 |
| `TSWAP-C613` | `max_resident` above the member count. | Lower the group's max_resident to its member count, or add the missing tools to the group; nothing breaks either way |
| `TSWAP-C999` | Internal: a rule raised an exception instead of returning diagnostics. | This is a tool-swap bug; file a report with the full traceback. |
| `TSWAP-S100` | Two entries in the same inputs:/outputs: block share a name. | Rename one of the entries so each name appears once. |
| `TSWAP-S101` | A name appears in both inputs: and params:. | Remove the name from one of the blocks so it appears in only one. |
| `TSWAP-S102` | An input name is not a valid Python identifier; handlers receive inputs as keyword arguments, so the input can never be passed. | Rename it to a valid identifier. |
| `TSWAP-S103` | An entry's type (or an array entry's items type) is not one of the six supported: string, number, integer, boolean, array, object. | Use one of the six types, or move the tool to a json_schema: block for enums, ranges, oneOf or nested objects. |
| `TSWAP-S104` | An entry's semantic: value is not a string. | Write 'semantic' as a string, or remove it. |
| `TSWAP-S105` | The inputs:/outputs: block is not a list, or one of its entries is not a non-empty mapping. | Make the block a YAML list of entries, each a mapping with at least a 'name'. |
| `TSWAP-S106` | An entry has no non-empty string name:. | Add a non-empty string 'name' to the entry. |
| `TSWAP-S107` | An inputs: entry's required: value is not a boolean. | Set 'required' to true or false. |
| `TSWAP-S108` | An entry's description: is present but is not a string. | Write the entry's 'description' as a string. |
| `TSWAP-S109` | An entry's type is array but it declares no items:. | Add 'items: <one of the six types>' to the entry. |
| `TSWAP-S110` | An array entry's items: is itself an array or an object with properties: (nesting beyond one level). | Move the tool to a json_schema: block to describe nested items. |
| `TSWAP-S120` | An entry is missing its description: (ERROR on inputs:, WARNING on outputs:). | Add a non-blank 'description' to the entry. |
| `TSWAP-S130` | A tool declares both json_schema: and inputs:; they are alternatives. | Remove one of them from the tool's tool.yaml. |
| `TSWAP-S140` | The authored json_schema: is not valid JSON Schema 2020-12. | Fix the schema so it validates against the 2020-12 meta-schema. |
