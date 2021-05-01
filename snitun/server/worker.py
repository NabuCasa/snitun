"""SniTun worker for traffics."""
import asyncio
from multiprocessing import Process, Manager, Queue
from threading import Thread
from typing import Dict, Optional, List
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

        # Communication between Parent/Child
        self._manager: Manager = Manager()
        self._new: Queue = self._manager.Queue()
        self._sync: Dict[str, None] = self._manager.dict()

    @property
    def peer_size(self) -> int:
        """Return amount of managed peers."""
        return len(self._sync)

    def is_responsible_peer(self, sni: str) -> bool:
        """Return True if worker is responsible for this peer domain."""
        return sni in self._sync

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
        """Shutdown child process."""
        self._new.put(None)
        self.join(10)

    def handover_connection(
        self, con: socket, data: bytes, sni: Optional[str] = None
    ) -> None:
        """Move new connection to worker."""
        self._new.put_nowait((con, data, sni))

    def run(self) -> None:
        """Running worker process."""
        loop = asyncio.new_event_loop()

        # Start eventloop
        running_loop = Thread(target=loop.run_forever)
        running_loop.start()

        # Init backend
        asyncio.run_coroutine_threadsafe(self._async_init(), loop=loop).result()

        while True:
            new = self._new.get()
            if new is None:
                break

            new[0].setblocking(False)
            loop.call_soon_threadsafe(
                asyncio.create_task, self._async_new_connection(*new)
            )

        # Shutdown worker
        loop.call_soon_threadsafe(loop.stop)
        running_loop.join(10)

    async def _async_new_connection(
        self, con: socket, data: bytes, sni: Optional[str]
    ) -> None:
        """Handle incoming connection."""
        try:
            reader, writer = await asyncio.open_connection(sock=con)
        except OSError:
            con.close()
            return

        # Select the correct handler for process connection
        loop = asyncio.get_running_loop()
        if sni:
            loop.create_task(
                self._list_sni.handle_connection(reader, writer, data=data, sni=sni)
            )
        else:
            loop.create_task(
                self._list_peer.handle_connection(reader, writer, data=data)
            )
