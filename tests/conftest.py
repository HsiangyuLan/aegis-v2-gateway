"""Shared pytest fixtures."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    """
    A module-scoped FastAPI TestClient that runs the full lifespan (startup +
    shutdown) once per test module.  The sampler will attempt NVML init and
    immediately degrade gracefully in CI / non-GPU environments.
    """
    with TestClient(app) as c:
        yield c
