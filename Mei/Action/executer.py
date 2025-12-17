import uiautomation as auto
import time

class Executor:
    def __init__(self):
        print("Executor is online")
        root = auto.GetRootControl()
        self.screen_w = root.BoundingRectangle.width()
        self.screen_h = root.BoundingRectangle.height()
        print(f'Calibrated to screen size: {self.screen_w}x{self.screen_h}')

    def get_center(self, bbox):
        left, top, right, bottom = 0,0,0,0
        # If it is from Symbolic
        if hasattr(bbox, 'left'):
            left = bbox.left
            top = bbox.top
            right = bbox.right
            bottom = bbox.bottom

        # If its from Visual
        elif isinstance(bbox,(list, tuple)):
            left, top, right, bottom = bbox

            if right <= 1.5 and bottom <= 1.5:
                left = int(left*self.screen_w)
                right = int(right*self.screen_w)
                top = int(top*self.screen_h)
                bottom = int(bottom*self.screen_h)

        center_x = (left + right)//2
        center_y = (top + bottom)//2
        return center_x, center_y
    def perform_action(self, element_index, ui_element):
        try:
            index = int(element_index)
            if index<0 or index >= len(ui_element):
                print(f"Index {index} is out of range")
                return False
            target = ui_element[index]
            print(f"Targeting '{target.get('content', 'Unknown')}'")
            x,y = self.get_center(target['bbox'])
            print(f"Clicking at {x},{y}")

            auto.SetCursorPos(x,y)
            time.sleep(0.1)
            auto.Click(x,y)
            auto.SetCursorPos(0,0)
            return True
        except Exception as e:
            print(f"Fail: {e}")
            return False
        
if __name__ == "__main__":
    hand = Executor()
    
    print("\n--- TEST: SYMBOLIC (RECT) ---")
    print("Hover over a window/button to capture it...")
    time.sleep(2)
    
    # Capture real symbolic data (Rect Object)
    control = auto.ControlFromCursor()
    rect_bbox = control.BoundingRectangle
    print(f"Captured: {control.Name}")
    
    # Test 1: Clicking via Rect Object
    hand.perform_action("0", [{"content": control.Name, "bbox": rect_bbox}])
    
    print("\n--- TEST: VISUAL (RATIO) ---")
    print("Simulating a Vision Model click on the center of the screen...")
    time.sleep(1)
    
    # Test 2: Clicking via Ratio List (0.5 = Center)
    # This should click exactly in the middle of your monitor
    fake_vision_data = [{"content": "Center Screen", "bbox": [0.45, 0.45, 0.55, 0.55]}]
    hand.perform_action("0", fake_vision_data)