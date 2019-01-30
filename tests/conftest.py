"""Pytest fixtures for SniTun."""
import asyncio
from unittest.mock import patch

import pytest


@pytest.fixture
def raise_timeout():
    """Raise timeout on async-timeout."""
    with patch('async_timeout.timeout', side_effect=asyncio.TimeoutError()):
        yield
