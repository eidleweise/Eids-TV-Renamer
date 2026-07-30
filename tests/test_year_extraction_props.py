"""Property tests for year extraction positioning.

# Feature: design-gap-completion, Property 4: Year Extraction Positioning

Validates: Requirements 4.1, 4.2
"""

from hypothesis import given, assume, settings
from hypothesis import strategies as st

from tvrenamer.renamer.engine import _extract_year


# --- Strategies ---

# Generate years in valid range
valid_years = st.integers(min_value=1950, max_value=2099)

# Generate show name words (no digits to avoid false matches)
show_words = st.text(
    alphabet=st.characters(whitelist_categories=("L",)),
    min_size=2, max_size=10,
)

show_names = st.lists(show_words, min_size=1, max_size=3).map(lambda ws: " ".join(ws))

# Generate season/episode numbers
seasons = st.integers(min_value=1, max_value=20)
episodes = st.integers(min_value=1, max_value=99)


class TestYearExtractionProperty:
    """Property 4: For any filename containing a year positioned before any SxxExx marker,
    the engine SHALL extract that number as the year. For numbers appearing only after a
    marker, the engine SHALL NOT extract it as the year.
    """

    @settings(max_examples=100)
    @given(show=show_names, year=valid_years, s=seasons, e=episodes)
    def test_year_before_se_marker_is_extracted(self, show, year, s, e):
        """Year before SxxExx marker should be extracted."""
        filename = f"{show} {year} S{s:02d}E{e:02d}"

        cleaned, extracted_year = _extract_year(filename)
        assert extracted_year == year, (
            f"Expected year {year}, got {extracted_year} from '{filename}'"
        )
        assert str(year) not in cleaned, (
            f"Year {year} still in cleaned name '{cleaned}'"
        )

    @settings(max_examples=100)
    @given(show=show_names, year=valid_years, s=seasons, e=episodes)
    def test_year_after_se_marker_not_extracted(self, show, year, s, e):
        """Year after SxxExx marker should NOT be extracted."""
        filename = f"{show} S{s:02d}E{e:02d} {year}"

        _, extracted_year = _extract_year(filename)
        assert extracted_year is None, (
            f"Year {year} should NOT be extracted from '{filename}', got {extracted_year}"
        )

    @settings(max_examples=100)
    @given(show=show_names, year=valid_years)
    def test_year_without_se_marker_is_extracted(self, show, year):
        """Year in filename without any SE marker should be extracted."""
        filename = f"{show} {year}"

        cleaned, extracted_year = _extract_year(filename)
        assert extracted_year == year, (
            f"Expected year {year}, got {extracted_year} from '{filename}'"
        )
        assert str(year) not in cleaned, (
            f"Year {year} still in cleaned name '{cleaned}'"
        )

    @settings(max_examples=100)
    @given(show=show_names)
    def test_no_year_returns_none(self, show):
        """Filename without any 4-digit year returns None."""
        assume(not any(c.isdigit() for c in show))
        filename = f"{show} S01E01"

        cleaned, extracted_year = _extract_year(filename)
        assert extracted_year is None, (
            f"Unexpected year {extracted_year} from '{filename}'"
        )

    @settings(max_examples=50)
    @given(show=show_names, year=valid_years, s=seasons, e=episodes)
    def test_cleaned_name_preserves_show(self, show, year, s, e):
        """Show name words should be preserved after year extraction."""
        filename = f"{show} {year} S{s:02d}E{e:02d}"

        cleaned, _ = _extract_year(filename)
        for word in show.split():
            assert word in cleaned, (
                f"Show word '{word}' missing from cleaned '{cleaned}'"
            )

    @settings(max_examples=50)
    @given(
        show=show_names,
        year1=valid_years,
        year2=valid_years,
        s=seasons,
        e=episodes,
    )
    def test_last_year_before_marker_wins(self, show, year1, year2, s, e):
        """When multiple years appear before SE marker, the last one is extracted."""
        assume(year1 != year2)
        filename = f"{show} {year1} extra {year2} S{s:02d}E{e:02d}"

        _, extracted_year = _extract_year(filename)
        assert extracted_year == year2, (
            f"Expected last year {year2}, got {extracted_year} from '{filename}'"
        )

    @settings(max_examples=50)
    @given(show=show_names, year=valid_years)
    def test_year_in_range_boundaries(self, show, year):
        """Years at boundary values (1950, 2099) should be extracted."""
        filename = f"{show} {year}"

        _, extracted_year = _extract_year(filename)
        assert extracted_year == year

    @settings(max_examples=50)
    @given(show=show_names, bad_year=st.integers(min_value=2100, max_value=9999))
    def test_year_out_of_range_not_extracted(self, show, bad_year):
        """Numbers outside 1950-2099 should NOT be treated as years."""
        assume(not any(c.isdigit() for c in show))
        filename = f"{show} {bad_year}"

        _, extracted_year = _extract_year(filename)
        assert extracted_year is None, (
            f"Out-of-range year {bad_year} should not be extracted from '{filename}'"
        )
