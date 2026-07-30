"""Property tests for scene tag removal.

# Feature: design-gap-completion, Property 3: Scene Tag and Group Tag Removal

Validates: Requirements 3.2, 3.4, 3.7
"""

import re

from hypothesis import given, assume, settings
from hypothesis import strategies as st

from tvrenamer.renamer.engine import _strip_scene_tags
from tvrenamer.config import DEFAULT_SCENE_TAGS_STRIP, DEFAULT_GROUP_TAG_PATTERNS


# --- Strategies ---

# Generate base show names (simple words)
base_words = st.text(
    alphabet=st.characters(whitelist_categories=("L",)),
    min_size=2, max_size=12,
)

show_names = st.lists(base_words, min_size=1, max_size=4).map(lambda ws: " ".join(ws))

# Pick some scene tags to inject
scene_tags = st.sampled_from(DEFAULT_SCENE_TAGS_STRIP)

# Generate separators used in scene releases
separators = st.sampled_from([".", "_", "-", " "])


class TestSceneTagRemovalProperty:
    """Property 3: For any filename and any subset of configured scene tags injected
    into that filename, after cleaning, the output SHALL contain none of the injected tags.
    """

    @settings(max_examples=100)
    @given(
        show=show_names,
        tags=st.lists(scene_tags, min_size=1, max_size=5, unique=True),
        sep=separators,
    )
    def test_injected_tags_removed(self, show, tags, sep):
        """Tags injected into filename should not appear in the cleaned result."""
        # Build a filename like "Show.Name.PROPER.720p.x264"
        parts = [show.replace(" ", sep)] + tags
        filename = sep.join(parts)

        result = _strip_scene_tags(filename, {})

        # None of the injected tags should remain (case-insensitive word check)
        for tag in tags:
            # Check that tag is not present as a standalone word
            pattern = r"(?<!\S)" + re.escape(tag) + r"(?!\S)"
            assert not re.search(pattern, result, re.IGNORECASE), (
                f"Tag '{tag}' still present in result '{result}' from input '{filename}'"
            )

    @settings(max_examples=100)
    @given(
        show=show_names,
        tags=st.lists(scene_tags, min_size=1, max_size=3, unique=True),
    )
    def test_show_name_preserved(self, show, tags):
        """The base show name words should survive tag removal."""
        # Use dots as separator (common scene format)
        parts = [show.replace(" ", ".")] + tags
        filename = ".".join(parts)

        result = _strip_scene_tags(filename, {})

        # Show name words should be in the result (case-insensitive)
        for word in show.split():
            if word.lower() not in {t.lower() for t in DEFAULT_SCENE_TAGS_STRIP}:
                assert word.lower() in result.lower(), (
                    f"Show word '{word}' missing from result '{result}'"
                )

    @settings(max_examples=50)
    @given(show=show_names)
    def test_group_tags_removed(self, show):
        """Group tags like [GroupName] or -GroupName at end should be removed."""
        # Test bracket group tag
        filename_bracket = f"{show} [YIFY]"
        result = _strip_scene_tags(filename_bracket, {})
        assert "YIFY" not in result, (
            f"Group tag '[YIFY]' not removed from result '{result}'"
        )

        # Test dash group tag at end
        filename_dash = f"{show}-SPARKS"
        result2 = _strip_scene_tags(filename_dash, {})
        assert "SPARKS" not in result2, (
            f"Group tag '-SPARKS' not removed from result '{result2}'"
        )

    @settings(max_examples=100)
    @given(show=show_names)
    def test_empty_strip_list_preserves_tags(self, show):
        """When strip list is empty, no scene tags are removed."""
        filename = f"{show} PROPER 720p"
        config = {"scene_tags": {"strip": [], "group_tag_patterns": []}}

        result = _strip_scene_tags(filename, config)
        # Tags should remain since strip list is empty
        assert "PROPER" in result
        assert "720p" in result

    @settings(max_examples=50)
    @given(
        show=show_names,
        tags=st.lists(scene_tags, min_size=1, max_size=5, unique=True),
    )
    def test_no_consecutive_whitespace_in_result(self, show, tags):
        """The result should never have consecutive whitespace."""
        parts = [show.replace(" ", ".")] + tags
        filename = ".".join(parts)

        result = _strip_scene_tags(filename, {})
        assert "  " not in result, (
            f"Double space found in result '{result}'"
        )

    @settings(max_examples=50)
    @given(
        show=show_names,
        tags=st.lists(scene_tags, min_size=1, max_size=3, unique=True),
    )
    def test_cleaning_order_separators_before_tags(self, show, tags):
        """Separator normalization happens before tag removal (dots become spaces first)."""
        # Use dots - tags like "720p" have dots normalized away before matching
        parts = [show.replace(" ", ".")] + tags
        filename = ".".join(parts)

        result = _strip_scene_tags(filename, {})
        # No dots should remain (normalized to spaces)
        assert "." not in result, (
            f"Dots still present in result '{result}'"
        )
