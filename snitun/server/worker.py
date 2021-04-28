"""SniTun worker for traffics."""
import asyncio
from multiprocessing import Process, Manager, Queue
from threading import Thread, Event
from typing import Dict, Optional, List, Tuple
from socket import socket

from .listener_peer import PeerListener
from .listener_sni import SNIProxy
from .peer_manager import PeerManager


class ServerWorker(Process):
    """Worker for multiplexer."""

    def __init__(
        self,
        fernet_keys: List[str],
        throttling: Optional[int] = None,
    ) -> None:
        """Initialize worker & communication."""
        super().__init__()

        self._peers = PeerManager(fernet_keys, throttling=throttling)
        self._list_sni = SNIProxy(self._peers)
        self._list_peer = PeerListener(self._peers)

        self._manager: Manager = Manager()
        self._new: Queue = self._manager.Queue()
        self._sync: Dict[str, socket] = self._manager.dict()
        self._closing: Event = self._manager.Event()

        self._loop: Optional[asyncio.BaseEventLoop] = None

    def handover_connection(
        self, con: socket, data: bytes, sni: Optional[str] = None
    ) -> None:
        """Move new connection to worker."""
        self._new.put_nowait((con, data, sni))

    def run(self) -> None:
        """Running worker process."""
        self._loop = asyncio.get_event_loop()

        # Start eventloop
        running_loop = Thread(target=self._loop.run_forever)
        running_loop.start()

        while not self._closing.is_set():
            new: Tuple[socket, bytes, Optional[str]] = self._new.get()

            asyncio.create_task(self._new_connection(*new))

    async def _new_connection(
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
