import socket

import pytest


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Any attempt to open a network connection during tests fails loudly."""
    def refuse(*args, **kwargs):
        raise RuntimeError("network access is forbidden in jev-turing tests")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
