import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.main as main
from app.main import app

client = TestClient(app)


@pytest.mark.parametrize(
    "origin", ["https://evil.example", "http://evil.example:8000", "null"]
)
def test_cross_site_page_cannot_start_microphone(origin, monkeypatch):
    started = []
    monkeypatch.setattr(main.threading, "Thread", lambda **kw: started.append(kw))

    response = client.post("/calls/start", headers={"Origin": origin})

    assert response.status_code == 403
    assert started == []


def test_cross_site_page_cannot_read_transcript():
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(
            "/ws/transcript", headers={"Origin": "https://evil.example"}
        ):
            pass
    assert closed.value.code == 1008


@pytest.mark.parametrize(
    "host",
    ["evil.example", "evil.example:8000", "localhost.evil.example", "169.254.169.254", ""],
)
def test_requests_addressed_to_another_host_are_refused(host):
    """DNS rebinding: the page is 'same-origin', so it may send no Origin, but
    it has to send its own host name."""
    response = client.get("/scenarios", headers={"Host": host})

    assert response.status_code == 403
    assert response.text == "Forbidden host"


def test_rebound_host_cannot_start_microphone_or_read_transcript(monkeypatch):
    started = []
    monkeypatch.setattr(main.threading, "Thread", lambda **kw: started.append(kw))

    assert client.post("/calls/start", headers={"Host": "evil.example"}).status_code == 403
    assert started == []

    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/ws/transcript", headers={"Host": "evil.example"}):
            pass
    assert closed.value.code == 1008


@pytest.mark.parametrize(
    "host", ["localhost", "localhost:8000", "127.0.0.1:8000", "[::1]:8000", "LOCALHOST:5173"]
)
def test_local_host_names_are_accepted(host):
    assert client.get("/scenarios", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [{}, {"Origin": "http://localhost:5173"}, {"Origin": "http://127.0.0.1:8000"}],
)
def test_local_pages_and_scripts_still_work(headers):
    assert client.post(
        "/calls/screen", json={"transcript": "hi"}, headers=headers
    ).status_code == 200
    with client.websocket_connect("/ws/transcript", headers=headers):
        pass
