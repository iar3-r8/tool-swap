# tool-swap

A tool swapping router for managing AI agent tool contexts.

## Architecture

See the full architecture overview in [plan/01_ARCHITECTURE.md](plan/01_ARCHITECTURE.md).
The complete implementation plan is at [plan/README.md](plan/README.md).

## Distributions

- **tool-swap** — The router package. Requires Python 3.12+.
- **tool-swap-runtime** — The runtime backend package. Requires Python 3.10+.

## Installation

```bash
pip install -e ".[dev]"
```

## CLI

```bash
tswap --help
```

## Configuration

Tool-swap is configured by one `tools.yaml` file plus a directory per tool.
Requirement R4 — a working single-model config must fit in five lines — is
the design bar, and it holds: the committed
[`tools/example_echo`](tools/example_echo/tool.yaml) fixture is the proof,
and
[`test_the_minimal_config_is_at_most_five_lines`](tests/unit/config/test_minimal_config.py:226)
asserts it mechanically.

The minimum is a tool name pointing at a directory:

```yaml
tools:
  example_echo:
    path: ./tools/example_echo
```

The committed [`tools.example.yaml`](tools.example.yaml) shows the full
surface, and every key has its type, default and description in the
generated reference [`docs/configuration.md`](docs/configuration.md); the
design rationale is in
[`plan/02_CONFIGURATION.md`](plan/02_CONFIGURATION.md).

**Validating.** `tswap validate` runs the whole pipeline in one pass; each
diagnostic carries a `TSWAP-C*`/`TSWAP-S*` code, a location and a remedy.
Exit 0 (warnings, if any, on stderr), exit 1 (errors; `--strict` also
promotes warnings), exit 2 (the config file could not be read). `--json`
prints the report on stdout and nothing else.

**Inspecting.** `tswap config show [tool]` prints the fully-resolved config
with each value's origin — which layer set it. `--verbose` also shows the
shadowed values each setting overrode; `--json` emits the
`{config, router, backend, tools}` envelope on stdout; `--show-secrets`
prints secret values instead of `***` (local use only, no banner).

**The example.** `tools.example.yaml` is validated in CI with `--strict`,
so it is guaranteed free of errors AND warnings — copy from it freely.

**Troubleshooting.** Every `TSWAP-C*`/`TSWAP-S*` code maps to a cause and a
fix in the troubleshooting table in
[`docs/configuration.md`](docs/configuration.md).

## Get started

1. **Clone the repository**
   ```bash
   git clone https://github.com/iar3-r8/tool-swap.git
   cd tool-swap
   ```
2. **Install dependencies**
   ```bash
   pip install -e ".[dev]"
   ```
3. **Run lint and type-check**
   ```bash
   make lint
   ```
4. **Run the test suite**
   ```bash
   .venv/bin/pytest          # when .venv is not on PATH
   make test                 # or use the Makefile target
   ```
5. **Verify the CLI**
   ```bash
   tswap --help
   ```
The full implementation plan is at [plan/README.md](plan/README.md).

## Repository Structure

```
tool-swap/
├── src/
│   ├── tool_swap/              # Router package (always-on, tiny deps)
│   │   ├── __init__.py
│   │   ├── __main__.py         # python -m tool_swap
│   │   ├── config/             # Schema parsing, config loading, resolution
│   │   ├── schema/             # JSON Schema compilation, tool definitions
│   │   ├── registry/           # Tool registry, model definitions
│   │   ├── scheduler/          # Dispatch, batching, occupancy accounting
│   │   ├── lifecycle/          # Container lifecycle state machine
│   │   ├── backend/            # Pluggable container backends (Docker, fake)
│   │   ├── preflight/          # Deployment gate: checks, runner, report
│   │   │   └── checks/         # Static, build, boot, readiness, contract checks
│   │   ├── proxy/              # Streaming reverse proxy, health probes
│   │   ├── api/                # FastAPI routes (run, upstream, admin, discovery)
│   │   │   └── ui/             # Status page (single HTML file, no build step)
│   │   ├── observability/      # Logging, metrics, request IDs
│   │   ├── cli/                # Typer CLI commands (up, down, status, logs, etc.)
│   │   └── utils/              # Clock protocol, ID generation
│   │
│   └── tool_swap_runtime/      # In-container runtime (BentoML-based)
│       ├── __init__.py         # Public API: @tool decorator, Field, __version__
│       ├── pyproject.toml
│       └── backends/           # Backend abstractions (BentoML-only imports here)
│           ├── __init__.py
│           └── NATIVE.md       # Native backend specification (spec only, no code)
│
├── docker/                     # Dockerfiles (router base images)
│   └── base/                   # CPU and CUDA base images
├── templates/                  # tswap new templates (cpu, cuda, tensorflow, function)
├── models/                     # Model zoo (gitignored, examples included)
├── tests/                      # pytest suite (unit, integration, e2e)
│   ├── unit/                   # Unit tests mirroring src/ structure
│   ├── runtime/contract/       # Runtime contract tests
│   ├── integration/            # Docker-based integration tests
│   └── e2e/                    # End-to-end quickstart test
├── docs/                       # Documentation (quickstart, operations, architecture)
├── deploy/                     # Deployment artifacts (systemd, prometheus, grafana)
└── plan/                       # Implementation plans and architecture docs
```

**Key design principles:**

- **`tool_swap` and `tool_swap_runtime` are strictly separate.** The router never imports the runtime and vice versa.
- **`backends/` is the only place BentoML imports may appear.** A second import-linter rule enforces the boundary.
- **`NATIVE.md` is a specification document, not a package.** The native backend is not implemented in v1.

## License

Apache-2.0
