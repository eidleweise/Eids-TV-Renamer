"""Property tests for exclude patterns.

# Feature: design-gap-completion, Property 8: Exclude Patterns Filter Completeness

Validates: Requirements 13.3, 13.5
"""

import os

from hypothesis import given, assume, settings
from hypothesis import strategies as st

from tvrenamer.renamer.engine import _matches_exclude


# --- Strategies ---

# Generate path components (simple directory/file names)
path_components = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-",
    min_size=1, max_size=15,
)

# Generate file extensions
file_exts = st.sampled_from([".mkv", ".mp4", ".avi", ".srt", ".nfo", ".txt", ".jpg"])

# Generate relative paths (1-3 components deep)
relative_paths = st.builds(
    lambda parts, ext: os.path.join(*parts[:-1], parts[-1] + ext) if len(parts) > 1 else parts[0] + ext,
    parts=st.lists(path_components, min_size=1, max_size=3),
    ext=file_exts,
)

# Generate glob patterns
glob_patterns = st.one_of(
    # Wildcard extension patterns like "*.nfo"
    file_exts.map(lambda e: f"*{e}"),
    # Prefix wildcard like "*sample*"
    path_components.map(lambda c: f"*{c}*"),
    # Directory prefix like "extras/*"
    path_components.map(lambda c: f"{c}/*"),
)


class TestExcludePatternProperty:
    """Property 8: For any file whose relative path matches at least one exclude
    glob pattern, that file SHALL NOT appear in processing (returns True). Files
    that match no pattern SHALL be included (returns False).
    """

    @settings(max_examples=100)
    @given(
        filename=path_components,
        ext=file_exts,
    )
    def test_exact_extension_match(self, filename, ext):
        """A file with extension .X matches the pattern '*.X'."""
        relpath = f"{filename}{ext}"
        pattern = f"*{ext}"
        assert _matches_exclude(relpath, [pattern]) is True, (
            f"'{relpath}' should match pattern '{pattern}'"
        )

    @settings(max_examples=100)
    @given(
        filename=path_components,
        ext=file_exts,
        other_ext=file_exts,
    )
    def test_non_matching_extension(self, filename, ext, other_ext):
        """A file with extension .X does not match pattern '*.Y' when X != Y."""
        assume(ext != other_ext)
        relpath = f"{filename}{ext}"
        pattern = f"*{other_ext}"
        assert _matches_exclude(relpath, [pattern]) is False, (
            f"'{relpath}' should NOT match pattern '{pattern}'"
        )

    @settings(max_examples=100)
    @given(
        dirname=path_components,
        filename=path_components,
        ext=file_exts,
    )
    def test_directory_prefix_match(self, dirname, filename, ext):
        """A file in directory 'X' matches pattern 'X/*'."""
        relpath = os.path.join(dirname, f"{filename}{ext}")
        pattern = f"{dirname}/*"
        assert _matches_exclude(relpath, [pattern]) is True, (
            f"'{relpath}' should match pattern '{pattern}'"
        )

    @settings(max_examples=100)
    @given(
        dirname=path_components,
        other_dir=path_components,
        filename=path_components,
        ext=file_exts,
    )
    def test_non_matching_directory_prefix(self, dirname, other_dir, filename, ext):
        """A file in directory 'X' does not match pattern 'Y/*' when X != Y."""
        assume(dirname != other_dir)
        relpath = os.path.join(dirname, f"{filename}{ext}")
        pattern = f"{other_dir}/*"
        assert _matches_exclude(relpath, [pattern]) is False, (
            f"'{relpath}' should NOT match pattern '{pattern}'"
        )

    @settings(max_examples=100)
    @given(
        filename=path_components,
        ext=file_exts,
        keyword=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=3, max_size=6),
    )
    def test_substring_wildcard_match(self, filename, ext, keyword):
        """A file containing keyword matches '*keyword*' pattern."""
        relpath = f"prefix{keyword}suffix{ext}"
        pattern = f"*{keyword}*"
        assert _matches_exclude(relpath, [pattern]) is True, (
            f"'{relpath}' should match pattern '{pattern}'"
        )

    @settings(max_examples=100)
    @given(relpath=relative_paths)
    def test_empty_patterns_never_match(self, relpath):
        """With no patterns, nothing is excluded."""
        assert _matches_exclude(relpath, []) is False

    @settings(max_examples=100)
    @given(
        relpath=relative_paths,
        patterns=st.lists(glob_patterns, min_size=1, max_size=5),
    )
    def test_union_semantics(self, relpath, patterns):
        """Matching any single pattern means the union matches."""
        union_result = _matches_exclude(relpath, patterns)
        individual_results = [_matches_exclude(relpath, [p]) for p in patterns]

        if any(individual_results):
            assert union_result is True, (
                f"'{relpath}' matches individual patterns but not union"
            )
        else:
            assert union_result is False, (
                f"'{relpath}' matches union but no individual pattern"
            )

    @settings(max_examples=100)
    @given(
        filename=path_components,
        ext=file_exts,
        dirname=path_components,
    )
    def test_basename_matching(self, filename, ext, dirname):
        """Pattern matching also works against just the basename."""
        relpath = os.path.join(dirname, f"{filename}{ext}")
        # Pattern that matches basename only
        pattern = f"{filename}{ext}"
        assert _matches_exclude(relpath, [pattern]) is True, (
            f"'{relpath}' should match basename pattern '{pattern}'"
        )
