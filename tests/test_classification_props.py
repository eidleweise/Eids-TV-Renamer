"""Property tests for file classification.

# Feature: design-gap-completion, Property 7: File Classification Determinism and Correctness

Validates: Requirements 10.4
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from tvrenamer.renamer.engine import _classify_file, VIDEO_EXTS, SUBTITLE_EXTS


# --- Strategies ---

video_exts = st.sampled_from(sorted(VIDEO_EXTS))
subtitle_exts = st.sampled_from(sorted(SUBTITLE_EXTS))

# Generate junk extensions (not overlapping with video/subtitle)
_reserved_exts = VIDEO_EXTS | SUBTITLE_EXTS
junk_ext_candidates = st.sampled_from(
    [".nfo", ".txt", ".url", ".jpg", ".jpeg", ".png", ".bmp", ".tbn", ".sfv"]
)

# Generate random unknown extensions
unknown_exts = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz",
    min_size=2, max_size=5,
).map(lambda s: f".{s}").filter(
    lambda e: e not in VIDEO_EXTS
    and e not in SUBTITLE_EXTS
    and e not in {".nfo", ".txt", ".url", ".jpg", ".jpeg", ".png", ".bmp", ".tbn", ".sfv"}
)

# Junk extension sets
junk_sets = st.frozensets(junk_ext_candidates, min_size=1, max_size=9).map(set)


class TestFileClassificationProperty:
    """Property 7: For any file extension, the classification function SHALL assign
    exactly one category, and the assigned category SHALL match the configured
    extension sets.
    """

    @settings(max_examples=100)
    @given(ext=video_exts, junk=junk_sets)
    def test_video_extensions_classified_as_video(self, ext, junk):
        """Any known video extension classifies as 'video'."""
        result = _classify_file(ext, junk)
        assert result == "video", f"Extension '{ext}' should be 'video', got '{result}'"

    @settings(max_examples=100)
    @given(ext=video_exts, junk=junk_sets)
    def test_video_extensions_case_insensitive(self, ext, junk):
        """Video classification is case-insensitive."""
        assert _classify_file(ext.upper(), junk) == "video"
        assert _classify_file(ext.lower(), junk) == "video"
        # Mixed case
        mixed = ext[0] + ext[1:].upper() if len(ext) > 1 else ext.upper()
        assert _classify_file(mixed, junk) == "video"

    @settings(max_examples=100)
    @given(ext=subtitle_exts, junk=junk_sets)
    def test_subtitle_extensions_classified_as_subtitle(self, ext, junk):
        """Any known subtitle extension classifies as 'subtitle'."""
        result = _classify_file(ext, junk)
        assert result == "subtitle", f"Extension '{ext}' should be 'subtitle', got '{result}'"

    @settings(max_examples=100)
    @given(ext=subtitle_exts, junk=junk_sets)
    def test_subtitle_extensions_case_insensitive(self, ext, junk):
        """Subtitle classification is case-insensitive."""
        assert _classify_file(ext.upper(), junk) == "subtitle"
        assert _classify_file(ext.lower(), junk) == "subtitle"

    @settings(max_examples=100)
    @given(ext=junk_ext_candidates, junk=junk_sets)
    def test_junk_extensions_classified_as_junk(self, ext, junk):
        """Extensions in the junk set classify as 'junk'."""
        # Ensure this ext is actually in the junk set for this test
        junk_with_ext = junk | {ext}
        result = _classify_file(ext, junk_with_ext)
        assert result == "junk", f"Extension '{ext}' should be 'junk', got '{result}'"

    @settings(max_examples=100)
    @given(ext=unknown_exts, junk=junk_sets)
    def test_unknown_extensions_classified_as_unknown(self, ext, junk):
        """Extensions not in any known set classify as 'unknown'."""
        result = _classify_file(ext, junk)
        assert result == "unknown", f"Extension '{ext}' should be 'unknown', got '{result}'"

    @settings(max_examples=200)
    @given(
        ext=st.one_of(video_exts, subtitle_exts, junk_ext_candidates, unknown_exts),
        junk=junk_sets,
    )
    def test_exactly_one_category(self, ext, junk):
        """Every extension is assigned exactly one category."""
        result = _classify_file(ext, junk)
        assert result in {"video", "subtitle", "junk", "unknown"}, (
            f"Invalid category '{result}' for extension '{ext}'"
        )

    @settings(max_examples=100)
    @given(ext=video_exts, junk=junk_sets)
    def test_video_priority_over_junk(self, ext, junk):
        """Even if a video extension is added to junk set, video classification wins."""
        # Video extensions should never be classified as junk
        junk_with_video = junk | {ext}
        result = _classify_file(ext, junk_with_video)
        assert result == "video", (
            f"Video ext '{ext}' misclassified as '{result}' even when in junk set"
        )

    @settings(max_examples=100)
    @given(ext=subtitle_exts, junk=junk_sets)
    def test_subtitle_priority_over_junk(self, ext, junk):
        """Even if a subtitle extension is added to junk set, subtitle classification wins."""
        junk_with_sub = junk | {ext}
        result = _classify_file(ext, junk_with_sub)
        assert result == "subtitle", (
            f"Subtitle ext '{ext}' misclassified as '{result}' even when in junk set"
        )
