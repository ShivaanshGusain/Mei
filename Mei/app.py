import os
import time
import sys
from PIL import ImageGrab
from unittest.mock import MagicMock
sys.modules["flash_attn"] = MagicMock()
sys.modules["flash_attn.flash_attn_interface"] = MagicMock()
# Import your organs
# Ensure these paths match your folder structure exactly
from Action.executer import Executor
from Audio.ear import Ears
from Perception.perception import PerceptionManager
from Cognition.cortex import Cortex
from Interaction.voice import Voice

class MeiAgent:
    def __init__(self):
        print("\n[SYSTEM] BOOT SEQUENCE INITIATED...")
        
        # 1. PATHS
        # Define where your models live
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        PROJECT_ROOT = os.path.dirname(BASE_DIR) # Go up one level if needed, or adjust based on where models folder is
        
        # Update these to your ACTUAL paths
        WHISPER_PATH = r"C:\Users\Asus\Projects\Mei\models\whisper-model"
        QWEN_PATH = r"C:\Users\Asus\Projects\Mei\models\qwen2.5-3b-instruct-q4_k_m.gguf"
        
        # 2. INITIALIZE ORGANS
        # We start the Mouth first so she can greet us
        self.mouth = Voice()
        self.mouth.speak("Initializing core systems.")

        # Ears (Listening)
        self.ears = Ears(WHISPER_PATH)

        # Eyes (Perception Manager handles both Symbolic and Visual)
        # Note: We pass the project root so it can find the OmniParser weights
        self.eyes = PerceptionManager(PROJECT_ROOT)

        # Brain (Cognition)
        self.brain = Cortex(QWEN_PATH)

        # Hands (Action)
        self.hand = Executor()

        self.mouth.speak("All systems online. I am listening.")
        print("[SYSTEM] READY.")

    def run(self):
        """
        The Main Loop of Life.
        """
        while True:
            try:
                # --- STEP 1: LISTEN ---
                print("\n[1] Listening...")
                user_command = self.ears.listen()
                
                if not user_command:
                    continue # Heard silence, loop again
                
                if "exit" in user_command.lower() or "sleep" in user_command.lower():
                    self.mouth.speak("Shutting down. Goodbye.")
                    break

                print(f"[USER] {user_command}")
                self.mouth.speak("Understood.")

                # --- STEP 2: SEE (Perception) ---
                print("[2] Analyzing Screen...")
                
                # 1. Define the path
                screenshot_path = os.path.join(os.getcwd(), "current_view.png")
                
                # 2. TAKE THE SCREENSHOT (The missing line)
                snapshot = ImageGrab.grab()
                snapshot.save(screenshot_path)
                
                # 3. Now the file exists, so we can analyze it
                ui_elements, source, window_title = self.eyes.get_screen_state(screenshot_path)
                
                # --- STEP 3: THINK ---
                print(f"[3] Thinking... (Context: {window_title})")
                
                # We pass the window title so the Brain knows "I am in Calculator"
                step_list = self.brain.think(user_command, ui_elements, active_window_title=window_title)
                
                if not step_list:
                    self.mouth.speak("I am not sure what to click.")
                    continue

                # --- STEP 4: ACT (Loop through the plan) ---
                print(f"[4] Executing Plan: {step_list}")
                self.mouth.speak(f"Executing {len(step_list)} actions.")

                for index in step_list:
                    print(f"   -> Clicking Item {index}")
                    success = self.hand.perform_action(index, ui_elements)
                    if not success:
                        self.mouth.speak("I lost track of the plan.")
                        break
                    # Wait a bit between clicks so the app can react
                    time.sleep(0.5) 
                
                self.mouth.speak("Plan complete.")

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"[CRITICAL ERROR] {e}")
                self.mouth.speak("I encountered a critical error.")

if __name__ == "__main__":
    # Disable the annoying model check
    os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"
    
    agent = MeiAgent()
    agent.run()