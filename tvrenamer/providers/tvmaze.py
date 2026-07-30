from typing import Optional
import urllib.parse
from ..cache import DiskCache
from ..ratelimit import TokenBucket, CircuitBreaker
from .network import BaseNetworkProvider

TVMAZE_SEARCH = "https://api.tvmaze.com/singlesearch/shows?q={q}"
TVMAZE_EP_BY_NUM = (
    "https://api.tvmaze.com/shows/{id}/episodebynumber?season={s}&number={e}"
)
TVMAZE_SEASONS = "https://api.tvmaze.com/shows/{id}/seasons"
TVMAZE_SEASON_EP_BY_NUM = "https://api.tvmaze.com/seasons/{season_id}/episodebynumber?number={e}"


class TVMazeProvider(BaseNetworkProvider):
    def __init__(
        self,
        cache: DiskCache,
        limiter: TokenBucket | None = None,
        circuit: CircuitBreaker | None = None,
        prefetch_seasons: bool = False,
    ):
        super().__init__(
            cache=cache,
            name="tvmaze",
            limiter=limiter,
            circuit=circuit,
            max_retries=5,
            backoff_base=0.5,
            backoff_cap=10.0,
        )
        self.prefetch_seasons = prefetch_seasons
        self._prefetched: set = set()  # track (show_id, season) already prefetched

    def search_show(self, name: str, year: Optional[int] = None) -> Optional[dict]:
        key = urllib.parse.quote_plus(name.lower())
        if year:
            key += f":{year}"
        cached = self.cache.get("tvmaze", f"show:{key}", extra={"provider": self.name})
        if cached:
            return cached
        # Include year in query for disambiguation if provided
        query = f"{name} {year}" if year else name
        url = TVMAZE_SEARCH.format(q=urllib.parse.quote(query))
        data = self._fetch_json(url)
        if data:
            self.cache.set("tvmaze", f"show:{key}", data, extra={"provider": self.name})
        return data

    def get_episode(self, show_id: int, season: int, episode: int) -> Optional[dict]:
        key = f"{show_id}:{season}:{episode}"
        cached = self.cache.get(
            "tvmaze", f"episode:{key}", extra={"provider": self.name}
        )
        if cached:
            return cached
        # Primary attempt: episode by show id + season number
        url = TVMAZE_EP_BY_NUM.format(id=show_id, s=season, e=episode)
        data = self._fetch_json(url)
        if data:
            self.cache.set(
                "tvmaze", f"episode:{key}", data, extra={"provider": self.name}
            )
            return data
        # Fallback: fetch seasons for the show and try season-specific endpoints
        try:
            seasons_url = TVMAZE_SEASONS.format(id=show_id)
            seasons = self._fetch_json(seasons_url) or []
            # find season entry with matching "number" field
            season_id = None
            for s in seasons:
                if s.get("number") == season:
                    season_id = s.get("id")
                    break
            if season_id:
                # try season-specific episodebynumber
                s_url = TVMAZE_SEASON_EP_BY_NUM.format(season_id=season_id, e=episode)
                s_data = self._fetch_json(s_url)
                if s_data:
                    self.cache.set(
                        "tvmaze", f"episode:{key}", s_data, extra={"provider": self.name}
                    )
                    return s_data
                # as a final fallback, fetch all episodes for the season and filter
                eps_url = f"https://api.tvmaze.com/seasons/{season_id}/episodes"
                eps = self._fetch_json(eps_url) or []
                for ep in eps:
                    # some APIs use 'number' for episode within season
                    if ep.get("number") == episode or ep.get("episode") == episode:
                        self.cache.set(
                            "tvmaze", f"episode:{key}", ep, extra={"provider": self.name}
                        )
                        return ep
        except Exception:
            pass
        return None

    def _prefetch_season(self, show_id: int, season: int) -> bool:
        """Prefetch all episodes for a season and populate the cache.

        Returns True if prefetch succeeded (at least partially), False otherwise.
        Acquires rate-limiter tokens before each API request.
        """
        prefetch_key = (show_id, season)
        if prefetch_key in self._prefetched:
            return True
        self._prefetched.add(prefetch_key)

        self.logger.info(
            "Prefetching season %d for show %d", season, show_id,
            extra={"provider": self.name},
        )

        # First, get seasons list to find the season_id
        seasons_url = TVMAZE_SEASONS.format(id=show_id)
        seasons_data = self._fetch_json(seasons_url)
        if not seasons_data:
            return False

        season_id = None
        for s in seasons_data:
            if s.get("number") == season:
                season_id = s.get("id")
                break

        if season_id is None:
            return False

        # Fetch all episodes for this season
        eps_url = f"https://api.tvmaze.com/seasons/{season_id}/episodes"
        episodes = self._fetch_json(eps_url)
        if not episodes or not isinstance(episodes, list):
            return False

        # Populate cache for each episode
        cached_count = 0
        for ep in episodes:
            ep_num = ep.get("number")
            if ep_num is None:
                continue
            key = f"{show_id}:{season}:{ep_num}"
            self.cache.set(
                "tvmaze", f"episode:{key}", ep, extra={"provider": self.name}
            )
            cached_count += 1

        self.logger.info(
            "Prefetched %d episodes for show %d season %d",
            cached_count, show_id, season,
            extra={"provider": self.name},
        )
        return cached_count > 0

    def get_episode_title(
        self, show_name: str, season: int, episode: int, year: Optional[int] = None
    ) -> Optional[str]:
        # search show to get id (pass year for disambiguation)
        show = self.search_show(show_name, year=year)
        if not show:
            return None
        show_id = show.get("id")
        if show_id is None:
            return None

        # Trigger season prefetch if enabled and not yet done for this show+season
        if self.prefetch_seasons:
            prefetch_key = (show_id, season)
            if prefetch_key not in self._prefetched:
                self._prefetch_season(show_id, season)
                # After prefetch, the cache should have the episode — try cache first
                key = f"{show_id}:{season}:{episode}"
                cached = self.cache.get(
                    "tvmaze", f"episode:{key}", extra={"provider": self.name}
                )
                if cached:
                    return cached.get("name")
                # Prefetch didn't include this episode — fall back to individual lookup

        ep = self.get_episode(show_id, season, episode)
        if not ep:
            return None
        return ep.get("name")
