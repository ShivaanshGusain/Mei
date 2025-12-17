import os
os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"

import sys
import time
current_dir = os.path.dirname(os.path.abspath(__file__))
visual_dir = os.path.join(current_dir,'Visual')
if visual_dir not in sys.path:
    sys.path.append(visual_dir)
from Perception.System.Symbolic import SystemEye
from Perception.Visual.element_detector import VisualEye
class PerceptionManager:
    def __init__(self, project_root):
        self.fast_eye = SystemEye()
        self.slow_eye = VisualEye(project_root)

    def get_screen_state(self, screenshot_path):
        # 1. Get Symbolic Data + Window Name
        symbolic_data = self.fast_eye.scan_active_window() # This returns a LIST right now
        
        # We need to extract the window name from the fast eye. 
        # Update your scan_active_window in Symbolic.py to return a dict 
        # OR just grab it here quickly:
        import uiautomation as auto
        current_window_name = auto.GetForegroundControl().Name

        if len(symbolic_data) > 5:
            print(f"[Perception] Symbolic Scan: {len(symbolic_data)} items in '{current_window_name}'.")
            return symbolic_data, "symbolic", current_window_name
            
        else:
            print("[Perception] Switching to Visual...")
            # Vision doesn't know window names, so we just pass "Visual View"
            visual_elements, debug_path = self.slow_eye.inspect_screen(screenshot_path)
            return visual_elements, "visual", current_window_name      
          
if __name__ == "__main__":
    ROOT = os.path.dirname(os.path.abspath(__file__))
    
    manager = PerceptionManager(r"C:\Users\Asus\Projects\Mei\Mei") 
    time.sleep(3)
    
    print("\n--- STARTING FUSION TEST ---")
    elements, source = manager.get_screen_state(r"C:\Users\Asus\Projects\Mei\Mei\Perception\Visual\test_screenshot.png")
    
    print(f"\nFINAL DECISION: Used {source} source.")
    print(f"Found {len(elements)} elements.")   