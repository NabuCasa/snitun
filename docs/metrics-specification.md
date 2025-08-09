# SniTun Server-Side Metrics Specification

## Overview

This document specifies the design and implementation requirements for server-side metrics collection in SniTun. The metrics system provides visibility into peer connections and protocol versions while properly handling the multiprocessing architecture of the production server.

## Goals

1. **Visibility**: Provide real-time insights into server operation
2. **Multiprocess Safety**: Handle metrics correctly across multiple worker processes
3. **Zero Overhead**: No performance impact when metrics are disabled
4. **Extensibility**: Support different metrics backends (StatsD, Prometheus, etc.)
5. **Simplicity**: Easy to integrate without disrupting existing code

## Architecture

### Key Challenges

The production architecture (`SniTunServerWorker`) works as follows:

- Main entry point that runs in a separate thread
- Spawns multiple `ServerWorker` processes (default: CPU count × 2)
- Each `ServerWorker` runs as an independent process
- Parent thread handles socket accept and connection distribution
- Worker processes handle the actual connection processing

The multiprocess architecture presents unique challenges:

- Each worker process handles a subset of connections independently
- Workers use shared memory (`multiprocessing.Manager`) for coordination
- Metrics must avoid collisions when multiple processes report to the same backend

### Solution: Process-Aware Metrics

To avoid shared memory complexity for metrics:

- Each `ServerWorker` process creates its own independent metrics collector instance
- Every metric automatically includes:
  - `hostname`: The server hostname
  - `process_id`: The process ID of the reporting worker

This ensures that gauge metrics from different processes don't overwrite each other and eliminates the need for shared memory synchronization of metrics data.

## API Specification

### Core Interface

The metrics system shall provide a `MetricsCollector` abstract base class with the following methods:

#### `gauge(name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None`

Sets a gauge metric to a specific value. Gauges represent point-in-time measurements.

- **name**: Metric name (e.g., 'snitun.peer.connections')
- **value**: Current value
- **tags**: Optional tags for the metric

#### `increment(name: str, value: float = 1, tags: Optional[Dict[str, str]] = None) -> None`

Increments a counter metric. Counters are cumulative values that only increase.

- **name**: Metric name (e.g., 'snitun.connections.new')
- **value**: Amount to increment (default: 1)
- **tags**: Optional tags for the metric

#### `histogram(name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None`

Records a value in a histogram for statistical distribution analysis.

- **name**: Metric name (e.g., 'snitun.connection.duration')
- **value**: Value to record
- **tags**: Optional tags for the metric

#### `timing(name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None`

Records a timing value in milliseconds.

- **name**: Metric name (e.g., 'snitun.handshake.time')
- **value**: Time in milliseconds
- **tags**: Optional tags for the metric

### Factory Pattern

The system shall use a factory pattern for metrics creation:

```python
MetricsFactory = Callable[[], MetricsCollector]
```

Required factory functions:

- `create_default_metrics_collector()`: Returns an in-memory metrics collector
- `create_noop_metrics_collector()`: Returns a no-operation collector (zero overhead)

## Implementation Requirements

### Default Metrics Collector

The default implementation shall:

- Store metrics in memory for debugging/testing purposes
- Automatically add `hostname` and `process_id` tags to all metrics
- Use system hostname and process ID by default
- Allow override of hostname and process_id during initialization
- Maintain timestamps for all metric updates
- Does not need to be thread-safe (runs in single event loop thread)

### No-Op Collector

The no-op implementation shall:

- Implement all `MetricsCollector` methods as no-ops
- Have zero memory allocation
- Have zero CPU overhead
- Be the default when no metrics factory is provided

### System Tag Requirements

All collectors must:

- Automatically inject `hostname` tag using `socket.gethostname()`
- Automatically inject `process_id` tag using `os.getpid()`
- Apply these tags before any user-provided tags
- Ensure these tags cannot be overridden by user tags

## Server Integration Points

### Worker Process Integration

#### Initialization

- `ServerWorker.__init__` shall accept optional `metrics_factory` parameter
- `ServerWorker.__init__` shall accept optional `metrics_interval` parameter (default: 60 seconds)
- Each `ServerWorker` process shall create its own metrics collector instance in the child process
- Metrics collector runs in the worker's event loop thread (single-threaded context)
- No shared memory synchronization needed for metrics data

#### Metrics Collection

- Each worker independently tracks its own:
  - Number of protocol v0 connections
  - Number of protocol v1 connections
- Each worker reports metrics directly to the metrics backend
- Process isolation ensures no conflicts between workers
- Metrics collector does not need thread-safety (runs in single event loop)

#### Reporting Task

- Create async task for periodic metrics reporting
- Task shall run every `metrics_interval` seconds in the event loop
- Task shall collect current state from local process data
- Task shall report via its own metrics collector instance
- No locking needed as all metrics operations happen in the same event loop
- Task shall be cancelled during shutdown

### Parent Thread Integration (SniTunServerWorker)

#### Initialization

- `SniTunServerWorker.__init__` shall accept optional `metrics_factory` parameter
- `SniTunServerWorker.__init__` shall accept optional `metrics_interval` parameter
- Parent thread shall create its own metrics collector instance
- Parent thread is responsible for spawning `ServerWorker` processes

#### Metrics Reporting

- Parent thread creates its own metrics collector instance (optional)
- Parent thread can report its own metrics (e.g., total workers spawned)
- Aggregation of worker metrics is handled by the metrics backend using hostname/process_id tags
- No need for parent thread to aggregate worker metrics manually

### Single Process Server Integration

For `SniTunServer` and `SniTunServerSingle`:

- Accept optional `metrics_factory` parameter
- Create metrics collector during initialization
- Report metrics directly from async context
- No need for shared memory or aggregation

## Metrics Taxonomy

### Per-Worker Metrics

All worker metrics include automatic `hostname` and `process_id` tags.

| Metric Name                      | Type  | Description                            | Additional Tags    |
| -------------------------------- | ----- | -------------------------------------- | ------------------ |
| `snitun.worker.peer_connections` | gauge | Active peer connections in this worker | `protocol_version` |

Note: Cluster-wide totals (sum of all worker metrics) are computed by the metrics backend using aggregation queries based on hostname tags.

### Connection Lifecycle Metrics

| Metric Name            | Type    | Description             | Additional Tags |
| ---------------------- | ------- | ----------------------- | --------------- |
| `snitun.auth.attempts` | counter | Authentication attempts | `result`        |
| `snitun.auth.failures` | counter | Authentication failures | `reason`        |

## Backend Implementation Guidelines

### StatsD Backend

Requirements for StatsD implementation:

- Inherit from `MetricsCollector` base class
- Format tags according to StatsD conventions (typically `metric.name,tag1=value1,tag2=value2`)
- Support configurable host, port, and prefix
- Support configurable sample rate
- Handle connection failures gracefully
- Buffer metrics if connection is unavailable

### Prometheus Backend

Requirements for Prometheus implementation:

- Inherit from `MetricsCollector` base class
- Convert dot notation to underscores for Prometheus compatibility
- Support custom `CollectorRegistry`
- Handle label names dynamically based on provided tags
- Cache metric instances to avoid recreation
- Support both push gateway and pull (HTTP endpoint) modes

### Custom Backend Guidelines

When implementing custom backends:

1. Always inherit from `MetricsCollector` base class
2. Thread-safety is not required (runs in single event loop)
3. Handle backend unavailability gracefully
4. Consider batching for network efficiency
5. Implement connection pooling if applicable
6. Add automatic reconnection logic
7. Respect the automatic system tags
8. Use async I/O where possible to avoid blocking the event loop

## Usage Patterns

### Basic Usage

```python
# With default in-memory metrics
server = SniTunServerWorker(
    fernet_keys=['key'],
    metrics_factory=create_default_metrics_collector,
    metrics_interval=30
)

# With custom metrics backend
def create_custom_metrics():
    return CustomMetricsCollector(config)

server = SniTunServerWorker(
    fernet_keys=['key'],
    metrics_factory=create_custom_metrics
)

# With no metrics (default)
server = SniTunServerWorker(
    fernet_keys=['key']
)
```

### Unit Tests

Required test coverage:

- Verify system tags are added automatically
- Verify no-op collector has zero overhead
- Test metric name validation
- Test tag formatting
- Verify factory pattern works correctly
- Test shared memory updates in worker

### Integration Tests

Required integration tests:

- Worker metrics reporting with mock collector
- Parent process aggregation accuracy
- Multiprocess metric isolation
- Graceful shutdown with metrics
- Metrics reporting interval accuracy
- Memory leak testing for long-running metrics

## Appendix

### Metric Naming Conventions

- Use dots for hierarchy: `snitun.component.metric`
- Use underscores in tag values: `protocol_version`
- Be consistent with singular/plural forms
- Include units in metric names when not obvious (e.g., `_ms`, `_bytes`)
- Use standard prefixes: `total_`, `current_`, `avg_`

### Tag Guidelines

- Keep tag cardinality low (<100 unique values)
- Use consistent tag names across metrics
- Standard tags: `protocol_version`, `type`, `reason`, `result`
- Avoid high-cardinality tags (user IDs, IP addresses)
- Use enumerated values for tags when possible
