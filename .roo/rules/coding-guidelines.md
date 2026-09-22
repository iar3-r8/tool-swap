---
description: code style guidelines
trigger: always_on
---

## Code language and compliances

- Python project using Black for formatting (88 character line length)
- flake8 for linting compliance
- pytest for testing

## Documentation guidelines

- A docstring explains what the code pins and why it could fail — never how the decision was reached. Decisions and rationale belong in the commit message and the plan: both are permanent, searchable, and already required.
- Documentation pages (and docstrings) describe the system as it is now, not the work that produced it: no slice letters, milestone identifiers, behaviour numbers, pull request numbers, commit hashes, or "shipped/planned" sequencing in prose. Capability limits are allowed; project schedules are not. The full standard, with examples and the pre-finish self-check, is in `.roo/rules-docs-manager/guidelines.xml` — it applies to every mode that writes documentation, not only Docs Manager.
- Keep docstrings short. A test docstring is normally one to three lines; one approaching the length of the code it documents is narrating the decision — move the narrative to the commit message or the plan.
- Minimal inline comments - only explain non-obvious logic or technical constraints
- Never document a flag or command from memory; confirm against the code first

## Test guidelines

- Use pytest as the test framework
- Tests are organized in a `tests/` directory
- Run tests with the `pytest` command
- Follow the AAA (Arrange, Act, Assert) pattern for test structure
- Write tests that are easily testable with well-structured functions and classes
- Prefer pure functions where possible and avoid side effects unless necessary
- Use dependency injection for better testability
- Test-facing strings (assertion messages, `pytest.fail` text, skip reasons) are read by a developer debugging a failure, not by the pipeline. They state what is missing and where — never process vocabulary such as "RED step", "GREEN step", or behaviour numbers used as workflow markers.

## Additional Guidelines

- Keep functions focused on a single responsibility
- Use descriptive variable names that indicate purpose
- Limit line length to 88 characters (Black standard)
- Use explicit imports over wildcard imports
- Follow naming conventions: snake_case for variables/functions, PascalCase for classes

## Documentation Finalisation

- Once all tests are written and passing, ask the user whether to switch to **Docs Manager** mode to finalize documentation (README, doc/ directory, usage guides).
- Always ask the user whether to document the current commit or the current branch before starting documentation work.
