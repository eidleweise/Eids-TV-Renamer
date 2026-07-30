import json
import urllib.parse
import urllib.request
from typing import Optional
from ..cache import DiskCache
from ..ratelimit import TokenBucket, CircuitBreaker
from .network import BaseNetworkProvider

SEARCH = (
    "https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&"
    "language=en&limit=1&search={q}"
)
ENTITY = "https://www.wikidata.org/wiki/Special:EntityData/{id}.json"


class WikidataProvider(BaseNetworkProvider):
    def __init__(
        self,
        cache: DiskCache,
        limiter: TokenBucket | None = None,
        circuit: CircuitBreaker | None = None,
        headers: dict | None = None,
    ):
        super().__init__(
            cache=cache,
            name="wikidata",
            limiter=limiter or TokenBucket(rate=1, capacity=2),
            circuit=circuit,
            headers=headers,
        )

    def _sparql_query(self, show_name: str, season: int, episode: int) -> Optional[str]:
        """Query query.wikidata.org SPARQL endpoint for an episode label matching the show/season/episode.

        This is a best-effort fallback that looks for labels containing the show name and
        episode/season indicators. Returns the first match label if found.
        """
        # Escape SPARQL string literal special characters to prevent injection
        def _sparql_escape(s: str) -> str:
            """Escape a string for safe inclusion in a SPARQL string literal."""
            return (
                s.replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("'", "\\'")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t")
            )

        qshow = _sparql_escape(show_name)
        # try a few candidate patterns to match common labels
        candidates = [
            f"{qshow} episode {episode}",
            f"{qshow} S{season:02d}E{episode:02d}",
            f"{qshow} season {season} episode {episode}",
        ]
        for cand in candidates:
            sparql = (
                'SELECT ?item ?itemLabel WHERE { '
                f'?item rdfs:label ?itemLabel . FILTER(LANG(?itemLabel) = "en") '
                f'FILTER(CONTAINS(LCASE(?itemLabel), "{cand.lower()}")) '
                '} LIMIT 1'
            )
            try:
                url = "https://query.wikidata.org/sparql?query=" + urllib.parse.quote(sparql)
                headers = self.headers.copy()
                # prefer JSON results
                headers.setdefault("Accept", "application/sparql-results+json")
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    status = getattr(resp, "status", None) or resp.getcode()
                    if status != 200:
                        continue
                    data = json.loads(resp.read().decode("utf-8"))
                    bindings = data.get("results", {}).get("bindings", [])
                    if bindings:
                        label = bindings[0].get("itemLabel", {}).get("value")
                        if label:
                            self.logger.info(
                                "Provider fetch success (sparql)",
                                extra={"provider": self.name, "query": cand},
                            )
                            return label
            except Exception as ex:
                # log and continue to next candidate
                self.logger.warning(
                    "Provider fetch error",
                    extra={"provider": self.name, "query": cand, "error": str(ex)},
                )
                continue
        return None

    def search_show(self, name: str, year: Optional[int] = None) -> Optional[dict]:
        key = urllib.parse.quote_plus(name.lower())
        cached = self.cache.get(
            "wikidata", f"show:{key}", extra={"provider": self.name}
        )
        if cached:
            return cached
        url = SEARCH.format(q=urllib.parse.quote(name))
        data = self._fetch_json(url)
        if not data:
            return None
        try:
            results = data.get("search") or []
            if results:
                entry = results[0]
                out = {"id": entry.get("id"), "label": entry.get("label")}
                self.cache.set(
                    "wikidata",
                    f"show:{key}",
                    out,
                    extra={"provider": self.name},
                )
                return out
        except Exception:
            return None
        return None

    def get_episode_title(
        self, show_name: str, season: int, episode: int, year: Optional[int] = None
    ) -> Optional[str]:
        # Wikidata approach is complex; as a fallback, try to find an episode item via search by label
        # We'll attempt a simple approach: search for "Show episode X" and return label if found
        q = f"{show_name} episode {episode}"
        key = urllib.parse.quote_plus(q.lower())
        cached = self.cache.get("wikidata", f"episode:{key}")
        if cached:
            return cached
        url = SEARCH.format(q=urllib.parse.quote(q))
        data = self._fetch_json(url)
        if not data:
            # try SPARQL fallback
            sparq = self._sparql_query(show_name, season, episode)
            if sparq:
                self.cache.set(
                    "wikidata",
                    f"episode:{key}",
                    sparq,
                    extra={"provider": self.name, "method": "sparql"},
                )
                return sparq
            return None
        try:
            results = data.get("search") or []
            if results:
                title = results[0].get("label") or results[0].get("concepturi")
                self.cache.set(
                    "wikidata",
                    f"episode:{key}",
                    title,
                    extra={"provider": self.name},
                )
                return title
        except Exception:
            return None
        return None
