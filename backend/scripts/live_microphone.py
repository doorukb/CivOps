
import queue
import threading
import time

import sounddevice as sd
from dotenv import load_dotenv
from deepgram import DeepgramClient
from deepgram.core.events import EventType
from deepgram.listen.v1.types import ListenV1Results
from app.models import TranscriptEvent

import json
from urllib.request import Request, urlopen

load_dotenv()

SAMPLE_RATE = 16000
CHUNK_SIZE = 1600  # 100 milliseconds of audio

def publish_event(event: TranscriptEvent):
    url = "http://127.0.0.1:8000/transcript/event"

    data = event.model_dump_json().encode("utf-8")

    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urlopen(request, timeout=2) as response:
            response.read()

    except Exception as error:
        print("Failed to publish transcript:", error)

def main(stop_event=None, on_ready=None):
    if stop_event is None:
        stop_event = threading.Event()
    client = DeepgramClient()
    transcript_events = []
    session_start = time.monotonic()

    publish_queue = queue.Queue()

    def publisher_worker():
        while True:
            event = publish_queue.get()

            try:
                if event is None:
                    return

                publish_event(event)
            finally:
                publish_queue.task_done()

    publisher = threading.Thread(
        target=publisher_worker,
        daemon=True
    )
    publisher.start()

    # Thread-safe buffer between the microphone and Deepgram
    audio_queue = queue.Queue(maxsize=100)

    def microphone_callback(indata, frames, time_info, status):
        if status:
            print("Microphone status:", status)

        try:
            audio_queue.put_nowait(bytes(indata))
        except queue.Full:
            print("Audio buffer full; dropping a chunk")

    def on_message(message):
        if not isinstance(message, ListenV1Results):
            return

        if not message.channel.alternatives:
            return

        text = message.channel.alternatives[0].transcript

        if not text:
            return

        event = TranscriptEvent(
            speaker="unknown",
            text=text,
            is_final=message.is_final,
            t=time.monotonic() - session_start
        )

        publish_queue.put(event)

        if event.is_final:
            transcript_events.append(event)
            print("FINAL:", event.text)
        else:
            print("Interim:", event.text)

    print("Connecting to Deepgram...")

    with client.listen.v1.connect(
        model="nova-3",
        language="en",
        encoding="linear16",
        sample_rate=str(SAMPLE_RATE),
        channels="1",
        interim_results="true",
        smart_format="true",
    ) as connection:

        connection.on(EventType.MESSAGE, on_message)
        connection.on(
            EventType.ERROR,
            lambda error: print("Deepgram error:", error)
        )

        # Receive transcriptions in the background
        listener = threading.Thread(
            target=connection.start_listening,
            daemon=True
        )
        listener.start()

        print("Microphone starting. Speak normally!")

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
                while not stop_event.is_set():
                    try:
                        audio_chunk = audio_queue.get(timeout=0.3)
                        connection.send_media(audio_chunk)
                    except queue.Empty:
                        continue
            except KeyboardInterrupt:
                print("\nStopping microphone...")
                stop_event.set()

        # Ask Deepgram to finish the remaining transcript
        connection.send_finalize()
        time.sleep(1.5)
        connection.send_close_stream()
        listener.join(timeout=3)

        complete_transcript = " ".join(
        event.text
        for event in transcript_events
        if event.is_final
    )

    print("\n=== COMPLETE TRANSCRIPT ===")
    print(complete_transcript)

    publish_queue.put(None)
    publish_queue.join()
    publisher.join(timeout=3)

    print("Session finished.")


if __name__ == "__main__":
    main()
