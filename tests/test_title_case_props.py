"""Property tests for title casing rules.

# Feature: design-gap-completion, Property 5: Title Casing Rules

Validates: Requirements 5.1, 5.2, 5.3, 5.4
"""

from hypothesis import given, assume, settings
from hypothesis import strategies as st

from tvrenamer.renamer.engine import _title_case, SHORT_WORDS


# --- Strategies ---

# Generate words (lowercase ASCII alpha only - avoids Unicode chars without upper/lower forms)
lowercase_words = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz",
    min_size=1, max_size=12,
)

# Generate multi-word strings
multi_word_strings = st.lists(lowercase_words, min_size=1, max_size=6).map(
    lambda ws: " ".join(ws)
)

# Generate acronyms (2-5 uppercase ASCII letters)
acronyms = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    min_size=2, max_size=5,
)

# Generate short words from the defined set
short_words_st = st.sampled_from(sorted(SHORT_WORDS))


class TestTitleCaseProperty:
    """Property 5: Title casing function produces output where:
    (a) first word is always capitalized
    (b) short words are lowercase when not first
    (c) all-uppercase 2-5 char words are preserved
    (d) all other words have first letter capitalized
    """

    @settings(max_examples=100)
    @given(name=multi_word_strings)
    def test_first_word_always_capitalized(self, name):
        """The first word is always capitalized."""
        assume(len(name.strip()) > 0)
        result = _title_case(name)
        if result:
            first_word = result.split()[0]
            assert first_word[0].isupper(), (
                f"First word '{first_word}' not capitalized in '{result}'"
            )

    @settings(max_examples=100)
    @given(
        prefix_words=st.lists(lowercase_words, min_size=1, max_size=3),
        short_word=short_words_st,
        suffix_words=st.lists(lowercase_words, min_size=1, max_size=3),
    )
    def test_short_words_lowercase_when_not_first(self, prefix_words, short_word, suffix_words):
        """Short words in non-first position are lowercase."""
        # Ensure prefix doesn't contain the short word to avoid ambiguity
        assume(all(w.lower() != short_word for w in prefix_words))
        assume(all(w.lower() not in SHORT_WORDS for w in prefix_words))
        assume(all(w.lower() not in SHORT_WORDS for w in suffix_words))

        words = prefix_words + [short_word] + suffix_words
        name = " ".join(words)
        result = _title_case(name)

        result_words = result.split()
        # Find the short word in result (it should be lowercase and not first)
        # The short word position = len(prefix_words)
        idx = len(prefix_words)
        if idx < len(result_words):
            assert result_words[idx] == short_word.lower(), (
                f"Short word '{short_word}' at position {idx} should be lowercase, "
                f"got '{result_words[idx]}' in '{result}'"
            )

    @settings(max_examples=100)
    @given(short_word=short_words_st, suffix=multi_word_strings)
    def test_short_word_capitalized_when_first(self, short_word, suffix):
        """Short words in first position are capitalized."""
        assume(len(suffix.strip()) > 0)
        name = f"{short_word} {suffix}"
        result = _title_case(name)

        first_word = result.split()[0]
        assert first_word[0].isupper(), (
            f"First word '{first_word}' should be capitalized even though "
            f"it's a short word, in '{result}'"
        )

    @settings(max_examples=100)
    @given(
        prefix=st.lists(lowercase_words, min_size=1, max_size=2),
        acronym=acronyms,
        suffix=st.lists(lowercase_words, min_size=0, max_size=2),
    )
    def test_acronyms_preserved_uppercase(self, prefix, acronym, suffix):
        """Fully uppercase words of 2-5 characters are preserved."""
        assume(acronym.lower() not in SHORT_WORDS)
        assume(all(w.lower() not in SHORT_WORDS for w in prefix))

        words = prefix + [acronym] + suffix
        name = " ".join(words)
        result = _title_case(name)

        # The acronym should be preserved in result
        assert acronym in result, (
            f"Acronym '{acronym}' not preserved in '{result}' from '{name}'"
        )

    @settings(max_examples=100)
    @given(name=multi_word_strings)
    def test_non_short_non_acronym_words_capitalized(self, name):
        """All other words have their first letter capitalized."""
        assume(len(name.strip()) > 0)
        result = _title_case(name)

        words = result.split()
        for i, word in enumerate(words):
            if i == 0:
                # First word always capitalized
                assert word[0].isupper()
            elif word.lower() in SHORT_WORDS:
                # Short word should be lowercase
                assert word == word.lower()
            elif word.isupper() and 2 <= len(word) <= 5:
                # Acronym preserved
                pass
            else:
                # Normal word: first letter upper
                assert word[0].isupper(), (
                    f"Word '{word}' at position {i} should be capitalized in '{result}'"
                )

    @settings(max_examples=50)
    @given(name=multi_word_strings)
    def test_word_count_preserved(self, name):
        """Title casing should not add or remove words."""
        assume(len(name.strip()) > 0)
        input_words = name.split()
        result_words = _title_case(name).split()
        assert len(input_words) == len(result_words), (
            f"Word count changed: {len(input_words)} -> {len(result_words)} "
            f"for '{name}' -> '{_title_case(name)}'"
        )

    def test_empty_string(self):
        """Empty input returns empty output."""
        assert _title_case("") == ""

    def test_single_word(self):
        """Single word is capitalized."""
        assert _title_case("hello") == "Hello"

    def test_known_examples(self):
        """Verify known examples from the design doc."""
        assert _title_case("the wire") == "The Wire"
        assert _title_case("game of thrones") == "Game of Thrones"
        assert _title_case("CSI miami") == "CSI Miami"
        assert _title_case("FBI") == "FBI"
        assert _title_case("a tale of two cities") == "A Tale of Two Cities"
