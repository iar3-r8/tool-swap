---
description: code style guidelines
trigger: always_on
---

## Code language and compliances

- Python project using Black for formatting (88 character line length)
- flake8 for linting compliance
- pytest for testing

## Documentation guidelines

- Google style docstrings for all functions and classes
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

## Additional Guidelines

- Keep functions focused on a single responsibility
- Use descriptive variable names that indicate purpose
- Limit line length to 88 characters (Black standard)
- Use explicit imports over wildcard imports
- Follow naming conventions: snake_case for variables/functions, PascalCase for classes

## Documentation Finalisation

- Once all tests are written and passing, ask the user whether to switch to **Docs Manager** mode to finalize documentation (README, doc/ directory, usage guides).
- Always ask the user whether to document the current commit or the current branch before starting documentation work.
