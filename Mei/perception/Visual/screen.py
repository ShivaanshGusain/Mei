from ...core.config import get_config, MonitorInfo, Screenshot, UIElement, ScreenDiff
from ...core.events import emit, EventType
from typing import List,Optional, Tuple
import mss, os, ctypes
from datetime import datetime
from PIL import Image
import win32gui, win32con, win32ui, win32api 
import time, numpy as np

class ScreenCapture:
    def __init__(self):
        self.config = get_config()
        self._sct = mss.mss()
        self._monitors:List[MonitorInfo] = []
        self._refresh_monitors()
        os.makedirs(self.config.visual.screenshot_cache_dir, exist_ok= True)

    def _refresh_monitors(self)->None:
        self._monitors = []
        for i, mon in enumerate(self._sct.monitors[1:], start=0):
            monitor_info = MonitorInfo(
                index=i,
                x = mon['left'],
                y = mon['top'],
                width =mon['width'],
                height = mon['height'],
                is_primary=(i==0),
                scale_factor=self._get_dpi_scale(i)
            )
            self._monitors.append(monitor_info)
        emit(event_type= EventType.MONITOR_REFRESHED, source="ScreenCapture")
    
    def _get_dpi_scale(self, monitor_index: int)->float:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except:
            pass
        user32 = ctypes.windll.user32
        dpi = user32.GetDpiForSystem()
        return dpi/96.0
    
    def get_monitors(self)->List[MonitorInfo]:
        self._refresh_monitors()
        return list(self._monitors)
    
    def get_primary_monitor(self)->Optional[MonitorInfo]:
        for monitor in self._monitors:
            if monitor.is_primary:            
                return monitor
        return self._monitors[0] if self._monitors else None
    
    def capture_full_screen(self, monitor_index:int = None)-> Optional[Screenshot]:
        try:
            if monitor_index is None:
                mss_index = 0
            else:
                mss_index = monitor_index +1 
            monitor = self._sct.monitors[mss_index]
            sct_img = self._sct.grab(monitor)

            img = Image.frombytes('RGB', (sct_img.width,sct_img.height), sct_img.rgb)
            
            S =  Screenshot(
                image=img,
                timestamp=datetime.now(),
                region=(monitor['left'],monitor['top'],monitor['width'],monitor['height']),
                source="screen",
                source_hwnd=None,
                monitor_index=monitor_index
            )
            emit(event_type=EventType.MONITOR_SCREENSHOT, source="ScreenCapture", screenshot = S)
            return S
        except:
            emit(event_type=EventType.ERROR, source="ScreenCapture")

    def capture_region(self,x:int, y:int,width:int, height:int)->Optional[Screenshot]:
        try:
            region = {
                'left':x,
                'top':y,
                'width':width,
                'height':height
            }
            sct_image = self._sct.grab(region)
            img = Image.frombytes("RGB",(sct_image.width, sct_image.height),sct_image.rgb)
            S = Screenshot(
                image=img,
                timestamp=datetime.now(),
                region=(x,y,width,height),
                source='region',
                source_hwnd= None,
                monitor_index=None
            )
            emit(EventType.REGION_SCREENSHOT, source="ScreenCapture", screenshot = S)
            return S
        except:
            emit(event_type=EventType.ERROR, source="ScreenCapture")

    def capture_window(self,hwnd:int, include_border:bool = True, bring_to_front:bool = False)->Optional[Screenshot]:
        try:
            if win32gui.IsIconic(hwnd):
                return self._capture_minimized_window(hwnd)
            if bring_to_front:
                win32gui.ShowWindow(hwnd,win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.1)
                
            if include_border:
                rect = win32gui.GetWindowRect(hwnd)
            else:
                client_rect = win32gui.GetClientRect(hwnd)
                left,top = win32gui.ClientToScreen(hwnd,(0,0))
                rect = (left, top, left + client_rect[2], top + client_rect[3])
            x,y,x2,y2 = rect
            width = x2-x
            height = y2-y

            if width <=0 or height <=0:
                return None
            screenshot = self.capture_region(x,y,width,height)
            screenshot.source = "window"
            screenshot.source_hwnd = hwnd
            emit(EventType.WINDOW_CAPTURED, source="ScreenCapture", screenshot = screenshot)
            return screenshot
        except:
            emit(event_type=EventType.ERROR, source='ScreenCapture')
            
    def _capture_minimized_window(self, hwnd:int)->Optional[Screenshot]:
        try:
            rect = win32gui.GetWindowRect(hwnd)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
            if width <=0 or height <=0:
                return None
            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()

            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, width,height)
            save_dc.SelectObject(bitmap)
            
            PW_RENDERFULLCONTENT  = 2
            result = ctypes.windll.user32.PrintWindow(
                hwnd, save_dc.GetSafeHdc(),PW_RENDERFULLCONTENT
            )
            bmp_info = bitmap.GetInfo()
            bmp_bits = bitmap.GetBitmapBits(True)
            
            img = Image.frombuffer(
                'RGB', (bmp_info['bmWidth'], bmp_info['bmHeight']), bmp_bits,'raw','BGRX', 0,1
            )
            win32gui.DeleteObject(bitmap.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)
            S =  Screenshot(image=img,
                            timestamp= datetime.now(),
                            region=(rect[0], rect[1], width, height),
                            source='window',
                            source_hwnd=hwnd,
                            monitor_index=None
            )
            emit(EventType.WINDOW_CAPTURED, source="ScreenCapture", screenshot = S)
            return S
        except:
            emit(event_type=EventType.ERROR, source="ScreenCapture")

    def capture_element(self, element:UIElement, padding: int = 0)->Optional[Screenshot]:
        x, y, w, h = element.bounding_box
        x = max(0,x-padding)
        y = max(0, y - padding)
        w = w + (padding * 2) 
        h = h + (padding * 2) 
        return self.capture_region(x,y,w,h)
    
    def capture_around_cursor(self, width:int = 100, height:int = 100)->Screenshot:
        cursor_x, cursor_y = win32api.GetCursorPos()
        x = cursor_x - (width//2)
        y = cursor_y - (height//2)

        x = max(0,x)
        y = max(0,y)
        return self.capture_region(x,y,width, height)
    
    def capture_active_window(self)->Optional[Screenshot]:
        hwnd = win32gui.GetForegroundWindow()
        if hwnd:
            return self.capture_window(hwnd)
        return None
    
    def compare_screenshots(self, before:Screenshot,after:Screenshot, threshold:float = 0.95)->Optional[ScreenDiff]:
        try:
            img_before = before.image
            img_after = after.image
            if img_before.size != img_after.size:
                img_after = img_after.resize(img_before.size)

            arr_before = np.array(img_before)
            arr_after = np.array(img_after)
            diff = np.abs(arr_before.astype(np.int16)-arr_after.astype(np.int16))
            diff_sum = np.sum(diff, axis = 2)
            changed_mask = diff_sum >30
            changed_regions = self._find_changed_regions(changed_mask)
            
            total_pixels = arr_before.shape[0] * arr_before.shape[1] 
            changed_pixels = np.sum(changed_mask)
            similarity = 1.0-(changed_pixels/total_pixels)

            S = ScreenDiff(
                changed_regions=changed_regions,
                similarity_score=similarity,
                has_significant_change=(similarity<threshold)
            )
            emit(event_type=EventType.SCREENSHOT_COMPARED, source="ScreenCapture", data = S)
            return S
        except:
            emit(event_type=EventType.ERROR, source="ScreenCapture")
    
    
    def _find_changed_regions(self,mask:np.ndarray)->List[Tuple[int,int,int,int]]:
        rows,cols = np.where(mask)
        if len(rows) == 0:
            return []
        min_row, max_row = rows.min(), rows.max()
        min_col, max_col = cols.min(), cols.max()
        return [(min_col, min_row, max_col-min_col, max_row-min_row)]
    
    def save_screenshot(self, screenshot:Screenshot, path:str = None)->Optional[str]:
        try:
            if path == None:
                timestamp_str = screenshot.timestamp.strftime("%Y%m%d_%H%M%S_%f")
                filename = f'screenshot_{timestamp_str}.png'
                path = os.path.join(self.config.visual.screenshot_cache_dir, filename)
            
            os.makedirs(os.path.dirname(path), exist_ok = True)
            screenshot.image.save(path, format='PNG')
            emit(event_type=EventType.SCREENSHOT_SAVED, source="ScreenCapture", data = path)
            return path
        except:
            emit(event_type=EventType.ERROR, source="ScreenCapture")

    def load_screenshot(self, path:str)->Optional[Screenshot]:
        if not os.path.exists(path):
            return None
        img = Image.open(path)
        mtime = os.path.getmtime(path)
        timestamp = datetime.fromtimestamp(mtime)
        return Screenshot(
            image = img,
            timestamp=timestamp,
            region=(0,0,img.width, img.height),
            source='file',
            source_hwnd=None,
            monitor_index= None
        )
    
    def cleanup_cache(self, max_age_hours:int = 24)->int:
        now = datetime.now()
        max_age_seconds = max_age_hours*3600
        delete_count = 0
        cache_dir = self.config.visual.screenshot_cache_dir
        for filename in os.listdir(cache_dir):
            filepath = os.path.join(cache_dir, filename)
            if not os.path.isfile(filepath):
                continue
            mtime = os.path.getmtime(filepath)
            age_seconds = (now- datetime.fromtimestamp(mtime)).total_seconds()
            if age_seconds > max_age_seconds:
                os.remove(filepath)
                delete_count +=1
        return delete_count
    


if __name__ == "__main__":                                        
    import time                                                   
                                                                  
    sc = ScreenCapture()                                          
                                                                  
    print("=" * 50)                                               
    print("TEST 1: Get Monitor Info")                             
    print("=" * 50)                                               
    monitors = sc.get_monitors()                                  
    for mon in monitors:                                          
        print(f"  Monitor {mon.index}: {mon.width}x{mon.height}") 
        print(f"    Position: ({mon.x}, {mon.y})")                
        print(f"    Primary: {mon.is_primary}")                   
        print(f"    Scale: {mon.scale_factor}")                   
                                                                  
    print("\n" + "=" * 50)                                        
    print("TEST 2: Capture Full Screen")                          
    print("=" * 50)                                               
    screenshot = sc.capture_full_screen()                         
    print(f"  Size: {screenshot.image.size}")                     
    print(f"  Region: {screenshot.region}")                       
    path = sc.save_screenshot(screenshot)                         
    print(f"  Saved to: {path}")                                  
                                                                  
    print("\n" + "=" * 50)                                        
    print("TEST 3: Capture Active Window")                        
    print("=" * 50)                                               
    window_ss = sc.capture_active_window()                        
    if window_ss:                                                 
        print(f"  Size: {window_ss.image.size}")                  
        print(f"  HWND: {window_ss.source_hwnd}")                 
    else:                                                         
        print("  No active window")                               
                                                                  
    print("\n" + "=" * 50)                                        
    print("TEST 4: Capture Region")                               
    print("=" * 50)                                               
    region_ss = sc.capture_region(100, 100, 400, 300)             
    print(f"  Size: {region_ss.image.size}")                      
                                                                  
    print("\n" + "=" * 50)                                        
    print("TEST 5: Compare Screenshots")                          
    print("=" * 50)                                               
    print("  Capturing 'before'...")                              
    before = sc.capture_full_screen()                             
    print("  Waiting 2 seconds (move something on screen)...")    
    time.sleep(2)                                                 
    print("  Capturing 'after'...")                               
    after = sc.capture_full_screen()                              
    diff = sc.compare_screenshots(before, after)                  
    print(f"  Similarity: {diff.similarity_score:.2%}")           
    print(f"  Changed regions: {len(diff.changed_regions)}")      
    print(f"  Significant change: {diff.has_significant_change}") 
                                                                  
    print("\n" + "=" * 50)                                        
    print("TEST 6: Capture Around Cursor")                        
    print("=" * 50)                                               
    cursor_ss = sc.capture_around_cursor(sc.config.visual.region_around_cursor[0], sc.config.visual.region_around_cursor[1])                
    print(f"  Size: {cursor_ss.image.size}")                      
    path = sc.save_screenshot(cursor_ss)
    print(path)                                         
    print("\nAll tests completed!")                               
                                                                  
