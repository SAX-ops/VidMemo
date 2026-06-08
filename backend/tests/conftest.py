"""Shared test fixtures for the backend test suite."""

import pytest


@pytest.fixture(autouse=True)
def _reset_summary_singletons():
    """Reset lazy module-level singletons in routers.summary between tests.

    Without this, the first test that hits /api/summarize initializes _cache
    and _extractor with whatever env vars were set at that time; subsequent
    tests that monkeypatch SUMMARY_CACHE_PATH will silently use the stale
    singletons, causing flaky test failures.
    """
    from routers import summary
    summary._cache = None
    summary._extractor = None
    yield
    summary._cache = None
    summary._extractor = None
