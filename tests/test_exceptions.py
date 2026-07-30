"""Tests for tvrenamer.exceptions module."""

from tvrenamer.exceptions import (
    ExitCode,
    TVRenamerError,
    NoMediaFoundError,
    ProviderError,
    FileOperationError,
    InvalidConfigError,
)


class TestExitCodes:
    """Verify exit code enum values."""

    def test_success_is_zero(self):
        assert ExitCode.SUCCESS == 0

    def test_no_media_is_one(self):
        assert ExitCode.NO_MEDIA == 1

    def test_api_error_is_two(self):
        assert ExitCode.API_ERROR == 2

    def test_file_error_is_three(self):
        assert ExitCode.FILE_ERROR == 3

    def test_invalid_args_is_four(self):
        assert ExitCode.INVALID_ARGS == 4


class TestExceptionHierarchy:
    """Verify all custom exceptions inherit from TVRenamerError."""

    def test_no_media_found_is_tvrenamer_error(self):
        assert issubclass(NoMediaFoundError, TVRenamerError)

    def test_provider_error_is_tvrenamer_error(self):
        assert issubclass(ProviderError, TVRenamerError)

    def test_file_operation_error_is_tvrenamer_error(self):
        assert issubclass(FileOperationError, TVRenamerError)

    def test_invalid_config_error_is_tvrenamer_error(self):
        assert issubclass(InvalidConfigError, TVRenamerError)

    def test_tvrenamer_error_is_exception(self):
        assert issubclass(TVRenamerError, Exception)


class TestExceptionExitCodes:
    """Verify each exception maps to the correct exit code."""

    def test_no_media_found_exit_code(self):
        assert NoMediaFoundError.exit_code == ExitCode.NO_MEDIA

    def test_provider_error_exit_code(self):
        assert ProviderError.exit_code == ExitCode.API_ERROR

    def test_file_operation_error_exit_code(self):
        assert FileOperationError.exit_code == ExitCode.FILE_ERROR

    def test_invalid_config_error_exit_code(self):
        assert InvalidConfigError.exit_code == ExitCode.INVALID_ARGS


class TestExceptionMessages:
    """Verify exceptions carry messages properly."""

    def test_no_media_with_message(self):
        err = NoMediaFoundError("No video files found in /tmp/media")
        assert str(err) == "No video files found in /tmp/media"

    def test_provider_error_with_message(self):
        err = ProviderError("TVMaze API returned 503")
        assert str(err) == "TVMaze API returned 503"

    def test_file_operation_error_with_message(self):
        err = FileOperationError("Permission denied: /media/show.mkv")
        assert str(err) == "Permission denied: /media/show.mkv"

    def test_invalid_config_error_with_message(self):
        err = InvalidConfigError("Unreadable config: /etc/tvrenamer.toml")
        assert str(err) == "Unreadable config: /etc/tvrenamer.toml"

    def test_default_empty_message(self):
        err = TVRenamerError()
        assert str(err) == ""

    def test_catchable_as_base_type(self):
        """Verify all exceptions can be caught via the base TVRenamerError."""
        exceptions = [
            NoMediaFoundError("test"),
            ProviderError("test"),
            FileOperationError("test"),
            InvalidConfigError("test"),
        ]
        for exc in exceptions:
            try:
                raise exc
            except TVRenamerError as caught:
                assert caught.exit_code > 0
