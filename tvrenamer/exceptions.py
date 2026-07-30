"""Custom exception types for tvrenamer.

Each exception maps to a specific exit code for structured error reporting.
The CLI catches these exceptions and translates them to the appropriate
process exit code.
"""

from enum import IntEnum


class ExitCode(IntEnum):
    """Process exit codes for tvrenamer."""

    SUCCESS = 0
    NO_MEDIA = 1
    API_ERROR = 2
    FILE_ERROR = 3
    INVALID_ARGS = 4


class TVRenamerError(Exception):
    """Base exception for all tvrenamer errors."""

    exit_code: int = 1

    def __init__(self, message: str = ""):
        super().__init__(message)


class NoMediaFoundError(TVRenamerError):
    """Raised when no media files are found in the target directory.

    Exit code: 1 (NO_MEDIA)
    """

    exit_code = ExitCode.NO_MEDIA


class ProviderError(TVRenamerError):
    """Raised when API/provider failures prevent metadata lookup.

    Exit code: 2 (API_ERROR)
    """

    exit_code = ExitCode.API_ERROR


class FileOperationError(TVRenamerError):
    """Raised when file operations fail (permission denied, disk full, rename failure).

    Exit code: 3 (FILE_ERROR)
    """

    exit_code = ExitCode.FILE_ERROR


class InvalidConfigError(TVRenamerError):
    """Raised when invalid arguments or unreadable configuration are provided.

    Exit code: 4 (INVALID_ARGS)
    """

    exit_code = ExitCode.INVALID_ARGS
