"""Custom exceptions for PIGE with helpful error messages."""

from __future__ import annotations


class ProjectNotFoundError(ValueError):
    """Raised when a project ID cannot be found."""
    
    def __init__(self, project_id: str):
        super().__init__(
            f"Project '{project_id}' not found.\n"
            f"Tip: Use 'python -m pige project list' to see available projects."
        )
        self.project_id = project_id


class EntryNotFoundError(ValueError):
    """Raised when an entry ID cannot be found."""
    
    def __init__(self, entry_id: str):
        super().__init__(
            f"Entry '{entry_id}' not found.\n"
            f"The entry may have been deleted or the ID is incorrect."
        )
        self.entry_id = entry_id


class TaskNotFoundError(ValueError):
    """Raised when a task ID cannot be found."""
    
    def __init__(self, task_id: str):
        super().__init__(
            f"Task '{task_id}' not found.\n"
            f"The task may have been deleted or moved to another project."
        )
        self.task_id = task_id


class InvalidDateRangeError(ValueError):
    """Raised when a date range is invalid (from > to)."""
    
    def __init__(self, from_date, to_date):
        super().__init__(
            f"Invalid date range: {from_date} to {to_date}.\n"
            f"The start date must be before or equal to the end date."
        )
        self.from_date = from_date
        self.to_date = to_date


class InvalidEntryTypeError(ValueError):
    """Raised when an entry type is not valid."""
    
    def __init__(self, entry_type: str, valid_types: tuple[str, ...]):
        valid_str = ", ".join(valid_types)
        super().__init__(
            f"Invalid entry type '{entry_type}'.\n"
            f"Valid types are: {valid_str}"
        )
        self.entry_type = entry_type
        self.valid_types = valid_types


class MeetingHoursError(ValueError):
    """Raised when meeting start/end hours are invalid."""
    
    def __init__(self, message: str):
        super().__init__(
            f"{message}\n"
            f"Meeting hours must be in HH:MM format, and start must be before end."
        )


class TimerAlreadyRunningError(ValueError):
    """Raised when trying to start a timer while one is already running."""
    
    def __init__(self, current_project_id: str):
        super().__init__(
            f"Timer is already running for project '{current_project_id}'.\n"
            f"Tip: Stop the current timer with 'python -m pige time stop' before starting a new one."
        )
        self.current_project_id = current_project_id


class TimerNotRunningError(ValueError):
    """Raised when trying to stop a timer that is not running."""
    
    def __init__(self):
        super().__init__(
            "No timer is currently running.\n"
            "Tip: Start a timer with 'python -m pige time start <PROJECT_ID>'"
        )


class BackupFormatError(ValueError):
    """Raised when a backup file format is not recognized."""
    
    def __init__(self, path: str):
        super().__init__(
            f"Backup format not recognized: {path}\n"
            f"The file must be a valid PIGE backup zip created with 'python -m pige backup'."
        )
        self.path = path
