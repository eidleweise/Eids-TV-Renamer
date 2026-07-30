from tvrenamer.providers.wikipedia import WikipediaProvider
from tvrenamer.providers.wikidata import WikidataProvider
from tvrenamer.cache import DiskCache


def test_wikipedia_provider_cached(tmp_path, monkeypatch):
    cache = DiskCache(str(tmp_path / "cache.json"))
    provider = WikipediaProvider(cache)

    # opensearch should return ['q', ['Some (season 1)'], ...]
    def fake_fetch(url):
        if "opensearch" in url:
            return ["q", ["Some (season 1)"], [], []]
        if "page/summary" in url:
            return {"title": "Some (season 1)", "extract": "Pilot"}
        return None

    monkeypatch.setattr(provider, "_fetch_json", lambda url: fake_fetch(url))
    t = provider.get_episode_title("Some", 1, 1)
    assert t == "Pilot"


def test_wikidata_provider_cached(tmp_path, monkeypatch):
    cache = DiskCache(str(tmp_path / "cache.json"))
    provider = WikidataProvider(cache)

    def fake_fetch(url):
        if "wbsearchentities" in url:
            return {"search": [{"id": "Q123", "label": "Episode 1"}]}
        return None

    monkeypatch.setattr(provider, "_fetch_json", lambda url: fake_fetch(url))
    t = provider.get_episode_title("Some Show", 1, 1)
    assert t == "Episode 1"
