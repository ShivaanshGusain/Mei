# Perception/System/Symbolic.py
"""
SystemEye - Uses Windows Accessibility API to scan UI elements.
This is FAST and RELIABLE - prefer this over visual scanning.
"""

import os
import sys

# Suppress warnings
os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"

import uiautomation as auto
import time


class SystemEye:
    """
    Scans the active window using Windows UI Automation API.
    Returns structured data about all interactive elements.
    """
    
    def __init__(self):
        print("[SystemEye] Initializing Windows UI Automation...")
        self.timeout = 3  # seconds
        auto.SetGlobalSearchTimeout(self.timeout)
        print("[SystemEye] Online.")
    
    def scan_active_window(self):
        """
        Scan the currently focused window and return all interactive elements.
        
        Returns:
            List[dict]: List of UI elements with format:
                {
                    'index': int,
                    'content': str,
                    'type': str,
                    'bbox': Rect object,
                    'interactivity': bool,
                    'source': 'symbolic'
                }
        """
        elements = []
        
        try:
            # Get the foreground (active) window
            active_window = auto.GetForegroundControl()
            
            if not active_window:
                print("[SystemEye] No active window found.")
                return elements
            
            window_name = active_window.Name
            print(f"[SystemEye] Scanning window: '{window_name}'")
            
            # Define which control types are interactive (clickable)
            interactive_types = {
                auto.ControlType.ButtonControl,
                auto.ControlType.CheckBoxControl,
                auto.ControlType.ComboBoxControl,
                auto.ControlType.EditControl,
                auto.ControlType.HyperlinkControl,
                auto.ControlType.ListItemControl,
                auto.ControlType.MenuItemControl,
                auto.ControlType.RadioButtonControl,
                auto.ControlType.TabItemControl,
                auto.ControlType.TreeItemControl,
                auto.ControlType.SliderControl,
                auto.ControlType.SpinnerControl,
                auto.ControlType.SplitButtonControl,
            }
            
            # Also include these if they have names
            semi_interactive = {
                auto.ControlType.TextControl,
                auto.ControlType.ImageControl,
                auto.ControlType.ListControl,
                auto.ControlType.TreeControl,
                auto.ControlType.TableControl,
                auto.ControlType.DataItemControl,
            }
            
            # Recursively scan all descendants
            index = 0
            
            def scan_control(control, depth=0):
                nonlocal index
                
                if depth > 15:  # Prevent infinite recursion
                    return
                
                try:
                    # Get control properties
                    ctrl_type = control.ControlType
                    name = control.Name or ""
                    
                    # Get bounding rectangle
                    try:
                        bbox = control.BoundingRectangle
                        # Skip elements with no size or off-screen
                        if bbox.width() <= 0 or bbox.height() <= 0:
                            # Still scan children
                            for child in control.GetChildren():
                                scan_control(child, depth + 1)
                            return
                        if bbox.left < -10000 or bbox.top < -10000:
                            # Off-screen, skip but scan children
                            for child in control.GetChildren():
                                scan_control(child, depth + 1)
                            return
                    except:
                        # Still scan children even if bbox fails
                        for child in control.GetChildren():
                            scan_control(child, depth + 1)
                        return
                    
                    # Determine if interactive
                    is_interactive = ctrl_type in interactive_types
                    
                    # Include semi-interactive if they have meaningful names
                    if ctrl_type in semi_interactive and len(name) > 0:
                        is_interactive = True
                    
                    # Get control type name
                    type_name = str(ctrl_type).replace('ControlType.', '').replace('Control', '')
                    
                    # Skip unnamed non-interactive elements (but still scan children)
                    if name or is_interactive:
                        element = {
                            'index': index,
                            'content': name if name else f"[{type_name}]",
                            'type': type_name,
                            'bbox': bbox,
                            'interactivity': is_interactive,
                            'source': 'symbolic'
                        }
                        elements.append(element)
                        index += 1
                    
                    # Scan children
                    for child in control.GetChildren():
                        scan_control(child, depth + 1)
                        
                except Exception as e:
                    pass  # Skip problematic controls
            
            # Start scanning from the active window
            scan_control(active_window)
            
            print(f"[SystemEye] Found {len(elements)} elements.")
            
        except Exception as e:
            print(f"[SystemEye] Error during scan: {e}")
        
        return elements
    
    def get_window_title(self):
        """Get the title of the active window."""
        try:
            window = auto.GetForegroundControl()
            return window.Name if window else "Unknown"
        except:
            return "Unknown"


# ══════════════════════════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "="*60)
    print("SYSTEM EYE TEST")
    print("="*60)
    
    print("\nFocus a window in 3 seconds...")
    time.sleep(3)
    
    eye = SystemEye()
    elements = eye.scan_active_window()
    
    print(f"\n{'='*60}")
    print(f"FOUND {len(elements)} ELEMENTS:")
    print(f"{'='*60}")
    
    for elem in elements[:25]:  # Show first 25
        content_short = str(elem['content'])[:35]
        print(f"[{elem['index']:2d}] {elem['type']:12s} | {content_short}")
    
    if len(elements) > 25:
        print(f"... and {len(elements) - 25} more")