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

A working single-model config is three lines: a tool name pointing at a
directory that holds the tool's configuration file (`tool.yaml`).

```yaml
# tools.yaml
tools:
  example_echo:
    path: ./tools/example_echo
```

While this is the minimum that tool-swap requires to configure tools, more options can be provided to overide default values. A full example with all parameters is provided here: [`tools.example.yaml`](tools.example.yaml).

Note that it is possible to use tswap to validate your configuration file. Any error will be reported with clear error message and how to fix it:

```bash
tswap validate --config tools.example.yaml --strict
```

**First steps.**

1. **Check your config.** `tswap validate` loads, resolves and checks the
   whole file in one pass. Exit 0 means you are good, with any warnings
   on stderr; exit 1 means errors; exit 2 means the file could not be
   read. Each diagnostic names the problem with a `TSWAP-C*` or
   `TSWAP-S*` code, points at the exact spot, and suggests the fix. Add
   `--strict` to fail on warnings too, or `--json` for a
   machine-readable report.
2. **See what tool-swap resolved.** `tswap config show [tool]` prints
   every effective value with its origin, so you can see which layer set
   it. `--verbose` also shows the values each setting overrode.
3. **Keep reading.** The [Configuration guide](docs/configuration-guide.md)
   walks from this three-line minimum to a full multi-GPU setup: the
   three ways to define a tool, defaults and groups, how values resolve,
   and environment variables.

**Go deeper.** Every key's type, default and description lives in the
generated [Configuration reference](docs/configuration.md), and every
diagnostic code maps to a cause and a fix in its
[troubleshooting table](docs/configuration.md#troubleshooting-every-diagnostic-code).

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
├── templates/                  # Tool templates (cpu, cuda, tensorflow, function)
├── models/                     # Model zoo (gitignored, examples included)
├── tests/                      # pytest suite (unit, integration, e2e)
│   ├── unit/                   # Unit tests mirroring src/ structure
│   ├── runtime/contract/       # Runtime contract tests
│   ├── integration/            # Docker-based integration tests
│   └── e2e/                    # End-to-end quickstart test
├── docs/                       # User documentation (configuration guide, generated reference)
├── deploy/                     # Deployment artifacts (systemd, prometheus, grafana)
└── plan/                       # Implementation plans and architecture docs
```

**Key design principles:**

- **`tool_swap` and `tool_swap_runtime` are strictly separate.** The router never imports the runtime and vice versa.
- **`backends/` is the only place BentoML imports may appear.** A second import-linter rule enforces the boundary.
- **`NATIVE.md` is a specification document, not a package.** The native backend is not implemented in v1.

## License

Apache-2.0
