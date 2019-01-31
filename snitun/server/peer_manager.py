"""Manage peer connections."""
from typing import List
import json


class PeerManager:
    """Manage Peer connections."""

    def __init__(self, fernet_tokens: List[str]):
        """Initialize Peer Manager."""