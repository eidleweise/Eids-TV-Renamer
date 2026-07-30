"""Tests for tvrenamer.config accessor functions.

Covers get_directory_blacklist, get_scene_tags, get_junk_extensions,
get_defaults, and get_provider_tvmaze with present/absent/empty values.
"""

from tvrenamer.config import (
    get_directory_blacklist,
    get_scene_tags,
    get_junk_extensions,
    get_defaults,
    get_provider_tvmaze,
    DEFAULT_DIRECTORY_BLACKLIST,
    DEFAULT_SCENE_TAGS_STRIP,
    DEFAULT_GROUP_TAG_PATTERNS,
    DEFAULT_JUNK_EXTENSIONS,
)


# --- get_directory_blacklist ---


class TestGetDirectoryBlacklist:
    def test_returns_defaults_when_section_absent(self):
        result = get_directory_blacklist({})
        assert result == DEFAULT_DIRECTORY_BLACKLIST

    def test_returns_defaults_when_key_absent(self):
        result = get_directory_blacklist({"path_extraction": {}})
        assert result == DEFAULT_DIRECTORY_BLACKLIST

    def test_returns_defaults_when_value_not_list(self):
        result = get_directory_blacklist({"path_extraction": {"directory_blacklist": "oops"}})
        assert result == DEFAULT_DIRECTORY_BLACKLIST

    def test_returns_user_list_when_present(self):
        config = {"path_extraction": {"directory_blacklist": ["MyFolder", "Other"]}}
        result = get_directory_blacklist(config)
        assert result == ["MyFolder", "Other"]

    def test_returns_empty_list_when_user_provides_empty(self):
        config = {"path_extraction": {"directory_blacklist": []}}
        result = get_directory_blacklist(config)
        assert result == []

    def test_converts_entries_to_strings(self):
        config = {"path_extraction": {"directory_blacklist": [123, True]}}
        result = get_directory_blacklist(config)
        assert result == ["123", "True"]


# --- get_scene_tags ---


class TestGetSceneTags:
    def test_returns_defaults_when_section_absent(self):
        result = get_scene_tags({})
        assert result["strip"] == DEFAULT_SCENE_TAGS_STRIP
        assert result["group_tag_patterns"] == DEFAULT_GROUP_TAG_PATTERNS

    def test_returns_defaults_for_strip_when_key_absent(self):
        result = get_scene_tags({"scene_tags": {}})
        assert result["strip"] == DEFAULT_SCENE_TAGS_STRIP

    def test_returns_defaults_for_patterns_when_key_absent(self):
        result = get_scene_tags({"scene_tags": {}})
        assert result["group_tag_patterns"] == DEFAULT_GROUP_TAG_PATTERNS

    def test_returns_custom_strip_list(self):
        config = {"scene_tags": {"strip": ["PROPER", "REPACK"]}}
        result = get_scene_tags(config)
        assert result["strip"] == ["PROPER", "REPACK"]

    def test_returns_custom_patterns_list(self):
        config = {"scene_tags": {"group_tag_patterns": [r"\[.*?\]"]}}
        result = get_scene_tags(config)
        assert result["group_tag_patterns"] == [r"\[.*?\]"]

    def test_empty_strip_list_returns_empty(self):
        config = {"scene_tags": {"strip": []}}
        result = get_scene_tags(config)
        assert result["strip"] == []

    def test_strip_max_100_entries(self):
        config = {"scene_tags": {"strip": [f"TAG{i}" for i in range(150)]}}
        result = get_scene_tags(config)
        assert len(result["strip"]) == 100

    def test_strip_entry_max_30_chars(self):
        config = {"scene_tags": {"strip": ["short", "x" * 31, "ok"]}}
        result = get_scene_tags(config)
        assert "short" in result["strip"]
        assert "ok" in result["strip"]
        assert "x" * 31 not in result["strip"]

    def test_strip_entry_min_1_char(self):
        config = {"scene_tags": {"strip": ["", "valid"]}}
        result = get_scene_tags(config)
        assert "" not in result["strip"]
        assert "valid" in result["strip"]

    def test_patterns_max_20_entries(self):
        config = {"scene_tags": {"group_tag_patterns": [f"pat{i}" for i in range(30)]}}
        result = get_scene_tags(config)
        assert len(result["group_tag_patterns"]) == 20

    def test_patterns_entry_max_200_chars(self):
        config = {"scene_tags": {"group_tag_patterns": ["short", "x" * 201]}}
        result = get_scene_tags(config)
        assert "short" in result["group_tag_patterns"]
        assert "x" * 201 not in result["group_tag_patterns"]

    def test_returns_defaults_when_strip_not_list(self):
        config = {"scene_tags": {"strip": "not a list"}}
        result = get_scene_tags(config)
        assert result["strip"] == DEFAULT_SCENE_TAGS_STRIP

    def test_returns_defaults_when_patterns_not_list(self):
        config = {"scene_tags": {"group_tag_patterns": 42}}
        result = get_scene_tags(config)
        assert result["group_tag_patterns"] == DEFAULT_GROUP_TAG_PATTERNS


# --- get_junk_extensions ---


class TestGetJunkExtensions:
    def test_returns_defaults_when_section_absent(self):
        result = get_junk_extensions({})
        assert result == DEFAULT_JUNK_EXTENSIONS

    def test_returns_defaults_when_key_absent(self):
        result = get_junk_extensions({"junk": {}})
        assert result == DEFAULT_JUNK_EXTENSIONS

    def test_returns_defaults_when_list_empty(self):
        result = get_junk_extensions({"junk": {"extensions": []}})
        assert result == DEFAULT_JUNK_EXTENSIONS

    def test_returns_defaults_when_not_list(self):
        result = get_junk_extensions({"junk": {"extensions": ".nfo"}})
        assert result == DEFAULT_JUNK_EXTENSIONS

    def test_returns_custom_extensions(self):
        config = {"junk": {"extensions": [".nfo", ".txt"]}}
        result = get_junk_extensions(config)
        assert result == [".nfo", ".txt"]

    def test_converts_entries_to_strings(self):
        config = {"junk": {"extensions": [".nfo", 123]}}
        result = get_junk_extensions(config)
        assert result == [".nfo", "123"]


# --- get_defaults ---


class TestGetDefaults:
    def test_returns_all_defaults_when_section_absent(self):
        result = get_defaults({})
        assert result["fetch_titles"] is True
        assert result["strict_windows"] is False
        assert result["exclude_patterns"] == []
        assert result["space_replacement"] == ""

    def test_returns_all_defaults_when_section_empty(self):
        result = get_defaults({"defaults": {}})
        assert result["fetch_titles"] is True
        assert result["strict_windows"] is False
        assert result["exclude_patterns"] == []
        assert result["space_replacement"] == ""

    def test_fetch_titles_true(self):
        result = get_defaults({"defaults": {"fetch_titles": True}})
        assert result["fetch_titles"] is True

    def test_fetch_titles_false(self):
        result = get_defaults({"defaults": {"fetch_titles": False}})
        assert result["fetch_titles"] is False

    def test_fetch_titles_defaults_true_for_non_bool(self):
        result = get_defaults({"defaults": {"fetch_titles": "yes"}})
        assert result["fetch_titles"] is True

    def test_strict_windows_true(self):
        result = get_defaults({"defaults": {"strict_windows": True}})
        assert result["strict_windows"] is True

    def test_strict_windows_defaults_false_for_non_bool(self):
        result = get_defaults({"defaults": {"strict_windows": "nope"}})
        assert result["strict_windows"] is False

    def test_exclude_patterns_list(self):
        result = get_defaults({"defaults": {"exclude_patterns": ["*sample*", "*.txt"]}})
        assert result["exclude_patterns"] == ["*sample*", "*.txt"]

    def test_exclude_patterns_defaults_empty_for_non_list(self):
        result = get_defaults({"defaults": {"exclude_patterns": "*.txt"}})
        assert result["exclude_patterns"] == []

    def test_space_replacement_underscore(self):
        result = get_defaults({"defaults": {"space_replacement": "underscore"}})
        assert result["space_replacement"] == "underscore"

    def test_space_replacement_defaults_empty_for_non_string(self):
        result = get_defaults({"defaults": {"space_replacement": 123}})
        assert result["space_replacement"] == ""


# --- get_provider_tvmaze ---


class TestGetProviderTvmaze:
    def test_returns_defaults_when_no_provider_section(self):
        result = get_provider_tvmaze({})
        assert result["prefetch_seasons"] is False

    def test_returns_defaults_when_no_tvmaze_section(self):
        result = get_provider_tvmaze({"provider": {}})
        assert result["prefetch_seasons"] is False

    def test_returns_defaults_when_prefetch_not_bool(self):
        result = get_provider_tvmaze({"provider": {"tvmaze": {"prefetch_seasons": "yes"}}})
        assert result["prefetch_seasons"] is False

    def test_prefetch_seasons_true(self):
        result = get_provider_tvmaze({"provider": {"tvmaze": {"prefetch_seasons": True}}})
        assert result["prefetch_seasons"] is True

    def test_prefetch_seasons_false(self):
        result = get_provider_tvmaze({"provider": {"tvmaze": {"prefetch_seasons": False}}})
        assert result["prefetch_seasons"] is False
