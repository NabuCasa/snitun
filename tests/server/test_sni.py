"""Tests for SNI parser."""

import pytest

from snitun.exceptions import ParseSNIError
from snitun.server import sni

from . import const_tls as raw


@pytest.mark.parametrize([
    raw.TLS_1_0, raw.TLS_1_0_OLD, raw.TLS_1_2, raw.TLS_1_2_MORE,
    raw.TLS_1_2_ORDER
])
def test_good_client_hello(test_package: bytes):
    """Test good TLS packages."""
    assert sni.parse_tls_sni(test_package) == "localhost"


@pytest.mark.parametrize(
    [raw.BAD_DATA1, raw.BAD_DATA2, raw.BAD_DATA3, raw.SSL_2_0, raw.SSL_3_0])
def test_bad_client_hello(test_package: bytes):
    """Test bad client hello."""
    with pytest.raises(ParseSNIError):
        sni.parse_tls_sni(test_package)
