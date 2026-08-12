---
description: Repository architecture
trigger: always_on
---
# tool-swap

## Project Structure

```
tool-swap/
├── .devcontainer/          # Dev container configuration (Dockerfile)
├── .roo/                   # Roo Code rules, commands, and skills
│   ├── commands/           # Custom Roo commands
│   │   ├── create-pull-request.md
│   │   ├── execute-github-task.md
│   │   ├── github-bug-report.md
│   │   ├── update_roo_rules.md
│   │   └── write-github-task.md
│   ├── rules/              # General rules
│   │   └── AGENTS.md
│   ├── rules-docs-manager/ # Docs Manager mode guidelines
│   ├── rules-qna-tester/   # Q&A Tester mode instructions
│   ├── rules-tdd-manager/  # TDD Manager mode instructions
│   └── skills/             # Roo skills
├── plan/                   # Implementation plans and architecture docs
│   ├── 00_CONTEXT_AND_MOTIVATION.md
│   ├── 01_ARCHITECTURE.md
│   ├── 02_CONFIGURATION.md
│   ├── 03_TOOL_AUTHORING.md
│   ├── 04_API_CONTRACT.md
│   ├── 05_RUNTIME_AND_BATCHING.md
│   ├── 06_LIFECYCLE_TTL_AND_SCHEDULING.md
│   ├── 07_CLI_AND_OPS.md
│   ├── 08_REPO_LAYOUT.md
│   ├── 09_IMPLEMENTATION_PLAN.md
│   ├── 10_TESTING_STRATEGY.md
│   ├── 11_R8_CLIENT_PLAN.md
│   ├── 12_REFERENCE_CODE.md
│   ├── 13_OPEN_QUESTIONS.md
│   ├── 14_ALTERNATIVES_EVALUATION.md
│   ├── HANDOFF.md
│   ├── README.md
│   └── adr/                # Architecture Decision Records
│       ├── 0001-build-our-own-router.md
│       ├── 0002-shared-node-soft-unload.md
│       └── README.md
└── .roomodes               # Custom Roo mode definitions
```

## Important Configurations

- **Dev container**: Configuration is in `.devcontainer/Dockerfile`
- **Custom modes**: Defined in `.roomodes` (docs-manager, qna-tester, tdd-manager)
- **MCP configuration**: GitHub MCP is configured in `.roo/mcp.json`
- **Organization**: iar3-r8 (GitHub)
- **Repository**: tool-swap
- **GitHub user**: MathGaron
