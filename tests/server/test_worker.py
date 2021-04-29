"""Tests for the server worker."""

from snitun.server.worker import ServerWorker

from .const_fernet import FERNET_TOKENS


def test_worker_up_down(loop):
    """Test if worker start and stop."""
    worker = ServerWorker(FERNET_TOKENS)

    worker.start()
    assert worker.is_alive()
    worker.shutdown()

    assert worker.exitcode == 0
    assert not worker.is_alive()
