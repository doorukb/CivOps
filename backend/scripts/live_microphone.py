"""Live microphone -> Deepgram streaming transcription -> transcript events.

Two ways to run it:

* In-process (normal): the API starts `main()` in a worker thread when the
  console presses Start Call and passes a `publish` callback, so events never
  leave the process.
* Standalone: `python -m scripts.live_microphone` posts events to a running
  backend over HTTP. That endpoint is off unless both sides share
  CIVOPS_EVENT_TOKEN, and the target must be a loopback address.

Privacy: this module never logs or prints what was said. It logs counts only.
Audio goes to Deepgram for transcription; see docs/RESPONSIBLE_USE.md.

Single-speaker mode: the microphone has one channel and no diarization, so
every event is labelled "unknown".
"""

import logging
import os
import queue
import threading
import time
from collections.abc import Callable
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from app.models import MAX_EVENT_TEXT_CHARS, TranscriptEvent

load_dotenv()

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHUNK_SIZE = 1600  # 100 milliseconds of audio

# After "finalize", Deepgram sends the last words flagged from_finalize and,
# after "close stream", closes the socket. Wait for those signals instead of
# sleeping a fixed time; the timeouts only bound a silent connection.
FINALIZE_TIMEOUT_SECONDS = 3.0
CLOSE_TIMEOUT_SECONDS = 3.0

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}

Publish = Callable[[TranscriptEvent], object]


class MicrophoneSessionError(RuntimeError):
    """The session ended because transcription failed, not because it was stopped."""


def validated_api_url(url: str) -> str:
    """Only plain HTTP(S) to this machine. Rejects file:, ftp: and remote hosts."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError("CIVOPS_API_URL must start with http:// or https://")
    if parts.hostname not in LOOPBACK_HOSTS:
        raise ValueError("CIVOPS_API_URL must point at localhost; transcripts stay on this machine")
    return url.rstrip("/")


def http_publisher() -> Publish:
    """Publisher for standalone mode: POST each event to a local backend."""
    api_url = validated_api_url(os.environ.get("CIVOPS_API_URL", "http://127.0.0.1:8000"))
    token = os.environ.get("CIVOPS_EVENT_TOKEN", "")
    if not token:
        raise ValueError(
            "Standalone mode needs CIVOPS_EVENT_TOKEN set to the same value "
            "for the backend and this script."
        )

    def publish(event: TranscriptEvent) -> None:
        request = Request(  # noqa: S310 - scheme and host validated above
            f"{api_url}/transcript/event",
            data=event.model_dump_json().encode("utf-8"),
            headers={"Content-Type": "application/json", "X-CivOps-Token": token},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:  # noqa: S310
            response.read()

    return publish


def _load_audio_stack():
    """Imported here, not at module load, so a machine without PortAudio or a
    Deepgram key can still import this module (and so tests can fake both)."""
    import sounddevice
    from deepgram import DeepgramClient
    from deepgram.core.events import EventType

    return sounddevice, DeepgramClient, EventType


def main(
    stop_event: threading.Event | None = None,
    on_ready: Callable[[], object] | None = None,
    publish: Publish | None = None,
) -> int:
    """Run one microphone session until `stop_event` is set.

    Returns the number of final transcript segments. Raises
    MicrophoneSessionError if Deepgram reported an error or dropped the
    connection, after everything already transcribed has been published.
    """
    if stop_event is None:
        stop_event = threading.Event()
    if publish is None:
        publish = http_publisher()

    sd, deepgram_client, event_type = _load_audio_stack()
    client = deepgram_client()
    session_start = time.monotonic()

    finals = 0
    dropped_chunks = 0
    failure: list[BaseException | str] = []
    finalized = threading.Event()
    closed = threading.Event()

    publish_queue: queue.Queue[TranscriptEvent | None] = queue.Queue()

    def publisher_worker():
        while True:
            event = publish_queue.get()

            try:
                if event is None:
                    return

                publish(event)
            except Exception as error:
                # One undelivered event must not end the call.
                logger.warning("Could not publish a transcript event: %s", type(error).__name__)
            finally:
                publish_queue.task_done()

    publisher = threading.Thread(target=publisher_worker, daemon=True)
    publisher.start()

    # Thread-safe buffer between the microphone and Deepgram
    audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=100)

    def microphone_callback(indata, frames, time_info, status):
        nonlocal dropped_chunks

        if status:
            logger.warning("Microphone status: %s", status)

        try:
            audio_queue.put_nowait(bytes(indata))
        except queue.Full:
            dropped_chunks += 1

    def on_message(message):
        nonlocal finals

        channel = getattr(message, "channel", None)
        if channel is None:
            return  # metadata and other non-transcript messages

        # The reply to "finalize": everything spoken so far has been returned.
        if getattr(message, "from_finalize", False):
            finalized.set()

        if not channel.alternatives:
            return

        text = channel.alternatives[0].transcript

        if not text:
            return

        event = TranscriptEvent(
            speaker="unknown",
            text=text[:MAX_EVENT_TEXT_CHARS],
            is_final=bool(message.is_final),
            t=time.monotonic() - session_start,
        )

        publish_queue.put(event)

        if event.is_final:
            finals += 1

    def on_error(error):
        failure.append(error)
        logger.error("Deepgram error: %s", type(error).__name__)

    logger.info("Connecting to Deepgram")

    try:
        with client.listen.v1.connect(
            model="nova-3",
            language="en",
            encoding="linear16",
            sample_rate=str(SAMPLE_RATE),
            channels="1",
            interim_results="true",
            smart_format="true",
        ) as connection:

            connection.on(event_type.MESSAGE, on_message)
            connection.on(event_type.ERROR, on_error)
            connection.on(event_type.CLOSE, lambda _: closed.set())

            # Receive transcriptions in the background
            listener = threading.Thread(target=connection.start_listening, daemon=True)
            listener.start()

            with sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=microphone_callback,
            ):
                if on_ready:
                    on_ready()  # microphone is open and audio is flowing

                try:
                    # Stop on request, on a Deepgram error, or if the socket drops.
                    while not (stop_event.is_set() or failure or closed.is_set()):
                        try:
                            connection.send_media(audio_queue.get(timeout=0.3))
                        except queue.Empty:
                            continue
                except KeyboardInterrupt:
                    stop_event.set()

            if closed.is_set() and not stop_event.is_set() and not failure:
                failure.append("Deepgram closed the connection during the call")

            if not failure:
                # Ask Deepgram for the remaining words and wait for them.
                connection.send_finalize()
                if not finalized.wait(FINALIZE_TIMEOUT_SECONDS):
                    logger.warning("No finalize reply from Deepgram; closing anyway")
                connection.send_close_stream()
                closed.wait(CLOSE_TIMEOUT_SECONDS)

            listener.join(timeout=CLOSE_TIMEOUT_SECONDS)
    finally:
        # Deliver everything already transcribed before the caller sends the
        # end marker, on success and on failure alike.
        publish_queue.put(None)
        publish_queue.join()
        publisher.join(timeout=3)

        logger.info(
            "Microphone session finished: %d final segments, %d audio chunks dropped",
            finals,
            dropped_chunks,
        )

    if failure:
        reason = failure[0]
        raise MicrophoneSessionError(
            reason if isinstance(reason, str) else f"Deepgram error: {type(reason).__name__}"
        )

    return finals


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    main()
