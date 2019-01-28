"""Multiplexer for SniTun."""
import asyncio


class Multiplexer:
    """Multiplexer Socket wrapper."""

    def __init__(self, reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter):
        """Initialize Multiplexer."""
        self._reader: asyncio.StreamReader = reader
        self._writer: asyncio.StreamWriter = writer
