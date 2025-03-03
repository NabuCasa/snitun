import importlib
import os

from snitun.multiplexer import const


def test_override_constants_from_env():
    """Test overriding constants from environment variables."""
    os.environ.pop("MULTIPLEXER_INCOMING_QUEUE_MAX_BYTES_CHANNEL", None)
    os.environ.pop("MULTIPLEXER_INCOMING_QUEUE_LOW_WATERMARK", None)
    os.environ.pop("MULTIPLEXER_INCOMING_QUEUE_HIGH_WATERMARK", None)
    os.environ.pop("MULTIPLEXER_OUTGOING_QUEUE_MAX_BYTES_CHANNEL", None)
    os.environ.pop("MULTIPLEXER_OUTGOING_QUEUE_LOW_WATERMARK", None)
    os.environ.pop("MULTIPLEXER_OUTGOING_QUEUE_HIGH_WATERMARK", None)
    os.environ.pop("MULTIPLEXER_PEER_TCP_TIMEOUT", None)
    importlib.reload(const)
    assert (
        const.INCOMING_QUEUE_MAX_BYTES_CHANNEL
        == const.DEFAULT_INCOMING_QUEUE_MAX_BYTES_CHANNEL
    )
    assert (
        const.INCOMING_QUEUE_LOW_WATERMARK == const.DEFAULT_INCOMING_QUEUE_LOW_WATERMARK
    )
    assert (
        const.INCOMING_QUEUE_HIGH_WATERMARK
        == const.DEFAULT_INCOMING_QUEUE_HIGH_WATERMARK
    )
    assert (
        const.OUTGOING_QUEUE_MAX_BYTES_CHANNEL
        == const.DEFAULT_OUTGOING_QUEUE_MAX_BYTES_CHANNEL
    )
    assert (
        const.OUTGOING_QUEUE_LOW_WATERMARK == const.DEFAULT_OUTGOING_QUEUE_LOW_WATERMARK
    )
    assert (
        const.OUTGOING_QUEUE_HIGH_WATERMARK
        == const.DEFAULT_OUTGOING_QUEUE_HIGH_WATERMARK
    )
    assert const.PEER_TCP_TIMEOUT == const.DEFAULT_PEER_TCP_TIMEOUT
    os.environ["MULTIPLEXER_INCOMING_QUEUE_MAX_BYTES_CHANNEL"] = "1"
    os.environ["MULTIPLEXER_INCOMING_QUEUE_LOW_WATERMARK"] = "2"
    os.environ["MULTIPLEXER_INCOMING_QUEUE_HIGH_WATERMARK"] = "3"
    os.environ["MULTIPLEXER_OUTGOING_QUEUE_MAX_BYTES_CHANNEL"] = "4"
    os.environ["MULTIPLEXER_OUTGOING_QUEUE_LOW_WATERMARK"] = "5"
    os.environ["MULTIPLEXER_OUTGOING_QUEUE_HIGH_WATERMARK"] = "6"
    os.environ["MULTIPLEXER_PEER_TCP_TIMEOUT"] = "7"
    importlib.reload(const)
    assert const.INCOMING_QUEUE_MAX_BYTES_CHANNEL == 1
    assert const.INCOMING_QUEUE_LOW_WATERMARK == 2
    assert const.INCOMING_QUEUE_HIGH_WATERMARK == 3
    assert const.OUTGOING_QUEUE_MAX_BYTES_CHANNEL == 4
    assert const.OUTGOING_QUEUE_LOW_WATERMARK == 5
    assert const.OUTGOING_QUEUE_HIGH_WATERMARK == 6
    assert const.PEER_TCP_TIMEOUT == 7
    del os.environ["MULTIPLEXER_INCOMING_QUEUE_MAX_BYTES_CHANNEL"]
    del os.environ["MULTIPLEXER_INCOMING_QUEUE_LOW_WATERMARK"]
    del os.environ["MULTIPLEXER_INCOMING_QUEUE_HIGH_WATERMARK"]
    del os.environ["MULTIPLEXER_OUTGOING_QUEUE_MAX_BYTES_CHANNEL"]
    del os.environ["MULTIPLEXER_OUTGOING_QUEUE_LOW_WATERMARK"]
    del os.environ["MULTIPLEXER_OUTGOING_QUEUE_HIGH_WATERMARK"]
    del os.environ["MULTIPLEXER_PEER_TCP_TIMEOUT"]
    importlib.reload(const)
    assert (
        const.INCOMING_QUEUE_MAX_BYTES_CHANNEL
        == const.DEFAULT_INCOMING_QUEUE_MAX_BYTES_CHANNEL
    )
    assert (
        const.INCOMING_QUEUE_LOW_WATERMARK == const.DEFAULT_INCOMING_QUEUE_LOW_WATERMARK
    )
    assert (
        const.INCOMING_QUEUE_HIGH_WATERMARK
        == const.DEFAULT_INCOMING_QUEUE_HIGH_WATERMARK
    )
    assert (
        const.OUTGOING_QUEUE_MAX_BYTES_CHANNEL
        == const.DEFAULT_OUTGOING_QUEUE_MAX_BYTES_CHANNEL
    )
    assert (
        const.OUTGOING_QUEUE_LOW_WATERMARK == const.DEFAULT_OUTGOING_QUEUE_LOW_WATERMARK
    )
    assert (
        const.OUTGOING_QUEUE_HIGH_WATERMARK
        == const.DEFAULT_OUTGOING_QUEUE_HIGH_WATERMARK
    )
    assert const.PEER_TCP_TIMEOUT == const.DEFAULT_PEER_TCP_TIMEOUT
