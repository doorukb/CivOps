from pathlib import Path

from deepgram import DeepgramClient
from dotenv import load_dotenv

load_dotenv()


def transcribe_file(audio_path: str | Path) -> str:
    """
    Transcribe an audio recording using Deepgram.

    Returns the recognized speech as a string.
    """

    audio_path = Path(audio_path)

    if not audio_path.is_file():
        raise FileNotFoundError(
            f"Audio file not found: {audio_path}"
        )

    # Read the audio recording
    audio_bytes = audio_path.read_bytes()

    # Connect to Deepgram
    client = DeepgramClient()

    # Send audio for transcription
    response = client.listen.v1.media.transcribe_file(
        request=audio_bytes,
        model="nova-3",
        language="en",
        smart_format=True,
    )

    # Extract the transcription
    transcript = (
        response.results.channels[0]
        .alternatives[0]
        .transcript
    )

    return transcript