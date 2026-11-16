"""The microphone script, driven by fake audio and a fake Deepgram socket (G-09, S-05, S-07).

Importing the module must not need PortAudio or a Deepgram key: both are
loaded inside main(), which is what these tests replace.
"""

import threading
import types
from contextlib import contextmanager

import pytest

import scripts.live_microphone as mic
from app.models import TranscriptEvent


class EventType:
    MESSAGE, ERROR, CLOSE = "message", "error", "close"


def result(text, is_final=True, from_finalize=False):
    return types.SimpleNamespace(
        channel=types.SimpleNamespace(alternatives=[types.SimpleNamespace(transcript=text)]),
        is_final=is_final,
        from_finalize=from_finalize,
    )


class FakeConnection:
    """Plays `script` to the handlers, then behaves like Deepgram at the end
    of a call: finalize -> last words flagged from_finalize; close -> CLOSE."""

    def __init__(self, script=(), error=None, last_words="last words", drop=False):
        self.script, self.error, self.last_words, self.drop = script, error, last_words, drop
        self.handlers = {}
        self.sent = []
        self.calls = []
        self.release = threading.Event()
        self.on_media = lambda: None

    def on(self, event, handler):
        self.handlers[event] = handler

    def start_listening(self):
        for message in self.script:
            self.handlers[EventType.MESSAGE](message)
        if self.error is not None:
            self.handlers[EventType.ERROR](self.error)
        if self.error is not None or self.drop:
            self.handlers[EventType.CLOSE](None)
            return
        self.release.wait(5)
        self.handlers[EventType.CLOSE](None)

    def send_media(self, chunk):
        self.sent.append(chunk)
        self.on_media()

    def send_finalize(self):
        self.calls.append("finalize")
        if self.last_words is not None:
            self.handlers[EventType.MESSAGE](result(self.last_words, from_finalize=True))

    def send_close_stream(self):
        self.calls.append("close")
        self.release.set()


class FakeInputStream:
    def __init__(self, callback, **_):
        self.callback = callback

    def __enter__(self):
        self.callback(b"\x00\x01" * 10, 10, None, None)  # one chunk of "audio"
        return self

    def __exit__(self, *_):
        return False


def install(monkeypatch, connection):
    @contextmanager
    def connect(**_):
        yield connection

    client = types.SimpleNamespace(
        listen=types.SimpleNamespace(v1=types.SimpleNamespace(connect=connect))
    )
    sounddevice = types.SimpleNamespace(RawInputStream=FakeInputStream)
    monkeypatch.setattr(mic, "_load_audio_stack", lambda: (sounddevice, lambda: client, EventType))
    monkeypatch.setattr(mic, "FINALIZE_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(mic, "CLOSE_TIMEOUT_SECONDS", 0.5)


def run(connection, publish, stop_after_audio=True):
    """Run one session. By default the operator presses End Call right after
    the first chunk of audio has been sent."""
    stop = threading.Event()
    ready = []

    if stop_after_audio:
        connection.on_media = stop.set

    return mic.main(stop, on_ready=lambda: ready.append(True), publish=publish), ready


def test_normal_stop_publishes_everything_including_the_last_words(monkeypatch):
    connection = FakeConnection(script=[result("hel", is_final=False), result("hello there")])
    install(monkeypatch, connection)
    published: list[TranscriptEvent] = []

    finals, ready = run(connection, published.append)

    assert ready == [True]
    assert [(e.text, e.is_final) for e in published] == [
        ("hel", False), ("hello there", True), ("last words", True),
    ]
    assert finals == 2
    assert all(e.speaker == "unknown" for e in published)  # single-speaker mode
    assert connection.calls == ["finalize", "close"]  # waited for the reply, no fixed sleep
    assert connection.sent == [b"\x00\x01" * 10]  # audio reached Deepgram


def test_missing_finalize_reply_only_costs_the_timeout(monkeypatch):
    connection = FakeConnection(script=[result("hello")], last_words=None)
    install(monkeypatch, connection)
    published = []

    finals, _ = run(connection, published.append)

    assert finals == 1 and connection.calls == ["finalize", "close"]


def test_deepgram_error_ends_the_session_with_an_error(monkeypatch):
    """A dropped connection used to be printed and ignored, leaving the page
    on 'CALL IN PROGRESS' with no text."""
    connection = FakeConnection(script=[result("before the drop")], error=RuntimeError("boom"))
    install(monkeypatch, connection)
    published = []

    with pytest.raises(mic.MicrophoneSessionError, match="Deepgram error: RuntimeError"):
        run(connection, published.append, stop_after_audio=False)

    # What was already transcribed is still delivered before the error surfaces.
    assert [e.text for e in published] == ["before the drop"]
    assert connection.calls == []  # no finalize on a dead socket


def test_silent_disconnect_ends_the_session_with_an_error(monkeypatch):
    connection = FakeConnection(drop=True)
    install(monkeypatch, connection)

    with pytest.raises(mic.MicrophoneSessionError, match="closed the connection"):
        run(connection, lambda event: None, stop_after_audio=False)


def test_publisher_failure_does_not_crash_the_session(monkeypatch):
    connection = FakeConnection(script=[result("one"), result("two")])
    install(monkeypatch, connection)
    delivered = []

    def flaky(event):
        if event.text == "one":
            raise ConnectionError("backend restarting")
        delivered.append(event.text)

    finals, _ = run(connection, flaky)

    assert finals == 3 and delivered == ["two", "last words"]


def test_nothing_that_was_said_is_logged_or_printed(monkeypatch, caplog, capsys):
    import logging

    caplog.set_level(logging.DEBUG)
    connection = FakeConnection(script=[result("my secret address is 12 Elm Street")])
    install(monkeypatch, connection)

    run(connection, lambda event: None)

    output = capsys.readouterr()
    for text in (caplog.text, output.out, output.err):
        assert "secret" not in text and "Elm Street" not in text and "last words" not in text
    assert "2 final segments" in caplog.text  # counts only


def test_worker_turns_a_deepgram_error_into_the_error_marker(monkeypatch):
    import app.main as main

    connection = FakeConnection(error=RuntimeError("boom"))
    install(monkeypatch, connection)
    posted = []
    monkeypatch.setattr(main, "post_system_event", lambda *args: posted.append(args))
    monkeypatch.setattr(main, "post_event", lambda event: None)

    main.microphone_worker(threading.Event(), "call-1234")

    assert posted == [("__call_started__", "call-1234"), ("__call_error__", "call-1234")]


# --- Standalone mode ---------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "ftp://127.0.0.1/x", "http://example.com:8000", "http://10.0.0.5:8000"],
)
def test_api_url_must_be_http_on_this_machine(url):
    with pytest.raises(ValueError):
        mic.validated_api_url(url)


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:8000", "http://localhost:8000/", "http://[::1]:8000"]
)
def test_loopback_api_urls_are_accepted(url):
    assert mic.validated_api_url(url) == url.rstrip("/")


def test_standalone_mode_refuses_to_run_without_a_token(monkeypatch):
    monkeypatch.delenv("CIVOPS_EVENT_TOKEN", raising=False)

    with pytest.raises(ValueError, match="CIVOPS_EVENT_TOKEN"):
        mic.http_publisher()


def test_standalone_publisher_sends_the_token(monkeypatch):
    monkeypatch.setenv("CIVOPS_EVENT_TOKEN", "s3cret-token")
    monkeypatch.setenv("CIVOPS_API_URL", "http://127.0.0.1:8000")
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b"{}"

    monkeypatch.setattr(mic, "urlopen", lambda request, timeout: requests.append(request) or Response())

    mic.http_publisher()(TranscriptEvent(speaker="unknown", text="hi", is_final=True, t=0.0))

    assert requests[0].full_url == "http://127.0.0.1:8000/transcript/event"
    assert requests[0].get_header("X-civops-token") == "s3cret-token"
