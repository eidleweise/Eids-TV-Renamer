"""Shared pytest fixtures for tvrenamer tests."""

import pytest
from hypothesis import settings as hypothesis_settings
from tests.helpers import DummyProvider

# Register hypothesis profiles for CI and local development
hypothesis_settings.register_profile("ci", max_examples=200)
hypothesis_settings.register_profile("default", max_examples=100)
hypothesis_settings.load_profile("default")


@pytest.fixture
def dummy_provider():
    """Provide a DummyProvider instance."""
    return DummyProvider()


@pytest.fixture
def dummy_providers():
    """Provide a list with a single DummyProvider."""
    return [DummyProvider()]
