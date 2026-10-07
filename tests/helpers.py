"""Shared test helpers for tvrenamer tests.

Provides reusable mock providers and utilities to avoid duplication
across test files.
"""


class DummyProvider:
    """A mock metadata provider that returns predictable episode titles.

    Returns "Title {episode}" for any show/season/episode lookup.

    Optional constructor params (both default to behaviour identical to the
    original no-arg provider):
    - ``unidentified``: a collection of show names (compared case-insensitively)
      that ``search_show`` returns ``None`` for, so tests can simulate a show
      that cannot be identified.
    - ``record``: an optional list that ``get_episode_title`` appends its
      ``show`` argument to, so tests can observe which name reached the lookup.
    """

    def __init__(self, cache=None, unidentified=None, record=None):
        # names (lowercased) that search_show should MISS (return None)
        self._unidentified = {n.lower() for n in (unidentified or [])}
        self._record = record  # optional list; get_episode_title appends `show`

    def get_episode_title(self, show, season, episode, year=None):
        if self._record is not None:
            self._record.append(show)
        return f"Title {episode}"

    def search_show(self, name, year=None):
        if name.lower() in self._unidentified:
            return None
        return {"id": 1, "name": name}
