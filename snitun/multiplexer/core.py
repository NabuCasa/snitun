"""Multiplexer for SniTun."""
import asyncio
import logging

from ..exceptions import MultiplexerTransportClose

_LOGGER = logging.getLogger(__name__)


class Multiplexer:
    """Multiplexer Socket wrapper."""

    def __init__(self, reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter):
        """Initialize Multiplexer."""
        self._reader = reader
        self._writer = writer
        self._loop = asyncio.get_event_loop()
        self._queue = asyncio.Queue(10)
        self._processing_task = self._loop.create_task(self._runner())
        self._channels = {}  # type: Dict[MultiplexerMessage]

    async def shutdown(self):
        """Shutdonw connection."""
        if self._processing_task.done():
            return

        _LOGGER.debug("Cancel connection")
        self._processing_task.cancel()

    async def _runner(self):
        """Runner task of processing stream."""
        transport = self._writer.transport
        from_peer = None
        to_peer = None

        try:

            # Process stream
            while not transport.is_closing():
                if not from_peer:
                    from_peer = self._loop.create_task(self._reader.read(21))

                if not to_peer:
                    from_peer = self._loop.create_task(self._queue.get())

                # Wait until data need to be processed
                await asyncio.wait([from_peer, to_peer],
                                   return_when=asyncio.FIRST_COMPLETED)

                # To peer
                if to_peer.done():
                    await self._write_message(to_peer.result())
                    to_peer = None

                # From peer
                if from_peer.done():
                    msg_header = from_peer.result()
                    from_peer = None

                    if not msg_header:
                        raise MultiplexerTransportClose()
                    await self._read_message(msg_header)

        except asyncio.CancelledError:
            _LOGGER.debug("Receive canceling")
            self._writer.write_eof()
            await self._writer.drain()

        except MultiplexerTransportClose:
            _LOGGER.debug("Transport was closed")

        finally:
            if to_peer and not to_peer.done():
                to_peer.cancel()
            if from_peer and not from_peer.done():
                from_peer.cancel()
            if not transport.is_closing():
                self._writer.close()

        _LOGGER.debug("Multiplexer connection is closed")
