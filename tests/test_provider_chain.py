from tvrenamer.providers.chain import ProviderChain


class Fake1:
    def get_episode_title(self, show, s, e, year=None):
        return None

    def search_show(self, name, year=None):
        return None


class Fake2:
    def get_episode_title(self, show, s, e, year=None):
        return "Found"

    def search_show(self, name, year=None):
        return {"id": 1}


def test_chain_fallback():
    c = ProviderChain([Fake1(), Fake2()])
    t = c.get_episode_title("X", 1, 1)
    assert t == "Found"

    s = c.search_show("X")
    assert s == {"id": 1}
