from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CheckpointCompatibilityIssue:
    """One machine-readable checkpoint compatibility problem."""

    code: str
    message: str
    checkpoint_value: str | None = None
    current_value: str | None = None
    missing: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CheckpointCompatibilityReport:
    """Read-only result of checking a checkpoint against an Agent."""

    issues: tuple[CheckpointCompatibilityIssue, ...] = ()

    @property
    def compatible(self) -> bool:
        return not self.issues

    @property
    def errors(self) -> tuple[str, ...]:
        """Human-readable messages for display and logging."""
        return tuple(issue.message for issue in self.issues)


class IncompatibleCheckpointError(ValueError):
    """Raised when an Agent cannot interpret a checkpoint."""

    def __init__(self, report: CheckpointCompatibilityReport) -> None:
        self.report = report
        details = "; ".join(report.errors)
        super().__init__(f"Incompatible checkpoint: {details}")
