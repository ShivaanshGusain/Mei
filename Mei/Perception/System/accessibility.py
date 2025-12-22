import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import uiautomation as auto
from ...core.config import ControlType, UIElement

class UIAutomationManager:
    """Manages UI Automation interactions."""
    
    def __init__(self):
        if auto is None:
            raise ImportError("uiautomation library not installed")
        
        self._search_timeout = 5.0

    def find_element(self, hwnd: int, name: str = None,
                     control_type: str = None, automation_id: str = None,
                     partial_match: bool = True) -> Optional[UIElement]:
        """Find single element matching criteria."""
        try:
            window = auto.ControlFromHandle(hwnd)
            if not window:
                return None
            
            # Special handling for edit controls
            if control_type and "Edit" in control_type:
                for try_type in ["EditControl", "DocumentControl"]:
                    element = self._find_by_type(window, try_type)
                    if element:
                        return self._build_ui_element(element, hwnd)
            
            if partial_match and name:
                element = self._find_by_partial_name(window, name, control_type)
            elif automation_id:
                element = self._find_by_automation_id(window, automation_id)
            elif control_type:
                element = self._find_by_type(window, control_type)
            else:
                element = self._find_exact(window, name, control_type)
            
            if element:
                return self._build_ui_element(element, hwnd)
            return None
            
        except Exception as e:
            print(f"[UIAutomation] Error finding element: {e}")
            return None

    def find_elements(self, hwnd: int, name: str = None,
                      control_type: str = None, max_depth: int = 10) -> List[UIElement]:
        """Find ALL elements matching criteria."""
        try:
            window = auto.ControlFromHandle(hwnd)
            if not window:
                return []
            
            results = []
            self._walk_tree(window, name, control_type, results, 0, max_depth, hwnd)
            return results
            
        except Exception as e:
            print(f"[UIAutomation] Error finding elements: {e}")
            return []

    def get_all_elements(self, hwnd: int, max_depth: int = 10) -> List[UIElement]:
        """Get ALL elements in a window (no filtering)."""
        try:
            window = auto.ControlFromHandle(hwnd)
            if not window:
                return []
            
            results = []
            self._collect_all(window, results, 0, max_depth, hwnd)
            return results
            
        except Exception as e:
            print(f"[UIAutomation] Error getting all elements: {e}")
            return []

    def get_element_at_point(self, x: int, y: int) -> Optional[UIElement]:
        """Get element at screen coordinates."""
        try:
            element = auto.ControlFromPoint(x, y)
            if element:
                hwnd = element.NativeWindowHandle or 0
                return self._build_ui_element(element, hwnd)
            return None
        except Exception as e:
            print(f"[UIAutomation] Error getting element at point: {e}")
            return None

    def get_focused_element(self) -> Optional[UIElement]:
        """Get currently focused element."""
        try:
            element = auto.GetFocusedControl()
            if element:
                hwnd = element.NativeWindowHandle or 0
                return self._build_ui_element(element, hwnd)
            return None
        except Exception as e:
            print(f"[UIAutomation] Error getting focused element: {e}")
            return None

    def click_element(self, element: UIElement, click_type: str = 'left') -> bool:
        """Click on an element."""
        if not element._control:
            return False
        
        # Try invoke pattern first
        try:
            invoke_pattern = element._control.GetInvokePattern()
            if invoke_pattern:
                invoke_pattern.Invoke()
                return True
        except:
            pass
        
        # Fallback to click at center
        try:
            x, y, w, h = element.bounding_box
            center_x = x + w // 2
            center_y = y + h // 2
            
            if click_type == 'left':
                auto.Click(center_x, center_y)
            elif click_type == 'right':
                auto.RightClick(center_x, center_y)
            elif click_type == 'double':
                auto.Click(center_x, center_y)
                time.sleep(0.05)
                auto.Click(center_x, center_y)
            
            return True
        except Exception as e:
            print(f"[UIAutomation] Error clicking element: {e}")
            return False

    def type_text(self, element: UIElement, text: str, clear_first: bool = False) -> bool:
        """Type text into an element."""
        try:
            # Focus the element first
            self.click_element(element)
            time.sleep(0.1)
            
            if clear_first:
                try:
                    value_pattern = element._control.GetValuePattern()
                    if value_pattern:
                        value_pattern.SetValue("")
                    else:
                        auto.SendKeys('{Ctrl}a{Delete}', interval=0.02)
                except:
                    auto.SendKeys('{Ctrl}a{Delete}', interval=0.02)
            
            # Try value pattern first
            try:
                value_pattern = element._control.GetValuePattern()
                if value_pattern:
                    value_pattern.SetValue(text)
                    return True
            except:
                pass
            
            # Fallback to SendKeys
            auto.SendKeys(text, interval=0.02)
            return True
            
        except Exception as e:
            print(f"[UIAutomation] Error typing text: {e}")
            return False

    def get_value(self, element: UIElement) -> Optional[str]:
        """Get current value/text of element."""
        if not element._control:
            return None
        
        try:
            value_pattern = element._control.GetValuePattern()
            if value_pattern:
                return value_pattern.Value
        except:
            pass
        
        try:
            text_pattern = element._control.GetTextPattern()
            if text_pattern:
                return text_pattern.DocumentRange.GetText(-1)
        except:
            pass
        
        try:
            return element._control.Name
        except:
            return None

    def set_value(self, element: UIElement, value: str) -> bool:
        """Set value directly."""
        try:
            value_pattern = element._control.GetValuePattern()
            if value_pattern:
                value_pattern.SetValue(value)
                return True
            return False
        except:
            return False

    def invoke(self, element: UIElement) -> bool:
        """Invoke element (click button, etc.)."""
        try:
            invoke_pattern = element._control.GetInvokePattern()
            if invoke_pattern:
                invoke_pattern.Invoke()
                return True
        except:
            pass
        return self.click_element(element)

    def expand(self, element: UIElement) -> bool:
        """Expand dropdown/menu/tree node."""
        try:
            pattern = element._control.GetExpandCollapsePattern()
            if pattern:
                pattern.Expand()
                return True
            return False
        except:
            return False

    def collapse(self, element: UIElement) -> bool:
        """Collapse dropdown/menu/tree node."""
        try:
            pattern = element._control.GetExpandCollapsePattern()
            if pattern:
                pattern.Collapse()
                return True
            return False
        except:
            return False

    def select_item(self, element: UIElement) -> bool:
        """Select list/tree item."""
        try:
            pattern = element._control.GetSelectionItemPattern()
            if pattern:
                pattern.Select()
                return True
        except:
            pass
        return self.click_element(element)

    def is_checked(self, element: UIElement) -> Optional[bool]:
        """Get checkbox/toggle state."""
        try:
            pattern = element._control.GetTogglePattern()
            if pattern:
                state = pattern.ToggleState
                return state == auto.ToggleState.On
            return None
        except:
            return None

    def toggle(self, element: UIElement) -> bool:
        """Toggle checkbox/toggle."""
        try:
            pattern = element._control.GetTogglePattern()
            if pattern:
                pattern.Toggle()
                return True
        except:
            pass
        return self.click_element(element)

    def scroll_to_element(self, element: UIElement) -> bool:
        """Scroll element into view."""
        try:
            pattern = element._control.GetScrollItemPattern()
            if pattern:
                pattern.ScrollIntoView()
                return True
            return False
        except:
            return False

    # ===== HELPER METHODS =====

    def _walk_tree(self, control, name: str, control_type: str,
                   results: List[UIElement], depth: int, max_depth: int, hwnd: int):
        """Recursively walk UI tree with filtering."""
        if depth > max_depth:
            return
        
        try:
            matches = True
            
            if name:
                ctrl_name = control.Name or ""
                if name.lower() not in ctrl_name.lower():
                    matches = False
            
            if control_type and matches:
                ctrl_type = control.ControlTypeName or ""
                if ctrl_type != control_type:
                    matches = False
            
            if matches and (name is not None or control_type is not None):
                results.append(self._build_ui_element(control, hwnd, depth))
            
            # Always recurse into children
            child = control.GetFirstChildControl()
            while child:
                self._walk_tree(child, name, control_type, results, depth + 1, max_depth, hwnd)
                child = child.GetNextSiblingControl()
                
        except:
            pass

    def _collect_all(self, control, results: List[UIElement], depth: int, max_depth: int, hwnd: int):
        """Collect ALL elements without filtering."""
        if depth > max_depth:
            return
        
        try:
            results.append(self._build_ui_element(control, hwnd, depth))
            
            child = control.GetFirstChildControl()
            while child:
                self._collect_all(child, results, depth + 1, max_depth, hwnd)
                child = child.GetNextSiblingControl()
        except:
            pass

    def _build_ui_element(self, control, hwnd: int, depth: int = 0) -> UIElement:
        """Build UIElement from uiautomation control."""
        try:
            name = control.Name or ""
        except:
            name = ""
        
        try:
            control_type = control.ControlTypeName or ""
        except:
            control_type = ""
        
        try:
            automation_id = control.AutomationId or ""
        except:
            automation_id = ""
        
        try:
            class_name = control.ClassName or ""
        except:
            class_name = ""
        
        try:
            rect = control.BoundingRectangle
            bounding_box = (rect.left, rect.top, rect.width(), rect.height())
        except:
            bounding_box = (0, 0, 0, 0)
        
        try:
            is_enabled = control.IsEnabled
        except:
            is_enabled = False
        
        try:
            is_visible = not control.IsOffscreen
        except:
            is_visible = True
        
        try:
            is_focused = control.HasKeyboardFocus
        except:
            is_focused = False
        
        try:
            value_pattern = control.GetValuePattern()
            value = value_pattern.Value if value_pattern else None
        except:
            value = None
        
        return UIElement(
            name=name,
            control_type=control_type,
            automation_id=automation_id,
            class_name=class_name,
            value=value,
            is_enabled=is_enabled,
            is_visible=is_visible,
            is_focused=is_focused,
            bounding_box=bounding_box,
            hwnd=hwnd,
            depth=depth,
            _control=control
        )

    def _find_by_partial_name(self, window, name: str, control_type: str = None):
        """Find element with partial name match."""
        name_lower = name.lower()
        
        def search(control):
            try:
                ctrl_name = control.Name or ""
                if name_lower in ctrl_name.lower():
                    if control_type:
                        if control.ControlTypeName == control_type:
                            return control
                    else:
                        return control
            except:
                pass
            
            try:
                child = control.GetFirstChildControl()
                while child:
                    result = search(child)
                    if result:
                        return result
                    child = child.GetNextSiblingControl()
            except:
                pass
            
            return None
        
        return search(window)

    def _find_by_automation_id(self, window, automation_id: str):
        """Find element by automation ID."""
        def search(control):
            try:
                if control.AutomationId == automation_id:
                    return control
            except:
                pass
            
            try:
                child = control.GetFirstChildControl()
                while child:
                    result = search(child)
                    if result:
                        return result
                    child = child.GetNextSiblingControl()
            except:
                pass
            
            return None
        
        return search(window)

    def _find_by_type(self, window, control_type: str):
        """Find first element of given type."""
        def search(control):
            try:
                if control.ControlTypeName == control_type:
                    return control
            except:
                pass
            
            try:
                child = control.GetFirstChildControl()
                while child:
                    result = search(child)
                    if result:
                        return result
                    child = child.GetNextSiblingControl()
            except:
                pass
            
            return None
        
        return search(window)

    def _find_exact(self, window, name: str = None, control_type: str = None):
        """Find element with exact match."""
        def search(control):
            try:
                matches = True
                
                if name:
                    if control.Name != name:
                        matches = False
                
                if control_type and matches:
                    if control.ControlTypeName != control_type:
                        matches = False
                
                if matches and (name or control_type):
                    return control
            except:
                pass
            
            try:
                child = control.GetFirstChildControl()
                while child:
                    result = search(child)
                    if result:
                        return result
                    child = child.GetNextSiblingControl()
            except:
                pass
            
            return None
        
        return search(window)


# ===== TEST BLOCK =====
if __name__ == "__main__":
    import win32gui
    
    ui = UIAutomationManager()
    
    print("=" * 50)
    print("UI AUTOMATION TEST")
    print("Open Calculator and Notepad for testing")
    print("=" * 50)
    
    time.sleep(2)
    
    # Test 1: Focused element
    print("\nTEST 1: Get Focused Element")
    print("-" * 30)
    focused = ui.get_focused_element()
    if focused:
        print(f"  Name: {focused.name}")
        print(f"  Type: {focused.control_type}")
    
    # Test 2: Calculator
    print("\nTEST 2: Find Calculator Buttons")
    print("-" * 30)
    calc_hwnd = win32gui.FindWindow(None, "Calculator")
    if calc_hwnd:
        print(f"  Calculator HWND: {calc_hwnd}")
        
        # Get ALL elements first
        all_elements = ui.get_all_elements(calc_hwnd, max_depth=15)
        print(f"  Total elements: {len(all_elements)}")
        
        # Filter buttons
        buttons = [e for e in all_elements if "Button" in e.control_type]
        print(f"  Buttons found: {len(buttons)}")
        for btn in buttons[:10]:
            print(f"    - '{btn.name}' ({btn.control_type})")
        
        # Click button 7
        btn_7 = ui.find_element(calc_hwnd, name="Seven")
        if btn_7:
            print(f"\n  Clicking: {btn_7.name}")
            ui.click_element(btn_7)
    else:
        print("  Calculator not open")
    
    # Test 3: Notepad
    print("\nTEST 3: Type in Notepad")
    print("-" * 30)
    notepad_hwnd = win32gui.FindWindow("Notepad", None)
    if notepad_hwnd:
        print(f"  Notepad HWND: {notepad_hwnd}")
        
        # Get all elements to see structure
        all_elements = ui.get_all_elements(notepad_hwnd, max_depth=10)
        print(f"  Total elements: {len(all_elements)}")
        
        # Show types found
        types = set(e.control_type for e in all_elements)
        print(f"  Control types: {types}")
        
        # Find any editable control
        edit = ui.find_element(notepad_hwnd, control_type="EditControl")
        if not edit:
            edit = ui.find_element(notepad_hwnd, control_type="DocumentControl")
        if not edit:
            # Try RichEdit
            for elem in all_elements:
                if "Edit" in elem.control_type or "Document" in elem.control_type:
                    edit = elem
                    break
        
        if edit:
            print(f"  Found: {edit.control_type}")
            print("  Typing...")
            ui.type_text(edit, "Hello from MEI!", clear_first=True)
        else:
            print("  No edit control found")
            print("  Available controls:")
            for e in all_elements[:15]:
                print(f"    {e.control_type}: '{e.name[:30] if e.name else ''}'")
    else:
        print("  Notepad not open")
    
    print("\n" + "=" * 50)
    print("Test complete!")