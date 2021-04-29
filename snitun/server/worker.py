"""SniTun worker for traffics."""
import asyncio
from multiprocessing import Process, Manager, Queue
from threading import Thread, Event
from typing import Dict, Optional, List, Tuple
from socket import socket

from .listener_peer import PeerListener
from .listener_sni import SNIProxy
from .peer_manager import PeerManager, PeerManagerEvent
from .peer import Peer


class ServerWorker(Process):
    """Worker for multiplexer."""

    def __init__(
        self,
        fernet_keys: List[str],
        throttling: Optional[int] = None,
    ) -> None:
        """Initialize worker & communication."""
        super().__init__()

        self._fernet_keys: List[str] = fernet_keys
        self._throttling: Optional[int] = throttling

        # Used on the child
        self._peers: Optional[PeerManager] = None
        self._list_sni: Optional[SNIProxy] = None
        self._list_peer: Optional[PeerListener] = None
        self._loop: Optional[asyncio.BaseEventLoop] = None

        # Communication between Parent/Child
        self._manager: Manager = Manager()
        self._new: Queue = self._manager.Queue()
        self._sync: Dict[str, None] = self._manager.dict()
        self._closing: Event = self._manager.Event()

    async def _async_init(self) -> None:
        """Initialize child process data."""
        self._peers = PeerManager(
            self._fernet_keys,
            throttling=self._throttling,
            event_callback=self._event_stream,
        )
        self._list_sni = SNIProxy(self._peers)
        self._list_peer = PeerListener(self._peers)

    def _event_stream(self, peer: Peer, event: PeerManagerEvent) -> None:
        """Event stream peer connection data."""
        if event == PeerManagerEvent.CONNECTED:
            self._sync[peer.hostname] = None
        else:
            self._sync.pop(peer.hostname, None)

    def shutdown(self) -> None:
        """Shutdown child process.

        This function blocking, don't call it inside loop!
        """
        self._closing.set()
        self._new.put(None)

        self.join(10)
        self.close()

    def handover_connection(
        self, con: socket, data: bytes, sni: Optional[str] = None
    ) -> None:
        """Move new connection to worker.

        Async friendly.
        """
        self._new.put_nowait((con, data, sni))

    def run(self) -> None:
        """Running worker process."""
        self._loop = asyncio.get_event_loop()

        # Start eventloop
        running_loop = Thread(target=self._loop.run_forever)
        running_loop.start()

        # Init backend
        asyncio.run_coroutine_threadsafe(self._async_init(), loop=self._loop).result()

        while not self._closing.is_set():
            new: Tuple[socket, bytes, Optional[str]] = self._new.get()
            if new is None:
                continue

            asyncio.run_coroutine_threadsafe(
                self._async_new_connection(*new), loop=self._loop
            )

        # Shutdown worker
        self._loop.stop()
        running_loop.join(10)

    async def _async_new_connection(
        self, con: socket, data: bytes, sni: Optional[str]
    ) -> None:
        """Handle incoming connection."""
        con.setblocking(False)
        reader, writer = await asyncio.open_connection(sock=con)

        # Select the correct handler for process connection
        if sni:
            self._loop.create_task(
                self._list_sni.handle_connection(reader, writer, data=data, sni=sni)
            )
        else:
            self._loop.create_task(
                self._list_peer.handle_connection(reader, writer, data=data)
            )
