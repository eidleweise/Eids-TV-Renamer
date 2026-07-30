import urllib.parse
from typing import Optional
from ..cache import DiskCache
from ..ratelimit import TokenBucket, CircuitBreaker
from .network import BaseNetworkProvider

OPENSEARCH = "https://en.wikipedia.org/w/api.php?action=opensearch&limit=1&search={q}&format=json"
SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"


class WikipediaProvider(BaseNetworkProvider):
    def __init__(
        self,
        cache: DiskCache,
        limiter: TokenBucket | None = None,
        circuit: CircuitBreaker | None = None,
    ):
        super().__init__(
            cache=cache,
            name="wikipedia",
            limiter=limiter,
            circuit=circuit,
        )

    def search_show(self, name: str, year: Optional[int] = None) -> Optional[dict]:
        key = urllib.parse.quote_plus(name.lower())
        cached = self.cache.get(
            "wikipedia", f"show:{key}", extra={"provider": self.name}
        )
        if cached:
            return cached
        url = OPENSEARCH.format(q=urllib.parse.quote(name))
        data = self._fetch_json(url)
        if not data:
            return None
        # opensearch format: [query, [titles], [descriptions], [links]]
        try:
            titles = data[1]
            if titles:
                title = titles[0]
                out = {"title": title}
                self.cache.set(
                    "wikipedia", f"show:{key}", out, extra={"provider": self.name}
                )
                return out
        except Exception:
            return None
        return None

    def get_episode_title(
        self, show_name: str, season: int, episode: int, year: Optional[int] = None
    ) -> Optional[str]:
        # Heuristic attempts: "Show (season X)", "Show season X", "List of Show episodes"
        candidates = [
            f"{show_name} (season {season})",
            f"{show_name} season {season}",
            f"List of {show_name} episodes",
        ]
        for cand in candidates:
            key = urllib.parse.quote_plus(cand.lower())
            cached = self.cache.get("wikipedia", f"episode:{key}")
            if cached:
                return cached
            url = SUMMARY.format(title=urllib.parse.quote(cand.replace(" ", "_")))
            data = self._fetch_json(url)
            if not data:
                continue
            # try to parse a title from extract - tests can mock this
            extract = (
                data.get("extract") or data.get("description") or data.get("title")
            )
            if extract:
                # cache and return the extract as a fallback title
                self.cache.set(
                    "wikipedia",
                    f"episode:{key}",
                    extract,
                    extra={"provider": self.name},
                )
                return extract
        return None
