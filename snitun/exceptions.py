"""SniTun Exceptions."""


class SniTunError(Exception):
    """Base Exception for SniTun exceptions."""


class ParseSNIError(SniTunError):
    """Invalid ClientHello data."""


class MultiplexerTransportError(SniTunError):
    """Raise if multiplexer have an problem with peer."""