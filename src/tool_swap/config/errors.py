"""Diagnostic model and error-report container for the M1 configuration pipeline.

This module is the error behaviour of everything downstream in M1: the config
loader, schema validator, and resolver all produce ``Diagnostic`` values
(frozen, coded, ordered) which are aggregated into a ``ConfigReport`` that
serves the three report consumers (human render, JSON, exception) from one
shape.  A ``Diagnostic`` must carry a mandatory, non-empty ``remedy`` because
the M1 Definition of Done is *a message a stranger can act on*.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum

_CODE_PATTERN = re.compile(r"TSWAP-[CS]\d{3}")


class Severity(Enum):
    """Severity of a diagnostic; the lowercase ``.value`` is the JSON form."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Location:
    """Where in the config file a diagnostic was found.

    Attributes:
        file: Path of the offending file (required).
        yaml_path: Dotted YAML path within the file, if known.
        line: 1-based line number, if known.
        column: 1-based column number, if known.
    """

    file: str
    yaml_path: str | None = None
    line: int | None = None
    column: int | None = None

    def render(self) -> str:
        """Render the location for human-readable output.

        Returns:
            ``file:line`` when a line is known, ``file (yaml_path)`` when
            only the YAML path is known, otherwise just ``file``.
        """
        if self.line is not None:
            return f"{self.file}:{self.line}"
        if self.yaml_path is not None:
            return f"{self.file} ({self.yaml_path})"
        return self.file


@dataclass(frozen=True)
class Diagnostic:
    """One actionable problem found while loading or validating configuration.

    Frozen and hashable; ordered deterministically by
    ``(location.file, location.line or 0, code)`` so reports are stable
    across runs and platforms.  ``remedy`` is mandatory and non-empty.

    Attributes:
        code: Stable, greppable code matching ``TSWAP-[CS]\\d{3}``.
        severity: Whether this diagnostic makes the config invalid.
        message: What is wrong, naming the offending key/value.
        location: Where in the file the problem was found.
        remedy: What to do about it — mandatory, non-empty.
    """

    code: str
    severity: Severity
    message: str
    location: Location
    remedy: str

    def __post_init__(self) -> None:
        """Validate ``code`` format and mandatory ``remedy`` at construction."""
        if _CODE_PATTERN.fullmatch(self.code) is None:
            raise ValueError(
                "Diagnostic code must match pattern 'TSWAP-[CS]\\d{3}' "
                f"(a code starting with 'TSWAP-'); got {self.code!r}"
            )
        if not self.remedy.strip():
            raise ValueError("Diagnostic 'remedy' must be a non-empty string.")

    def __lt__(self, other: object) -> bool:
        """Order by ``(file, line or 0, code)``; ``line=None`` sorts as 0."""
        if not isinstance(other, Diagnostic):
            return NotImplemented
        return (self.location.file, self.location.line or 0, self.code) < (
            other.location.file,
            other.location.line or 0,
            other.code,
        )


@dataclass(frozen=True)
class ConfigReport:
    """Aggregate of the diagnostics produced for one config load.

    One report shape, three consumers: the human ``render()``, the
    ``to_json()`` payload, and the raised ``ConfigError``.

    Attributes:
        diagnostics: All diagnostics, in the given order; they are served
            in deterministic sort order by every view.
    """

    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        """Accept any iterable of diagnostics and normalize it to a tuple."""
        if not isinstance(self.diagnostics, tuple):
            object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    @property
    def errors(self) -> list[Diagnostic]:
        """ERROR-severity diagnostics, deterministically ordered."""
        return [d for d in sorted(self.diagnostics) if d.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        """WARNING-severity diagnostics, deterministically ordered."""
        return [d for d in sorted(self.diagnostics) if d.severity is Severity.WARNING]

    @property
    def ok(self) -> bool:
        """True iff there are no ERROR-severity diagnostics."""
        return not self.errors

    @property
    def exit_code(self) -> int:
        """0 when ok else 1 (the CLI's exit-2 is a later behaviour's concern)."""
        return 0 if self.ok else 1

    def render(self) -> str:
        """Render one block per diagnostic in sort order.

        Returns:
            Blocks of ``SEVERITY CODE location``, the message, and an
            indented ``remedy:`` line, separated by one blank line with a
            trailing newline; the empty string when there are no
            diagnostics (the caller owns the success message).
        """
        if not self.diagnostics:
            return ""
        blocks = [
            f"{d.severity.name} {d.code} {d.location.render()}\n"
            f"{d.message}\n"
            f"  remedy: {d.remedy}\n"
            for d in sorted(self.diagnostics)
        ]
        return "\n".join(blocks)

    def to_json(self) -> str:
        """Serialize the report as a JSON list, in the same sort order.

        Returns:
            ``json.dumps`` of a list of objects with exactly the keys
            ``code, severity, message, file, yaml_path, line, remedy``;
            severity is its lowercase value, absent location parts are
            ``null``; ``"[]"`` when empty.
        """
        payload = [
            {
                "code": d.code,
                "severity": d.severity.value,
                "message": d.message,
                "file": d.location.file,
                "yaml_path": d.location.yaml_path,
                "line": d.location.line,
                "remedy": d.remedy,
            }
            for d in sorted(self.diagnostics)
        ]
        return json.dumps(payload)


class ConfigError(Exception):
    """Raised form of a failed config load; always carries the report.

    Attributes:
        report: The ``ConfigReport`` this error was constructed with.
    """

    def __init__(self, report: ConfigReport) -> None:
        """Store the report; a report-less ``ConfigError`` is a TypeError.

        Args:
            report: The config report to attach to the exception.
        """
        super().__init__(report)
        self.report = report
