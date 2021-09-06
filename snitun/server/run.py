"""SniTun reference implementation."""
import asyncio
from contextlib import suppress
from itertools import cycle
import logging
from multiprocessing import cpu_count
import os
import select
import signal
import socket
from typing import Awaitable, Iterable, List, Optional, Dict
from threading import Thread

import async_timeout

from .listener_peer import PeerListener
from .listener_sni import SNIProxy
from .peer_manager import PeerManager
from .worker import ServerWorker
from .sni import ParseSNIError, parse_tls_sni

_LOGGER = logging.getLogger(__name__)

WORKER_STALE_MAX = 10


class SniTunServer:
    """SniTunServer helper class for Dual port Asyncio."""

    def __init__(
        self,
        fernet_keys: List[str],
        sni_port: Optional[int] = None,
        sni_host: Optional[str] = None,
        peer_port: Optional[int] = None,
        peer_host: Optional[str] = None,
        throttling: Optional[int] = None,
    ):
        """Initialize SniTun Server."""
        self._peers: PeerManager = PeerManager(fernet_keys, throttling=throttling)
        self._list_sni: SNIProxy = SNIProxy(self._peers, host=sni_host, port=sni_port)
        self._list_peer: PeerListener = PeerListener(
            self._peers, host=peer_host, port=peer_port
        )

    @property
    def peers(self) -> PeerManager:
        """Return peer manager."""
        return self._peers

    def start(self) -> Awaitable[None]:
        """Run server.

        Return coroutine.
        """
        return asyncio.wait([self._list_peer.start(), self._list_sni.start()])

    def stop(self) -> Awaitable[None]:
        """Stop server.

        Return coroutine.
        """
        return asyncio.wait([self._list_peer.stop(), self._list_sni.stop()])


class SniTunServerSingle:
    """SniTunServer helper class for Single port Asnycio."""

    def __init__(
        self,
        fernet_keys: List[str],
        host: Optional[str] = None,
        port: Optional[int] = None,
        throttling: Optional[int] = None,
    ):
        """Initialize SniTun Server."""
        self._loop: asyncio.BaseEventLoop = asyncio.get_event_loop()
        self._server: Optional[asyncio.AbstractServer] = None
        self._peers: PeerManager = PeerManager(fernet_keys, throttling=throttling)
        self._list_sni: SNIProxy = SNIProxy(self._peers)
        self._list_peer: PeerListener = PeerListener(self._peers)
        self._host: str = host or "0.0.0.0"
        self._port: int = port or 443

    @property
    def peers(self) -> PeerManager:
        """Return peer manager."""
        return self._peers

    async def start(self) -> None:
        """Run server."""
        self._server = await asyncio.start_server(
            self._handler, host=self._host, port=self._port
        )

    async def stop(self) -> None:
        """Stop server."""
        self._server.close()
        await self._server.wait_closed()

    async def _handler(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle incoming connection."""
        try:
            async with async_timeout.timeout(10):
                data = await reader.read(2048)
        except asyncio.TimeoutError:
            _LOGGER.warning("Abort connection initializing")
            writer.close()
            return
        except OSError:
            return

        # Connection closed / healty check
        if not data:
            writer.close()
            return

        # Select the correct handler for process data
        if data[0] == 0x16:
            self._loop.create_task(
                self._list_sni.handle_connection(reader, writer, data=data)
            )
        elif data.startswith(b"gA"):
            self._loop.create_task(
                self._list_peer.handle_connection(reader, writer, data=data)
            )
        else:
            _LOGGER.warning("No valid ClientHello found: %s", data)
            writer.close()
            return


class SniTunServerWorker(Thread):
    """SniTunServer helper class for Worker."""

    def __init__(
        self,
        fernet_keys: List[str],
        host: Optional[str] = None,
        port: Optional[int] = None,
        worker_size: Optional[int] = None,
        throttling: Optional[int] = None,
    ):
        """Initialize SniTun Server."""
        super().__init__()

        self._host: str = host or "0.0.0.0"
        self._port: int = port or 443
        self._fernet_keys: List[str] = fernet_keys
        self._throttling: Optional[int] = throttling
        self._worker_size: int = worker_size or (cpu_count() * 2)
        self._workers: List[ServerWorker] = []
        self._running: bool = False

        # TCP server
        self._server: Optional[socket.socket] = None
        self._poller: Optional[select.epoll] = None

    @property
    def peer_counter(self) -> int:
        """Return number of active peer connections."""
        return sum(worker.peer_size for worker in self._workers)

    def start(self) -> None:
        """Run server."""
        # Init first all worker, we don't want the epoll on the childs
        _LOGGER.info("Run SniTun with %d worker", self._worker_size)
        for _ in range(self._worker_size):
            worker = ServerWorker(self._fernet_keys, throttling=self._throttling)
            worker.start()
            self._workers.append(worker)

        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self._host, self._port))
        self._server.setblocking(False)
        self._server.listen(80 * 1000)

        self._running = True
        self._poller = select.epoll()
        self._poller.register(self._server.fileno(), select.EPOLLIN)

        super().start()

    def stop(self) -> None:
        """Stop server."""
        self._running = False
        self.join()

        # Shutdown all workers
        for worker in self._workers:
            worker.shutdown()
            worker.close()

        self._workers.clear()
        self._server.close()
        self._poller.close()

    def run(self) -> None:
        """Handle incoming connection."""
        fd_server = self._server.fileno()
        connections: Dict[int, socket.socket] = {}
        worker_lb = cycle(self._workers)
        stale: Dict[int, int] = {}

        while self._running:
            events = self._poller.poll(1)
            for fileno, event in events:
                # New Connection
                if fileno == fd_server:
                    con, _ = self._server.accept()
                    con.setblocking(False)

                    self._poller.register(
                        con.fileno(), select.EPOLLIN | select.EPOLLHUP | select.EPOLLERR
                    )
                    connections[con.fileno()] = con
                    stale[con.fileno()] = 0

                # Read hello & forward to worker
                elif event & select.EPOLLIN:
                    self._poller.unregister(fileno)
                    con = connections.pop(fileno)
                    self._process(con, worker_lb)

                # Close
                else:
                    self._poller.unregister(fileno)
                    con = connections.pop(fileno)
                    self._close_socket(con, shutdown=False)

            # cleanup stale connection
            for fileno in tuple(stale):
                if fileno not in connections:
                    stale.pop(fileno)
                elif stale[fileno] >= WORKER_STALE_MAX:
                    self._poller.unregister(fileno)
                    con = connections.pop(fileno)
                    self._close_socket(con)
                else:
                    stale[fileno] += 1

            # Check if worker are running
            for worker in self._workers:
                if worker.is_alive():
                    continue
                _LOGGER.critical("Worker '%s' crashed!", worker.name)
                os.kill(os.getpid(), signal.SIGINT)

    def _process(self, con: socket.socket, workers_lb: Iterable[ServerWorker]) -> None:
        """Process connection & helo."""
        data = b""
        try:
            data = con.recv(2048)
        except OSError as err:
            _LOGGER.warning("Receive fails: %s", err)
            self._close_socket(con, shutdown=False)
            return

        # No data received
        if not data:
            self._close_socket(con)
            return

        # Peer connection
        if data.startswith(b"gA"):
            next(workers_lb).handover_connection(con, data)
            _LOGGER.debug("Handover new peer connection: %s", data)
            return

        # TLS/SSL connection
        if data[0] != 0x16:
            _LOGGER.warning("No valid ClientHello found: %s", data)
            self._close_socket(con)
            return

        try:
            hostname = parse_tls_sni(data)
        except ParseSNIError:
            _LOGGER.warning("Receive invalid ClientHello on public Interface")
        else:
            for worker in self._workers:
                if not worker.is_responsible_peer(hostname):
                    continue
                worker.handover_connection(con, data, sni=hostname)

                _LOGGER.info("Handover %s to %s", hostname, worker.name)
                return
            _LOGGER.debug("No responsible worker for %s", hostname)

        self._close_socket(con)

    @staticmethod
    def _close_socket(con: socket.socket, shutdown: bool = True) -> None:
        """Gracefull shutdown a socket or free the handle."""
        with suppress(OSError):
            if shutdown:
                con.shutdown(socket.SHUT_RDWR)
            con.close()
