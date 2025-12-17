import os
import torch
import speech_recognition as sr
import numpy as np
from faster_whisper import WhisperModel

class Ears:
    def __init__(self, local_model_path):
        print(f"[Ears] Loading Faster-Whisper from: {local_model_path}")
        
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[Ears] Running on: {device}")

        try:
            # Load the model
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
        # Higher threshold prevents picking up breathing sounds
        self.recognizer.energy_threshold = 300 
        print("[Ears] Online.")

    def listen(self):
        # We enforce 16000Hz again as it worked for your debug file
        with sr.Microphone(sample_rate=16000) as source:
            print("[Ears] Adjusting for noise...")
            self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            print("[Ears] Ready. Speak now!")
            
            try:
                # 1. Listen (Time limit prevents hanging forever)
                audio_data = self.recognizer.listen(source, timeout=5, phrase_time_limit=10)
                
                # 2. Convert to Float32
                audio_np = np.frombuffer(audio_data.get_raw_data(), np.int16).flatten().astype(np.float32) / 32768.0
                
                # 3. Transcribe with STRICT parameters
                segments, info = self.model.transcribe(
                    audio_np, 
                    beam_size=5,
                    language="en",              # FORCE English
                    condition_on_previous_text=False, # Prevent repetition loops
                    vad_filter=True             # Ignore silence/background noise
                )
                
                full_text = ""
                for segment in segments:
                    full_text += segment.text
                
                text = full_text.strip()
                
                if text:
                    print(f"[Ears] Heard: '{text}'")
                    return text
                else:
                    print("[Ears] Heard silence.")
                    return None

            except sr.WaitTimeoutError:
                print("[Ears] Timeout: No speech detected.")
                return None
            except Exception as e:
                print(f"[Ears] Error: {e}")
                return None

if __name__ == "__main__":
    # UPDATE THIS PATH to your actual model folder
    MY_MODEL_FOLDER = r"C:\Users\Asus\Projects\Mei\models\whisper-model" 
    
    if os.path.exists(MY_MODEL_FOLDER):
        ears = Ears(MY_MODEL_FOLDER)
        while True:
            # Loop to let you test multiple phrases
            ears.listen()
    else:
        print("Model folder not found.")