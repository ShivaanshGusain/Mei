# Audio/ear.py
"""
Ears - Audio listening and transcription using Faster Whisper.
Includes filtering to reject garbage/hallucinated transcriptions.
"""

import os
import torch
import speech_recognition as sr
import numpy as np
from faster_whisper import WhisperModel
import re


class Ears:
    def __init__(self, local_model_path):
        print(f"[Ears] Loading Faster-Whisper from: {local_model_path}")
        
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[Ears] Running on: {device}")

        try:
            self.model = WhisperModel(
                local_model_path, 
                device=device, 
                compute_type="int8"
            )
            print("[Ears] Model Loaded.")
        except Exception as e:
            print(f"[Ears] LOAD ERROR: {e}")
            raise e

        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 400  # Higher = less sensitive to quiet sounds
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.pause_threshold = 0.8  # Seconds of silence before phrase is complete
        
        # Common hallucinations that Whisper produces from silence/noise
        self.garbage_phrases = [
            "thank you",
            "thanks for watching",
            "please subscribe",
            "like and subscribe",
            "see you next time",
            "bye",
            "you",
            "the",
            "i'll do it",
            "i'm going to",
            "when we have",
            "we have scored",
            "so",
            "and",
            "um",
            "uh",
            "hmm",
            "oh",
            "ah",
            "...",
            "music",
            "[music]",
            "(music)",
        ]
        
        print("[Ears] Online.")

    def _is_garbage(self, text):
        """Check if transcription is likely garbage/hallucination."""
        if not text:
            return True
        
        text_lower = text.lower().strip()
        
        # Too short
        if len(text_lower) < 3:
            return True
        
        # Just one word that isn't a command
        words = text_lower.split()
        if len(words) == 1 and words[0] not in ['exit', 'quit', 'stop', 'click', 'open', 'close', 'save', 'search', 'type']:
            return True
        
        # Known garbage phrases
        for garbage in self.garbage_phrases:
            if text_lower == garbage or text_lower.startswith(garbage + " ") or text_lower.endswith(" " + garbage):
                return True
            # Also check if the text IS a garbage phrase
            if garbage in text_lower and len(text_lower) < len(garbage) + 10:
                return True
        
        # Doesn't look like a command (no verbs/actions)
        command_words = [
            'click', 'press', 'open', 'close', 'go', 'navigate', 'search', 
            'type', 'write', 'enter', 'select', 'choose', 'find', 'show',
            'minimize', 'maximize', 'scroll', 'save', 'copy', 'paste',
            'multiply', 'divide', 'add', 'subtract', 'calculate', 'plus', 'minus',
            'seven', 'eight', 'nine', 'one', 'two', 'three', 'four', 'five', 'six', 'zero',
            '7', '8', '9', '1', '2', '3', '4', '5', '6', '0',
            'exit', 'quit', 'stop', 'sleep', 'wake'
        ]
        
        has_command_word = any(word in text_lower for word in command_words)
        
        if not has_command_word:
            # Check if it at least mentions something clickable
            if not any(char.isdigit() for char in text_lower):
                print(f"[Ears] Filtered as non-command: '{text}'")
                return True
        
        return False

    def listen(self):
        """Listen for speech and return transcription."""
        with sr.Microphone(sample_rate=16000) as source:
            print("[Ears] Adjusting for noise...")
            self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            print("[Ears] Ready. Speak now!")
            
            try:
                # Listen with timeout
                audio_data = self.recognizer.listen(
                    source, 
                    timeout=5,              # Max wait for speech to start
                    phrase_time_limit=10    # Max length of phrase
                )
                
                # Convert to numpy array
                audio_np = np.frombuffer(
                    audio_data.get_raw_data(), 
                    np.int16
                ).flatten().astype(np.float32) / 32768.0
                
                # Check if audio has enough energy (not just silence)
                audio_energy = np.abs(audio_np).mean()
                if audio_energy < 0.005:
                    print("[Ears] Audio too quiet, likely silence.")
                    return None
                
                # Transcribe
                segments, info = self.model.transcribe(
                    audio_np, 
                    beam_size=5,
                    language="en",
                    condition_on_previous_text=False,
                    vad_filter=True,
                    vad_parameters=dict(
                        min_silence_duration_ms=500,
                        speech_pad_ms=200
                    )
                )
                
                # Combine segments
                full_text = ""
                for segment in segments:
                    full_text += segment.text
                
                text = full_text.strip()
                
                # Filter garbage
                if self._is_garbage(text):
                    print(f"[Ears] Filtered garbage: '{text}'")
                    return None
                
                print(f"[Ears] Heard: '{text}'")
                return text

            except sr.WaitTimeoutError:
                print("[Ears] Timeout: No speech detected.")
                return None
            except Exception as e:
                print(f"[Ears] Error: {e}")
                return None


# ══════════════════════════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    MODEL_PATH = r"C:\Users\Asus\Projects\Mei\models\whisper-model"
    
    if not os.path.exists(MODEL_PATH):
        print(f"Model not found: {MODEL_PATH}")
    else:
        ears = Ears(MODEL_PATH)
        
        print("\n" + "="*50)
        print("EARS TEST - Say something!")
        print("="*50)
        
        while True:
            result = ears.listen()
            if result:
                print(f"\n>>> ACCEPTED: '{result}'\n")
                if 'exit' in result.lower():
                    break