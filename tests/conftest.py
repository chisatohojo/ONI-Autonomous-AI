import socket
from pathlib import Path

import pytest

from oni_ai.knowledge import create_database


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Offline tests must not use network sockets")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


@pytest.fixture
def knowledge_db(tmp_path: Path) -> Path:
    path = tmp_path / "knowledge.sqlite3"
    create_database(path)
    return path
