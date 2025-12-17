import os
os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"

import uiautomation as auto

class SystemEye:
    def __init__(self):
        print("[System-Eye] Connecting to Windows API...")
        auto.SetGlobalSearchTimeout(1)
        print("[System-Eye] Online.")

    def _get_all_descendants(self, control, max_depth, current_depth=0):
        if current_depth >= max_depth:
            return []
        
        descendants = []
        children = control.GetChildren()
        
        for child in children:
            descendants.append(child)
            descendants.extend(self._get_all_descendants(child, max_depth, current_depth + 1))
            
        return descendants

    def scan_active_window(self):
        active_window = auto.GetForegroundControl()
        if not active_window:
            return []

        print(f"[System-Eye] Scanning: {active_window.Name}")
        elements = []
        all_controls = self._get_all_descendants(active_window, max_depth=5)

        for control in all_controls:
            try:
                c_type = control.ControlTypeName
                if c_type in ["ButtonControl", "EditControl", "HyperlinkControl", "ListItemControl"]:
                    if not control.IsOffscreen and control.Name:
                        element_data = {
                            "type": c_type,
                            "content": control.Name,
                            "bbox": control.BoundingRectangle,
                            "source": "symbolic"
                        }
                        elements.append(element_data)
            except:
                continue
        
        return elements