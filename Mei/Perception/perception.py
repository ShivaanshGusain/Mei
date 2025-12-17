# Perception/perception.py
"""
PerceptionManager - Coordinates between Symbolic (fast) and Visual (slow) perception.
Prefers Symbolic when possible, falls back to Visual.
"""

import os
import sys

# Suppress warnings
os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"

# Get the directory where THIS file is located
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)  # Go up one level to Mei/

# Add paths for imports
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import uiautomation as auto

# Import from our own modules using relative imports based on folder structure
from Perception.System.Symbolic import SystemEye

# Visual import might fail if OmniParser weights are missing - that's OK
try:
    from Perception.Visual.element_detector import VisualEye
    VISUAL_AVAILABLE = True
except ImportError as e:
    print(f"[Perception] WARNING: Visual perception not available: {e}")
    VISUAL_AVAILABLE = False
except Exception as e:
    print(f"[Perception] WARNING: Visual perception error: {e}")
    VISUAL_AVAILABLE = False


class PerceptionManager:
    """
    Manages perception by choosing between Symbolic (fast/reliable) 
    and Visual (slow/fallback) methods.
    """
    
    def __init__(self, project_root=None):
        print("[Perception] Initializing Perception Manager...")
        
        # Initialize Symbolic (Accessibility API) - always available
        self.symbolic_eye = SystemEye()
        self.has_symbolic = True
        
        # Initialize Visual (OmniParser) - may fail if weights missing
        self.visual_eye = None
        self.has_visual = False
        
        if VISUAL_AVAILABLE:
            try:
                self.visual_eye = VisualEye(project_root)
                self.has_visual = True
                print("[Perception] Visual perception: ENABLED")
            except Exception as e:
                print(f"[Perception] Visual perception: DISABLED ({e})")
        else:
            print("[Perception] Visual perception: DISABLED (import failed)")
        
        # Threshold: if symbolic finds fewer than this many interactive elements, try visual
        self.min_symbolic_elements = 5
        
        print("[Perception] Online.")
    
    def get_screen_state(self, screenshot_path=None):
        """
        Get current screen state using best available method.
        
        Args:
            screenshot_path: Path to screenshot (needed for visual fallback)
        
        Returns:
            tuple: (elements, source, window_title)
        """
        
        # Get active window title
        window_title = self.symbolic_eye.get_window_title()
        
        # Try Symbolic first (fast and reliable)
        print("[Perception] Running Symbolic scan...")
        symbolic_elements = self.symbolic_eye.scan_active_window()
        
        # Count interactive elements
        interactive_count = sum(1 for e in symbolic_elements if e.get('interactivity', False))
        print(f"[Perception] Symbolic found {len(symbolic_elements)} elements ({interactive_count} interactive)")
        
        # If we have enough interactive elements, use Symbolic
        if interactive_count >= self.min_symbolic_elements:
            return symbolic_elements, "symbolic", window_title
        
        # Fallback to Visual if available
        if self.has_visual and screenshot_path and os.path.exists(screenshot_path):
            print("[Perception] Symbolic results sparse, trying Visual...")
            visual_elements, debug_path = self.visual_eye.inspect_screen(screenshot_path)
            
            if visual_elements and len(visual_elements) > len(symbolic_elements):
                print(f"[Perception] Using Visual: {len(visual_elements)} elements")
                return visual_elements, "visual", window_title
        
        # Return symbolic results even if sparse
        print(f"[Perception] Using Symbolic (sparse): {len(symbolic_elements)} elements")
        return symbolic_elements, "symbolic", window_title


# ══════════════════════════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import time
    from PIL import ImageGrab
    
    print("\n" + "="*60)
    print("PERCEPTION MANAGER TEST")
    print("="*60)
    
    # Take a screenshot
    screenshot_path = os.path.join(CURRENT_DIR, "test_perception.png")
    print(f"\nSaving screenshot to: {screenshot_path}")
    
    screenshot = ImageGrab.grab()
    screenshot.save(screenshot_path)
    
    print("\nFocus a window in 3 seconds...")
    time.sleep(3)
    
    # Initialize and test
    manager = PerceptionManager(PROJECT_ROOT)
    
    elements, source, window = manager.get_screen_state(screenshot_path)
    
    print(f"\n{'='*60}")
    print(f"Window: {window}")
    print(f"Source: {source}")
    print(f"Elements: {len(elements)}")
    print(f"{'='*60}")
    
    for elem in elements[:15]:
        content = str(elem.get('content', ''))[:40]
        print(f"[{elem.get('index', '?'):2}] {str(elem.get('type', '?'))[:10]:10s} | {content}")