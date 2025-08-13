"""SniTun worker for traffics."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from multiprocessing import Manager, Process
from socket import socket
from threading import Thread
import time
from typing import TYPE_CHECKING

from ..metrics import MetricsCollector, MetricsFactory, create_noop_metrics_collector
from .listener_peer import PeerListener
from .listener_sni import SNIProxy
from .peer import Peer
from .peer_manager import PeerManager, PeerManagerEvent

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from multiprocessing.managers import SyncManager


class ServerWorker(Process):
    """Worker for multiplexer."""

    def __init__(
        self,
        fernet_keys: list[str],
        throttling: int | None = None,
        metrics_factory: MetricsFactory | None = None,
        metrics_interval: int = 60,
    ) -> None:
        """Initialize worker & communication."""
        super().__init__()

        self._fernet_keys: list[str] = fernet_keys
        self._throttling: int | None = throttling
        self._metrics_factory = metrics_factory or create_noop_metrics_collector
        self._metrics_interval = metrics_interval

        # Used on the child
        self._peers: PeerManager | None = None
        self._list_sni: SNIProxy | None = None
        self._list_peer: PeerListener | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._metrics: MetricsCollector | None = None
        self._metrics_task: asyncio.Task | None = None

        # Communication between Parent/Child
        self._manager: SyncManager = Manager()
        self._new = self._manager.Queue()
        self._sync = self._manager.dict()
        self._peer_count = self._manager.Value("peer_count", 0)

    @property
    def peer_size(self) -> int:
        """Return amount of managed peers."""
        return self._peer_count.value

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

        # Initialize metrics collector in child process
        self._metrics = self._metrics_factory()

        self._list_sni = SNIProxy(self._peers)
        self._list_peer = PeerListener(self._peers, metrics=self._metrics)

        # Start metrics reporting task
        self._metrics_task = asyncio.create_task(self._report_metrics_loop())

    async def _report_metrics_loop(self) -> None:
        """Schedule periodic metrics reporting."""
        with contextlib.suppress(asyncio.CancelledError):
            next_report = time.monotonic() + self._metrics_interval
            while True:
                now = time.monotonic()
                sleep_time = next_report - now
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                await self._collect_and_report_metrics()
                next_report += self._metrics_interval

    async def _collect_and_report_metrics(self) -> None:
        """Collect current state and report metrics."""
        if not self._metrics:
            return

        if not self._peers:
            self._metrics.gauge("snitun.worker.peer_connections", 0)
            return

        protocol_version_counts: dict[int, int] = {
            0: 0,
            1: 0,
        }

        for peer in self._peers.iter_peers():
            if peer.protocol_version not in protocol_version_counts:
                protocol_version_counts[peer.protocol_version] = 0
                # Log out unknown protocol versions
                _LOGGER.warning(
                    "Unknown protocol version %d for peer %s",
                    peer.protocol_version,
                    peer.hostname,
                )
            protocol_version_counts[peer.protocol_version] += 1

        self._metrics.gauge(
            "snitun.worker.peer_connections",
            sum(protocol_version_counts.values()),
        )
        for version, count in protocol_version_counts.items():
            self._metrics.gauge(
                "snitun.worker.peer_connections",
                count,
                {"protocol_version": str(version)},
            )

    def _event_stream(self, peer: Peer, event: PeerManagerEvent) -> None:
        """Event stream peer connection data."""
        if event == PeerManagerEvent.CONNECTED:
            if peer.hostname not in self._sync:
                self._peer_count.set(self._peer_count.value + 1)
            for hostname in peer.all_hostnames:
                self._sync[hostname] = None
        else:
            if peer.hostname in self._sync:
                self._peer_count.set(self._peer_count.value - 1)
            for hostname in peer.all_hostnames:
                self._sync.pop(hostname, None)

    def shutdown(self) -> None:
        """Shutdown child process."""
        self._new.put(None)
        self.join(10)

    def handover_connection(
        self,
        con: socket,
        data: bytes,
        sni: str | None = None,
    ) -> None:
        """Move new connection to worker."""
        self._new.put_nowait((con, data, sni))

    def run(self) -> None:
        """Run the worker process."""
        _LOGGER.info("Start worker: %s", self.name)

        # Init new event loop
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        # Start eventloop
        running_loop = Thread(target=self._loop.run_forever)
        running_loop.start()

        # Init backend
        asyncio.run_coroutine_threadsafe(self._async_init(), loop=self._loop).result()

        while True:
            new = self._new.get()
            if new is None:
                break

            new[0].setblocking(False)
            asyncio.run_coroutine_threadsafe(
                self._async_new_connection(*new),
                loop=self._loop,
            )

        # Shutdown worker
        _LOGGER.info("Stoping worker: %s", self.name)

        # Cancel metrics task if running
        if self._metrics_task and not self._metrics_task.done():
            self._metrics_task.cancel()
            # Wait for metrics task to finish
            # Create a coroutine that waits for the task

            async def wait_for_task() -> None:
                with contextlib.suppress(asyncio.CancelledError):
                    if self._metrics_task:
                        await self._metrics_task

            with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                asyncio.run_coroutine_threadsafe(
                    wait_for_task(),
                    loop=self._loop,
                ).result()

        assert self._peers is not None, "PeerManager not initialized"
        asyncio.run_coroutine_threadsafe(
            self._peers.close_connections(),
            loop=self._loop,
        ).result()
        self._loop.call_soon_threadsafe(self._loop.stop)
        running_loop.join(10)

    async def _async_new_connection(
        self,
        con: socket,
        data: bytes,
        sni: str | None,
    ) -> None:
        """Handle incoming connection."""
        try:
            reader, writer = await asyncio.open_connection(sock=con)
        except OSError:
            con.close()
            return

        # Select the correct handler for process connection
        assert self._loop is not None, "Event loop not initialized"
        if sni:
            assert self._list_sni is not None, "SNIProxy not initialized"
            self._loop.create_task(
                self._list_sni.handle_connection(reader, writer, data=data, sni=sni),
            )
        else:
            assert self._list_peer is not None, "PeerListener not initialized"
            self._loop.create_task(
                self._list_peer.handle_connection(reader, writer, data=data),
            )
