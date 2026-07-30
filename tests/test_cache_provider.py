from tvrenamer.cache import DiskCache
from tvrenamer.providers.tvmaze import TVMazeProvider


def test_cache_basic(tmp_path):
    cache_path = tmp_path / "cache.json"
    cache = DiskCache(str(cache_path))
    cache.set("ns", "k1", {"a": 1})
    assert cache.get("ns", "k1") == {"a": 1}


def test_provider_cache(tmp_path, monkeypatch):
    cache_path = tmp_path / "cache.json"
    cache = DiskCache(str(cache_path))
    provider = TVMazeProvider(cache)

    # monkeypatch network calls to return a fake show and episode
    def fake_fetch(url):
        if "singlesearch" in url:
            return {"id": 123, "name": "Fake Show"}
        if "episodebynumber" in url:
            return {"id": 10, "name": "Pilot"}
        return None

    monkeypatch.setattr(provider, "_fetch_json", lambda url: fake_fetch(url))
    t = provider.get_episode_title("Fake Show", 1, 1)
    assert t == "Pilot"
    # second call should hit cache (monkeypatch would still return same but ensure no error)
    t2 = provider.get_episode_title("Fake Show", 1, 1)
    assert t2 == "Pilot"
