import time
from ...core.events import EventType, subscribe, get_event_bus
from ...core.config import init_config
from .listener import AudioListener

def on_speech_started(event):
    """Called when speech begins."""
    print("\n🎤 SPEECH STARTED!")
    print(f"   Source: {event.source}")
    print(f"   Time: {event.timestamp}")


def on_speech_ended(event):
    """Called when speech ends."""
    audio_data = event.data.get('audio', b'')
    duration_samples = len(audio_data) // 2  # 2 bytes per sample (int16)
    duration_seconds = duration_samples / 16000  # Assuming 16kHz
    
    print("\n🔇 SPEECH ENDED!")
    print(f"   Audio size: {len(audio_data)} bytes")
    print(f"   Duration: {duration_seconds:.2f} seconds")


def on_error(event):
    """Called on errors."""
    print(f"\n❌ ERROR: {event.data.get('error')}")


def main():
    print("=" * 50)
    print("  AUDIO LISTENER TEST")
    print("=" * 50)
    
    # Initialize config
    print("\n[1] Loading config...")
    config = init_config()
    print(f"    Threshold: {config.audio.energy_threshold}")
    print(f"    Sample rate: {config.audio.sample_rate}")
    
    # Subscribe to events
    print("\n[2] Setting up event subscribers...")
    subscribe(EventType.SPEECH_STARTED, on_speech_started)
    subscribe(EventType.SPEECH_ENDED, on_speech_ended)
    subscribe(EventType.ERROR, on_error)
    print("    ✓ Subscribed to SPEECH_STARTED")
    print("    ✓ Subscribed to SPEECH_ENDED")
    print("    ✓ Subscribed to ERROR")
    
    # Create and start listener
    print("\n[3] Creating AudioListener...")
    listener = AudioListener()
    
    print("\n[4] Starting listener...")
    listener.start()
    print("    ✓ Listener running")
    
    print("\n" + "=" * 50)
    print("  LISTENING... (Speak into your microphone)")
    print("  Press Ctrl+C to stop")
    print("=" * 50)
    print("\nRMS values will print below. Watch for:")
    print("  - Silence: ~0.001 - 0.01")
    print("  - Speech:  ~0.02 - 0.20")
    print("-" * 50)
    
    try:
        # Keep running until Ctrl+C
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\n[5] Stopping...")
        listener.stop()
        print("    ✓ Listener stopped")
        print("\nTest complete!")


if __name__ == "__main__":
    main()