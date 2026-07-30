from typing import Optional


class MetadataProvider:
    """Base interface for metadata providers."""

    def search_show(self, name: str, year: Optional[int] = None) -> Optional[dict]:
        raise NotImplementedError()

    def get_episode_title(
        self, show_name: str, season: int, episode: int, year: Optional[int] = None
    ) -> Optional[str]:
        raise NotImplementedError()
