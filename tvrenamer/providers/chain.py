"""Provider chain with offline mode support.

The chain queries providers in order and returns the first non-empty result.
When the circuit breaker fires (5 consecutive failures), the chain enters
offline mode for the remainder of the run — serving only cached results.
"""

import logging
import urllib.parse
from typing import List, Optional
from .base import MetadataProvider
from ..cache import DiskCache

logger = logging.getLogger(__name__)


class ProviderChain(MetadataProvider):
    def __init__(
        self,
        providers: List[MetadataProvider],
        cache: Optional[DiskCache] = None,
    ):
        self.providers = providers
        self.cache = cache
        self._offline = False
        self._consecutive_failures = 0
        self._failure_threshold = 5

    def enter_offline_mode(self):
        """Switch to offline mode — no more network calls for this run."""
        self._offline = True
        logger.warning(
            "Offline mode activated — serving cached results only"
        )

    @property
    def is_offline(self) -> bool:
        return self._offline

    def _record_failure(self):
        """Track consecutive failures and trigger offline mode at threshold."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold:
            self.enter_offline_mode()

    def _record_success(self):
        """Reset the failure counter on success."""
        self._consecutive_failures = 0

    def _cache_only_lookup(
        self, show_name: str, season: int, episode: int
    ) -> Optional[str]:
        """Attempt to find a cached result from any provider."""
        if self.cache is None:
            return None
        # Try common cache key patterns used by providers
        key = urllib.parse.quote_plus(show_name.lower())
        # First find the show to get show_id
        show_data = self.cache.get("tvmaze", f"show:{key}")
        if show_data and isinstance(show_data, dict):
            show_id = show_data.get("id")
            if show_id:
                ep_key = f"{show_id}:{season}:{episode}"
                ep_data = self.cache.get("tvmaze", f"episode:{ep_key}")
                if ep_data and isinstance(ep_data, dict):
                    return ep_data.get("name")
        # Try wikidata/wikipedia cache keys
        wikidata_key = f"{show_name.lower()}:{season}:{episode}"
        wd_data = self.cache.get("wikidata", wikidata_key)
        if wd_data and isinstance(wd_data, dict):
            return wd_data.get("title")
        wp_data = self.cache.get("wikipedia", wikidata_key)
        if wp_data and isinstance(wp_data, dict):
            return wp_data.get("title")
        return None

    def get_episode_title(
        self, show_name: str, season: int, episode: int, year: Optional[int] = None
    ) -> Optional[str]:
        """Get episode title from providers in order, or cache-only if offline."""
        if self._offline:
            return self._cache_only_lookup(show_name, season, episode)

        for p in self.providers:
            try:
                title = p.get_episode_title(show_name, season, episode, year=year)
                # Normal return (even None) means network is working — reset failures
                self._record_success()
                if title:
                    return title
            except Exception:
                self._record_failure()
                if self._offline:
                    # Just entered offline mode — serve from cache
                    return self._cache_only_lookup(show_name, season, episode)
                continue
        # All providers returned None (not an error, just no data)
        return None

    def search_show(self, name: str, year: Optional[int] = None):
        """Search for show across providers in order."""
        if self._offline:
            # In offline mode, try cache directly
            if self.cache:
                key = urllib.parse.quote_plus(name.lower())
                return self.cache.get("tvmaze", f"show:{key}")
            return None

        for p in self.providers:
            try:
                res = p.search_show(name, year=year)
                # Normal return means network is working — reset failures
                self._record_success()
                if res:
                    return res
            except Exception:
                self._record_failure()
                if self._offline:
                    if self.cache:
                        key = urllib.parse.quote_plus(name.lower())
                        return self.cache.get("tvmaze", f"show:{key}")
                    return None
                continue
        return None
