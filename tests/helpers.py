"""Shared test helpers for tvrenamer tests.

Provides reusable mock providers and utilities to avoid duplication
across test files.
"""


class DummyProvider:
    """A mock metadata provider that returns predictable episode titles.

    Returns "Title {episode}" for any show/season/episode lookup.
    """

    def __init__(self, cache=None):
        pass

    def get_episode_title(self, show, season, episode, year=None):
        return f"Title {episode}"

    def search_show(self, name, year=None):
        return {"id": 1, "name": name}
