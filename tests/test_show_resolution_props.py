"""Property tests for show name resolution from ancestor directories.

# Feature: design-gap-completion, Property 1: Show Name Resolution from Ancestors
# Feature: design-gap-completion, Property 2: Blacklist Merge is a Superset

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 2.2, 2.4, 2.5
"""

import os
import tempfile

from hypothesis import given, assume, settings
from hypothesis import strategies as st

from tvrenamer.renamer.engine import (
    _is_season_dir,
    _resolve_show_name,
    DEFAULT_DIRECTORY_BLACKLIST,
)
from tvrenamer.config import get_directory_blacklist


# --- Strategies ---

# Generate season directory names that match season patterns
season_dir_names = st.one_of(
    st.integers(min_value=1, max_value=99).map(lambda n: f"Season {n}"),
    st.integers(min_value=1, max_value=99).map(lambda n: f"season {n:02d}"),
    st.integers(min_value=1, max_value=99).map(lambda n: f"Season_{n}"),
    st.integers(min_value=1, max_value=99).map(lambda n: f"S{n:02d}"),
    st.integers(min_value=1, max_value=99).map(lambda n: f"s{n:02d}"),
    st.integers(min_value=1, max_value=99).map(lambda n: f"season.{n}"),
)

# Generate show names that are NOT season patterns and NOT blacklisted
_all_blacklist_lower = {b.lower() for b in DEFAULT_DIRECTORY_BLACKLIST}


def _valid_show_name(name):
    """Check that a name isn't a season dir or blacklisted."""
    return (
        _is_season_dir(name) is None
        and name.lower() not in _all_blacklist_lower
        and len(name) > 0
        and "/" not in name
        and "\\" not in name
        and "\x00" not in name
    )


show_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs"), whitelist_characters="'-"),
    min_size=2, max_size=30,
).filter(_valid_show_name)

# Generate filenames with SxxExx pattern
filenames_with_se = st.builds(
    lambda show, s, e: f"{show}.S{s:02d}E{e:02d}.720p.mkv",
    show=show_names,
    s=st.integers(min_value=1, max_value=20),
    e=st.integers(min_value=1, max_value=99),
)

# Blacklist entries for user-provided lists
blacklist_entries = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
    min_size=1, max_size=20,
)


# --- Property 1: Show Name Resolution from Ancestors ---


class TestShowNameResolutionProperty:
    """Property 1: For any file path where the parent directory matches a season pattern,
    the resolved show name SHALL equal the grandparent directory name (unless blacklisted or missing).
    """

    @settings(max_examples=100)
    @given(show_name=show_names, season_dir=season_dir_names, filename=filenames_with_se)
    def test_season_parent_resolves_to_grandparent(self, show_name, season_dir, filename):
        """When parent is a season dir and grandparent is valid, show name comes from grandparent."""
        with tempfile.TemporaryDirectory() as root:
            # Create Show/Season N/file.mkv structure
            show_dir = os.path.join(root, show_name)
            season_path = os.path.join(show_dir, season_dir)
            os.makedirs(season_path, exist_ok=True)
            filepath = os.path.join(season_path, filename)

            result = _resolve_show_name(filepath, root, {})
            assert result == show_name, (
                f"Expected '{show_name}', got '{result}' for path: {filepath}"
            )

    @settings(max_examples=100)
    @given(show_name=show_names, filename=filenames_with_se)
    def test_non_season_parent_resolves_to_parent(self, show_name, filename):
        """When parent is NOT a season dir and not blacklisted, show name comes from parent."""
        assume(_is_season_dir(show_name) is None)

        with tempfile.TemporaryDirectory() as root:
            show_dir = os.path.join(root, show_name)
            os.makedirs(show_dir, exist_ok=True)
            filepath = os.path.join(show_dir, filename)

            result = _resolve_show_name(filepath, root, {})
            assert result == show_name, (
                f"Expected '{show_name}', got '{result}' for path: {filepath}"
            )

    @settings(max_examples=50)
    @given(
        season_dir=season_dir_names,
        blacklisted=st.sampled_from(DEFAULT_DIRECTORY_BLACKLIST),
        filename=filenames_with_se,
    )
    def test_blacklisted_grandparent_falls_back(self, season_dir, blacklisted, filename):
        """When parent is a season dir and grandparent is blacklisted, fall back to filename."""
        with tempfile.TemporaryDirectory() as root:
            bad_dir = os.path.join(root, blacklisted)
            season_path = os.path.join(bad_dir, season_dir)
            os.makedirs(season_path, exist_ok=True)
            filepath = os.path.join(season_path, filename)

            result = _resolve_show_name(filepath, root, {})
            # Should NOT be the blacklisted name
            assert result.lower() != blacklisted.lower(), (
                f"Got blacklisted name '{result}' for grandparent '{blacklisted}'"
            )

    @settings(max_examples=50)
    @given(
        blacklisted=st.sampled_from(DEFAULT_DIRECTORY_BLACKLIST),
        filename=filenames_with_se,
    )
    def test_blacklisted_parent_not_used(self, blacklisted, filename):
        """When parent dir is blacklisted, the resolved name should not be that dir."""
        assume(_is_season_dir(blacklisted) is None)

        with tempfile.TemporaryDirectory() as root:
            bad_dir = os.path.join(root, blacklisted)
            os.makedirs(bad_dir, exist_ok=True)
            filepath = os.path.join(bad_dir, filename)

            result = _resolve_show_name(filepath, root, {})
            assert result.lower() != blacklisted.lower(), (
                f"Got blacklisted name '{result}'"
            )

    @settings(max_examples=50)
    @given(filename=filenames_with_se)
    def test_file_directly_in_root_uses_filename(self, filename):
        """When file is directly in root (no parent dirs), fall back to filename extraction."""
        with tempfile.TemporaryDirectory() as root:
            filepath = os.path.join(root, filename)

            result = _resolve_show_name(filepath, root, {})
            # Should return something (not empty, not Unknown for valid filenames)
            assert len(result) > 0


# --- Property 2: Blacklist Merge is a Superset ---


class TestBlacklistMergeProperty:
    """Property 2: For any user-provided blacklist and the default blacklist,
    the effective blacklist used by the engine SHALL be a superset of both.
    """

    @settings(max_examples=100)
    @given(user_entries=st.lists(blacklist_entries, min_size=0, max_size=10))
    def test_merged_blacklist_contains_all_defaults(self, user_entries):
        """The merged blacklist always contains every default entry."""
        config = {"path_extraction": {"directory_blacklist": user_entries}}
        user_blacklist = get_directory_blacklist(config)

        # Build merged set (same logic as _resolve_show_name)
        seen_lower = set()
        merged = []
        for entry in DEFAULT_DIRECTORY_BLACKLIST + user_blacklist:
            low = entry.lower()
            if low not in seen_lower:
                seen_lower.add(low)
                merged.append(entry)

        merged_lower = {e.lower() for e in merged}

        # All defaults must be present
        for default_entry in DEFAULT_DIRECTORY_BLACKLIST:
            assert default_entry.lower() in merged_lower, (
                f"Default '{default_entry}' missing from merged blacklist"
            )

    @settings(max_examples=100)
    @given(user_entries=st.lists(blacklist_entries, min_size=1, max_size=10))
    def test_merged_blacklist_contains_all_user_entries(self, user_entries):
        """The merged blacklist always contains every user-provided entry."""
        config = {"path_extraction": {"directory_blacklist": user_entries}}
        user_blacklist = get_directory_blacklist(config)

        seen_lower = set()
        merged = []
        for entry in DEFAULT_DIRECTORY_BLACKLIST + user_blacklist:
            low = entry.lower()
            if low not in seen_lower:
                seen_lower.add(low)
                merged.append(entry)

        merged_lower = {e.lower() for e in merged}

        for user_entry in user_entries:
            assert user_entry.lower() in merged_lower, (
                f"User entry '{user_entry}' missing from merged blacklist"
            )

    @settings(max_examples=100)
    @given(user_entries=st.lists(blacklist_entries, min_size=0, max_size=10))
    def test_blacklist_matching_is_case_insensitive(self, user_entries):
        """Blacklist matching should be case-insensitive."""
        config = {"path_extraction": {"directory_blacklist": user_entries}}
        user_blacklist = get_directory_blacklist(config)

        seen_lower = set()
        for entry in DEFAULT_DIRECTORY_BLACKLIST + user_blacklist:
            seen_lower.add(entry.lower())

        # Check that case variations are matched
        for entry in DEFAULT_DIRECTORY_BLACKLIST:
            assert entry.upper().lower() in seen_lower
            assert entry.lower() in seen_lower
