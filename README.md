# tool-swap

A tool swapping router for managing AI agent tool contexts.

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
│   ├── base/                   # CPU and CUDA base images
│   └── router.Dockerfile
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
