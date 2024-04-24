"""SniTun reference implementation."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from itertools import cycle
import logging
from multiprocessing import cpu_count
import os
import select
import signal
import socket
from threading import Thread
from typing import Awaitable, Iterable

import async_timeout

from ..exceptions import ParseSNIIncompleteError
from ..utils.server import MAX_BUFFER_SIZE, MAX_READ_SIZE
from .listener_peer import PeerListener
from .listener_sni import SNIProxy
from .peer_manager import PeerManager
from .sni import ParseSNIError, parse_tls_sni
from .worker import ServerWorker

_LOGGER = logging.getLogger(__name__)

WORKER_STALE_MAX = 30


class SniTunServer:
    """SniTunServer helper class for Dual port Asyncio."""

    def __init__(
        self,
        fernet_keys: list[str],
        sni_port: int | None = None,
        sni_host: str | None = None,
        peer_port: int | None = None,
        peer_host: str | None = None,
        throttling: int | None = None,
    ) -> None:
        """Initialize SniTun Server."""
        self._peers: PeerManager = PeerManager(fernet_keys, throttling=throttling)
        self._list_sni: SNIProxy = SNIProxy(self._peers, host=sni_host, port=sni_port)
        self._list_peer: PeerListener = PeerListener(
            self._peers,
            host=peer_host,
            port=peer_port,
        )

    @property
    def peers(self) -> PeerManager:
        """Return peer manager."""
        return self._peers

    def start(self) -> Awaitable[None]:
        """Run server.

        Return coroutine.
        """
        return asyncio.wait(
            [
                asyncio.create_task(self._list_peer.start()),
                asyncio.create_task(self._list_sni.start()),
            ],
        )

    def stop(self) -> Awaitable[None]:
        """Stop server.

        Return coroutine.
        """
        return asyncio.wait(
            [
                asyncio.create_task(self._list_peer.stop()),
                asyncio.create_task(self._list_sni.stop()),
            ],
        )


class SniTunServerSingle:
    """SniTunServer helper class for Single port Asnycio."""

    def __init__(
        self,
        fernet_keys: list[str],
        host: str | None = None,
        port: int | None = None,
        throttling: int | None = None,
    ) -> None:
        """Initialize SniTun Server."""
        self._loop: asyncio.BaseEventLoop = asyncio.get_event_loop()
        self._server: asyncio.AbstractServer | None = None
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
            self._handler,
            host=self._host,
            port=self._port,
        )

    async def stop(self) -> None:
        """Stop server."""
        self._server.close()
        await self._server.wait_closed()

    async def _handler(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
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
                self._list_sni.handle_connection(reader, writer, data=data),
            )
        elif data.startswith(b"gA"):
            self._loop.create_task(
                self._list_peer.handle_connection(reader, writer, data=data),
            )
        else:
            _LOGGER.warning("No valid ClientHello found: %s", data)
            writer.close()
            return


class SniTunServerWorker(Thread):
    """SniTunServer helper class for Worker."""

    def __init__(
        self,
        fernet_keys: list[str],
        host: str | None = None,
        port: int | None = None,
        worker_size: int | None = None,
        throttling: int | None = None,
    ) -> None:
        """Initialize SniTun Server."""
        super().__init__()

        self._host: str = host or "0.0.0.0"
        self._port: int = port or 443
        self._fernet_keys: list[str] = fernet_keys
        self._throttling: int | None = throttling
        self._worker_size: int = worker_size or (cpu_count() * 2)
        self._workers: list[ServerWorker] = []
        self._running: bool = False

        # TCP server
        self._server: socket.socket | None = None
        self._poller: select.epoll | None = None

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
        connections: dict[int, socket.socket] = {}
        worker_lb = cycle(self._workers)
        stale: dict[int, int] = {}
        partial: dict[int, bytes] = {}

        def _connection_cleanup(
            fileno: int,
            shutdown: bool = True,
            close_socket: bool = True,
        ) -> None:
            """Gracefull cleanup a connection."""
            partial.pop(fileno, None)
            stale.pop(fileno, None)
            self._poller.unregister(fileno)

            if (con := connections.pop(fileno, None)) and close_socket:
                self._close_socket(con, shutdown=shutdown)

        while self._running:
            events = self._poller.poll(1)
            for fileno, event in events:
                # New Connection
                if fileno == fd_server:
                    con, _ = self._server.accept()
                    con.setblocking(False)

                    self._poller.register(
                        con.fileno(),
                        select.EPOLLIN | select.EPOLLHUP | select.EPOLLERR,
                    )
                    connections[con.fileno()] = con
                    stale[con.fileno()] = 0
                    partial.pop(con.fileno(), None)

                # Read hello & forward to worker
                elif event & select.EPOLLIN:
                    stale[fileno] = 0  # Reset stale counter
                    if data := self._process(con, worker_lb, partial.get(fileno, b"")):
                        partial[fileno] = data
                        continue

                    _connection_cleanup(fileno, close_socket=False)

                # Close
                else:
                    _connection_cleanup(fileno, shutdown=False)

            # cleanup stale connection
            for fileno in tuple(stale):
                if fileno not in connections:
                    stale.pop(fileno)
                elif stale[fileno] >= WORKER_STALE_MAX:
                    _connection_cleanup(fileno, shutdown=True)
                else:
                    stale[fileno] += 1

            # Check if worker are running
            for worker in self._workers:
                if worker.is_alive():
                    continue
                _LOGGER.critical("Worker '%s' crashed!", worker.name)
                os.kill(os.getpid(), signal.SIGINT)

    def _process(
        self,
        con: socket.socket,
        workers_lb: Iterable[ServerWorker],
        data: bytes,
    ) -> None | bytes:
        """Process connection & helo."""
        try:
            data += con.recv(MAX_READ_SIZE)
        except OSError as err:
            _LOGGER.warning("Receive fails: %s", err)
            self._close_socket(con, shutdown=False)
            return None

        # No data received
        if not data:
            self._close_socket(con)
            return None

        if len(data) >= MAX_BUFFER_SIZE:
            _LOGGER.warning("Connection %d exceed buffer size", con.fileno())
            return None

        # Peer connection
        if data.startswith(b"gA"):
            next(workers_lb).handover_connection(con, data)
            _LOGGER.debug("Handover new peer connection: %s", data)
            return None

        # TLS/SSL connection
        if data[0] != 0x16:
            _LOGGER.warning("No valid ClientHello found: %s", data)
            self._close_socket(con)
            return None

        try:
            hostname = parse_tls_sni(data)
        except ParseSNIIncompleteError:
            return data
        except ParseSNIError:
            _LOGGER.warning("Receive invalid ClientHello on public Interface")
            return None
        for worker in self._workers:
            if not worker.is_responsible_peer(hostname):
                continue
            worker.handover_connection(con, data, sni=hostname)

            _LOGGER.info("Handover %s to %s", hostname, worker.name)
            return None
        _LOGGER.debug("No responsible worker for %s", hostname)

        self._close_socket(con)
        return None

    @staticmethod
    def _close_socket(con: socket.socket, shutdown: bool = True) -> None:
        """Gracefull shutdown a socket or free the handle."""
        with suppress(OSError):
            if shutdown:
                con.shutdown(socket.SHUT_RDWR)
            con.close()
