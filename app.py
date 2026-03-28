"""
Mei — Main entry point.
"""
import time
import threading
import os

from Mei.core.config import init_config
from Mei.core.pipeline import start_pipeline, stop_pipeline, process_text
from Mei.action.executor import get_executor
from Mei.perception.audio.listener import AudioListener
from Mei.perception.audio.transcriber import Transcriber
from Mei.core.events import EventType, subscribe
from Mei.memory.working import get_working_memory

def _on_speech_started(event):
    print("\n🎤 Speech detected!")


def _on_speech_ended(event):
    audio = event.data.get('audio', b'')
    duration = len(audio) / (2 * 16000)  # int16 = 2 bytes, 16kHz
    print(f"Speech ended: {len(audio)} bytes ({duration:.1f}s)")


def _on_transcribe_completed(event):
    text = event.data.get('text', '')
    lang = event.data.get('language', '?')
    print(f"Transcribed: '{text}' (lang={lang})")


def _on_error(event):
    print(f"Error from {event.source}: {event.data}")


def text_input_thread():
    """Runs in the background to accept typed commands."""
    time.sleep(1)
    print("\n--- Interactive mode (type commands or speak, 'quit' to exit) ---")

    while True:
        try:
            cmd = input().strip()

            if cmd.lower() in ('quit', 'exit', 'q'):
                print("Shutting down...")
                os._exit(0)

            if cmd:
                process_text(cmd)
        except Exception:
            break


def main():
    print("Starting Mei...")

    # 1. Initialize config
    init_config()

    working_memory = get_working_memory()

    # 2. Initialize executor
    executor = get_executor()
    print(f"Executor ready: {len(executor._handlers)} handlers registered")

    # 3. Start pipeline
    start_pipeline()

    # 4. Debug subscriptions — see the audio flow
    subscribe(EventType.SPEECH_STARTED, _on_speech_started)
    subscribe(EventType.SPEECH_ENDED, _on_speech_ended)
    subscribe(EventType.TRANSCRIBE_COMPLETED, _on_transcribe_completed)
    subscribe(EventType.ERROR, _on_error)
    print("Debug listeners attached for: SPEECH_STARTED, SPEECH_ENDED, TRANSCRIBE_COMPLETED, ERROR")

    # 5. Start Audio Components
    print("Loading Whisper Model... (This may take 10-20 seconds)")
    transcriber = Transcriber()
    transcriber.start()
    print(f"Transcriber started: queue={transcriber.queue is not None}, "
          f"thread={transcriber.thread is not None and transcriber.thread.is_alive()}")

    listener = AudioListener()
    print(f"AudioListener created: running={listener.running}")
    listener.start()
    print(f"AudioListener started: running={listener.running}")

    # 6. Quick sanity check — is the mic stream open?
    time.sleep(1)
    print(f"\n--- Audio Status ---")
    print(f"  Listener running: {listener.running}")
    print(f"  Listener stream: {listener.stream is not None}")
    print(f"  Listener threshold: {listener.threshold}")
    print(f"  Transcriber running: {transcriber.running}")
    print(f"--------------------\n")

    print("\nVoice input active: speak to control Mei")

    # 7. Start keyboard input in background
    input_thread = threading.Thread(target=text_input_thread, daemon=True)
    input_thread.start()

    # 8. Keep main thread alive
    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass

    # Cleanup
    print("\nCleaning up...")
    listener.stop()
    transcriber.stop()
    stop_pipeline()
    print("Mei stopped.")


if __name__ == "__main__":
    main()