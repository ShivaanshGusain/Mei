# test_transcriber.py
"""
Test script for AudioListener + Transcriber integration.
Run this directly: python test_transcriber.py
"""

import sys
import time

from ...core.events import EventType, subscribe, get_event_bus
from ...core.config import init_config
from ...perception.audio.listener import AudioListener
from ...perception.audio.transcriber import Transcriber


def on_speech_started(event):
    """Called when speech begins."""
    print("\n" + "=" * 50)
    print("🎤 SPEECH STARTED")
    print("=" * 50)


def on_speech_ended(event):
    """Called when speech ends."""
    audio_data = event.data.get('audio', b'')
    duration_samples = len(audio_data) // 2  # 2 bytes per sample (int16)
    duration_seconds = duration_samples / 16000  # Assuming 16kHz
    
    print(f"\n🔇 SPEECH ENDED")
    print(f"   Audio size: {len(audio_data)} bytes")
    print(f"   Duration: {duration_seconds:.2f} seconds")
    print(f"   Sending to transcriber...")


def on_transcribe_completed(event):
    """Called when transcription completes."""
    text = event.data.get('text', '')
    language = event.data.get('language', 'unknown')
    
    print("\n" + "=" * 50)
    print("📝 TRANSCRIPTION COMPLETED")
    print("=" * 50)
    print(f"   Text: '{text}'")
    print(f"   Language: {language}")
    print("=" * 50 + "\n")


def on_error(event):
    """Called on errors."""
    error = event.data.get('error', 'Unknown error')
    source = event.source
    print(f"\nERROR from {source}: {error}")


def main():
    print("=" * 60)
    print("  AUDIO LISTENER + TRANSCRIBER TEST")
    print("=" * 60)
    
    # Step 1: Initialize config
    print("\n[1] Loading config...")
    try:
        config = init_config()
        print(f"    ✓ Threshold: {config.audio.energy_threshold}")
        print(f"    ✓ Sample rate: {config.audio.sample_rate}")
        print(f"    ✓ Whisper model: {config.audio.model_path}")
    except Exception as e:
        print(f"    ✗ Config error: {e}")
        return
    
    # Step 2: Subscribe to events
    print("\n[2] Setting up event subscribers...")
    subscribe(EventType.SPEECH_STARTED, on_speech_started)
    subscribe(EventType.SPEECH_ENDED, on_speech_ended)
    subscribe(EventType.TRANSCRIBE_COMPLETED, on_transcribe_completed)
    subscribe(EventType.ERROR, on_error)
    print("    ✓ Subscribed to SPEECH_STARTED")
    print("    ✓ Subscribed to SPEECH_ENDED")
    print("    ✓ Subscribed to TRANSCRIBE_COMPLETED")
    print("    ✓ Subscribed to ERROR")
    
    # Step 3: Create Transcriber (loads model - slow!)
    print("\n[3] Creating Transcriber (loading Whisper model)...")
    print("    This may take 10-30 seconds...")
    try:
        start_time = time.time()
        transcriber = Transcriber()
        load_time = time.time() - start_time
        print(f"    ✓ Transcriber created in {load_time:.1f} seconds")
    except Exception as e:
        print(f"    ✗ Transcriber error: {e}")
        return
    
    # Step 4: Create Listener
    print("\n[4] Creating AudioListener...")
    try:
        listener = AudioListener()
        print("    ✓ AudioListener created")
    except Exception as e:
        print(f"    ✗ Listener error: {e}")
        return
    
    # Step 5: Start components
    print("\n[5] Starting components...")
    transcriber.start()
    listener.start()
    print("    ✓ Both components running")
    
    # Instructions
    print("\n" + "=" * 60)
    print("  READY! Speak into your microphone.")
    print("  ")
    print("  What will happen:")
    print("  1. You speak → 🎤 SPEECH STARTED")
    print("  2. You stop  → 🔇 SPEECH ENDED")
    print("  3. Whisper processes → 📝 TRANSCRIPTION COMPLETED")
    print("  ")
    print("  Press Ctrl+C to stop")
    print("=" * 60 + "\n")
    
    try:
        # Keep running until Ctrl+C
        while True:
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\n\n[6] Stopping...")
        
    finally:
        # Clean shutdown
        listener.stop()
        transcriber.stop()
        print("\n✓ Test complete!")


if __name__ == "__main__":
    main()