# Action/executer.py
"""
Executor - Performs physical actions (clicks) on UI elements.
Handles both Symbolic (pixel coordinates) and Visual (ratio coordinates).
"""

import os
import sys
import time
import ctypes

os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"

import uiautomation as auto


class Executor:
    """
    Executes actions on UI elements.
    Handles coordinate conversion for both Symbolic and Visual sources.
    """
    
    def __init__(self):
        print("[Executor] Initializing...")
        
        # Get screen dimensions
        user32 = ctypes.windll.user32
        
        # Primary monitor dimensions
        self.screen_width = user32.GetSystemMetrics(0)   # SM_CXSCREEN
        self.screen_height = user32.GetSystemMetrics(1)  # SM_CYSCREEN
        
        print(f"[Executor] Screen: {self.screen_width}x{self.screen_height}")
        print("[Executor] Online.")
    
    def get_center(self, bbox, source='symbolic'):
        """
        Calculate center point of a bounding box.
        
        Args:
            bbox: Bounding box (Rect object or [x1, y1, x2, y2] list)
            source: 'symbolic' or 'visual'
        
        Returns:
            tuple: (center_x, center_y) in screen pixels
        """
        
        # Handle None
        if bbox is None:
            print("[Executor] ERROR: bbox is None")
            return None, None
        
        # Handle Symbolic source (uiautomation Rect object)
        if hasattr(bbox, 'left') and hasattr(bbox, 'top'):
            left = bbox.left
            top = bbox.top
            right = bbox.right
            bottom = bbox.bottom
            
            center_x = (left + right) // 2
            center_y = (top + bottom) // 2
            
            print(f"[Executor] Symbolic bbox: ({left}, {top}, {right}, {bottom}) -> center ({center_x}, {center_y})")
            return center_x, center_y
        
        # Handle Visual source (list/tuple of coordinates)
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
            
            # Check if coordinates are ratios (0-1) or pixels
            if all(0 <= v <= 1.0 for v in [x1, y1, x2, y2]):
                # Convert ratios to pixels
                left = int(x1 * self.screen_width)
                top = int(y1 * self.screen_height)
                right = int(x2 * self.screen_width)
                bottom = int(y2 * self.screen_height)
                print(f"[Executor] Visual bbox (ratios): ({x1:.3f}, {y1:.3f}, {x2:.3f}, {y2:.3f})")
            else:
                # Already in pixels
                left, top, right, bottom = int(x1), int(y1), int(x2), int(y2)
                print(f"[Executor] Visual bbox (pixels): ({left}, {top}, {right}, {bottom})")
            
            center_x = (left + right) // 2
            center_y = (top + bottom) // 2
            
            print(f"[Executor] Center: ({center_x}, {center_y})")
            return center_x, center_y
        
        print(f"[Executor] ERROR: Unknown bbox format: {type(bbox)} = {bbox}")
        return None, None
    
    def perform_action(self, element_index, ui_elements, action='click'):
        """
        Perform an action on a UI element.
        
        Args:
            element_index: Index of element in ui_elements list
            ui_elements: List of UI element dicts
            action: 'click'
        
        Returns:
            bool: Success or failure
        """
        try:
            # Validate index
            index = int(element_index)
            if index < 0 or index >= len(ui_elements):
                print(f"[Executor] ERROR: Index {index} out of range (0-{len(ui_elements)-1})")
                return False
            
            # Get target element
            target = ui_elements[index]
            content = target.get('content', 'Unknown')
            source = target.get('source', 'symbolic')
            bbox = target.get('bbox')
            
            print(f"[Executor] Target [{index}]: '{content}' (source: {source})")
            
            if bbox is None:
                print(f"[Executor] ERROR: No bbox for element {index}")
                return False
            
            # Get click coordinates
            x, y = self.get_center(bbox, source)
            
            if x is None or y is None:
                print(f"[Executor] ERROR: Could not calculate center")
                return False
            
            # Perform the action
            if action == 'click':
                return self._click(x, y)
            else:
                print(f"[Executor] ERROR: Unknown action: {action}")
                return False
            
        except Exception as e:
            print(f"[Executor] ERROR: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _click(self, x, y):
        """Perform a mouse click at coordinates."""
        try:
            print(f"[Executor] Clicking at ({x}, {y})...")
            
            # Move cursor
            auto.SetCursorPos(x, y)
            time.sleep(0.05)
            
            # Click
            auto.Click(x, y)
            
            print(f"[Executor] Click successful!")
            return True
            
        except Exception as e:
            print(f"[Executor] Click failed: {e}")
            return False


# ══════════════════════════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "="*60)
    print("EXECUTOR TEST")
    print("="*60)
    
    hand = Executor()
    
    # Test 1: Symbolic coordinates
    print("\n--- TEST 1: SYMBOLIC ---")
    print("Hover over a button/element, then this will click it in 3 seconds...")
    time.sleep(3)
    
    control = auto.ControlFromCursor()
    if control:
        rect = control.BoundingRectangle
        print(f"Found: '{control.Name}' at {rect}")
        
        test_symbolic = [{
            'index': 0,
            'content': control.Name,
            'type': 'Test',
            'bbox': rect,
            'source': 'symbolic'
        }]
        
        print("Clicking in 2 seconds...")
        time.sleep(2)
        hand.perform_action(0, test_symbolic)
    
    # Test 2: Visual coordinates (ratios)
    print("\n--- TEST 2: VISUAL (ratios) ---")
    print("Clicking center of screen in 2 seconds...")
    time.sleep(2)
    
    test_visual = [{
        'index': 0,
        'content': 'Screen Center',
        'type': 'Test',
        'bbox': [0.48, 0.48, 0.52, 0.52],  # Center area
        'source': 'visual'
    }]
    
    hand.perform_action(0, test_visual)
    
    print("\n--- TESTS COMPLETE ---")