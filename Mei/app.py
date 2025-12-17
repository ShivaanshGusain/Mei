# app.py
"""
Mei Agent - Main Application
"""

import os
import sys
import time

# ══════════════════════════════════════════════════════════════════════════════
# SETUP
# ══════════════════════════════════════════════════════════════════════════════

os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"

from unittest.mock import MagicMock
import types

if "flash_attn" not in sys.modules:
    fake_flash = types.ModuleType("flash_attn")
    fake_flash.__spec__ = types.SimpleNamespace(name="flash_attn", loader=None, origin="fake", submodule_search_locations=[])
    fake_flash.__path__ = []
    fake_interface = types.ModuleType("flash_attn.flash_attn_interface")
    fake_flash.flash_attn_interface = fake_interface
    sys.modules["flash_attn"] = fake_flash
    sys.modules["flash_attn.flash_attn_interface"] = fake_interface

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ══════════════════════════════════════════════════════════════════════════════
# IMPORTS
# ══════════════════════════════════════════════════════════════════════════════

from PIL import ImageGrab

from Action.executer import Executor
from Audio.ear import Ears
from Perception.perception import PerceptionManager
from Cognition.cortex import Cortex
from Interaction.voice import Voice


class MeiAgent:
    def __init__(self):
        print("\n" + "="*60)
        print("MEI AGENT - STARTING")
        print("="*60)
        
        WHISPER_PATH = r"C:\Users\Asus\Projects\Mei\models\whisper-model"
        QWEN_PATH = r"C:\Users\Asus\Projects\Mei\models\qwen2.5-3b-instruct-q4_k_m.gguf"
        
        self.work_dir = os.path.join(PROJECT_ROOT, "temp")
        os.makedirs(self.work_dir, exist_ok=True)
        
        print("\n[1/5] Voice...")
        self.voice = Voice()
        
        print("\n[2/5] Ears...")
        self.ears = Ears(WHISPER_PATH)
        
        print("\n[3/5] Eyes...")
        self.eyes = PerceptionManager(PROJECT_ROOT)
        
        print("\n[4/5] Brain...")
        self.brain = Cortex(QWEN_PATH)
        
        print("\n[5/5] Hands...")
        self.hands = Executor()
        
        print("\n" + "="*60)
        print("READY - Say a command or 'exit' to quit")
        print("="*60)
        self.voice.speak("Ready.")
    
    def run(self):
        while True:
            try:
                # ═══════════════════════════════════════════════════════════
                # LISTEN
                # ═══════════════════════════════════════════════════════════
                print("\n" + "="*50)
                print("[LISTEN] Waiting for command...")
                
                command = self.ears.listen()
                
                if not command:
                    continue
                
                print(f"[HEARD] '{command}'")
                
                # Exit check
                if any(w in command.lower() for w in ['exit', 'quit', 'stop', 'goodbye']):
                    self.voice.speak("Goodbye!")
                    break
                
                self.voice.speak("Working on it.")
                
                # ═══════════════════════════════════════════════════════════
                # SEE
                # ═══════════════════════════════════════════════════════════
                print("\n[SEE] Analyzing screen...")
                
                screenshot_path = os.path.join(self.work_dir, "screen.png")
                ImageGrab.grab().save(screenshot_path)
                
                elements, source, window = self.eyes.get_screen_state(screenshot_path)
                
                print(f"[SEE] Window: '{window}'")
                print(f"[SEE] Source: {source}")
                print(f"[SEE] Found: {len(elements)} elements")
                
                # DEBUG: Show first 10 elements
                print("[SEE] Sample elements:")
                for elem in elements[:10]:
                    print(f"      [{elem.get('index', '?'):3}] {str(elem.get('content', ''))[:30]}")
                
                if not elements:
                    self.voice.speak("I cannot see any elements.")
                    continue
                
                # ═══════════════════════════════════════════════════════════
                # THINK
                # ═══════════════════════════════════════════════════════════
                print(f"\n[THINK] Processing: '{command}'")
                
                indices = self.brain.think(command, elements, window)
                
                if not indices:
                    self.voice.speak("I couldn't figure out what to click.")
                    continue
                
                print(f"[THINK] Plan: {indices}")
                
                # Show what we're about to click
                for idx in indices:
                    if 0 <= idx < len(elements):
                        elem = elements[idx]
                        print(f"[THINK] Will click [{idx}]: '{elem.get('content', 'Unknown')}'")
                
                # ═══════════════════════════════════════════════════════════
                # ACT
                # ═══════════════════════════════════════════════════════════
                print(f"\n[ACT] Executing {len(indices)} click(s)...")
                
                for i, idx in enumerate(indices):
                    print(f"[ACT] Click {i+1}/{len(indices)}: Element {idx}")
                    
                    success = self.hands.perform_action(idx, elements)
                    
                    if not success:
                        self.voice.speak("Click failed.")
                        break
                    
                    # Wait between clicks
                    if i < len(indices) - 1:
                        time.sleep(0.4)
                
                self.voice.speak("Done.")
                
            except KeyboardInterrupt:
                print("\n[INTERRUPTED]")
                self.voice.speak("Stopping.")
                break
            except Exception as e:
                print(f"\n[ERROR] {e}")
                import traceback
                traceback.print_exc()


if __name__ == "__main__":
    agent = MeiAgent()
    agent.run()