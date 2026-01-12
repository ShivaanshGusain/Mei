from ...core.config import TabInfo, WindowInfo, ExtendedWindowInfo
from ...core.task import AppBridge
import os
from typing import Dict, List, Optional
import win32gui, win32con, win32process, win32api
import psutil
from ...core.events import EventType, emit

class WindowManager:
    def __init__(self):
        self._bridges: Dict[str, AppBridge] = {}
        self._focus_history:List[int] = []
        self._max_history = 50
        # Cache for performance - 
        self._window_cache:Dict[int, WindowInfo] = {}
        self._cache_timeout = 1.0 # seconds
        self._last_cache_time  = 0

    def register_bridge(self,bridge:AppBridge)->None:
        for process_name in bridge.supported_process:
            self._bridges[process_name.lower()] = bridge
            print(f"Registered {bridge.app_type} bridge")

    def unregister_bridge(self, bridge:AppBridge) ->None:
        for process_name in bridge.supported_process:
            del self._bridges[process_name]
        print(f"Process: {bridge.app_type} removed from bridge")
    
    def _get_bridge(self, process_name: str)-> Optional[AppBridge]:
        bridge = self._bridges.get(process_name.lower())
        if bridge and bridge.is_connected:
            return bridge
        else:
            return None
    
    def get_all_windows(self, include_hidden = False) -> List[WindowInfo]:
        results: List[WindowInfo] = []

        def enum_callback(hwnd, results):
            try:
                # Skip if not a real window
                if not include_hidden:
                    if not self._is_real_window(hwnd):
                        return True
                
                info = self._build_window_info(hwnd)
                if info:
                    results.append(info)
            except:
                pass
            return True
        win32gui.EnumWindows(enum_callback,results)
        return results
    
    def get_extended_window_info(self, hwnd:int) ->ExtendedWindowInfo:
        window = self._build_window_info(hwnd)
        if not window:
            return None
        # Checking for app specific bridge
        bridge = self._get_bridge(window.process_name)
        
        #if bridge exists and connected:
        if bridge and bridge.is_connected:
            tabs = bridge.get_tabs(hwnd)
            state = bridge.get_state(hwnd)
            return ExtendedWindowInfo(
                window=window,
                tabs= tabs,
                has_deep_access=True,
                app_type=bridge.app_type,
                current_state=state
            )
        else:
            return ExtendedWindowInfo(
                window=window,
                tabs = [],
                has_deep_access=False,
                app_type='generic',
                current_state={}
            )
        
    def get_foreground_window(self) ->Optional[WindowInfo]:
        try:
            hwnd = win32gui.GetForegroundWindow()
            if hwnd ==0:
                return None
            self._update_focus_history(hwnd)
            return self._build_window_info(hwnd)
        except:
            return None
        
    def find_window(self, query: str, strategy= "smart") -> Optional[WindowInfo]:
        matches = self.find_windows(query=query)
        if not matches:
            return None
        if len(matches) ==1:
            return matches[0]
        else:
            if strategy == 'smart':
                exact = [w for w in matches
                         if w.title.lower() == query.lower()]
                if exact:
                    return exact[0]
                return self._get_most_recent(matches)
            elif strategy== 'mru':
                return self._get_most_recent(matches)
            elif strategy == 'first':
                return matches[0]
            elif strategy == 'ask':
                return None
    
    def find_windows(self,query:str) ->List[WindowInfo]:
        query = query.lower().strip()
        all_windows = self.get_all_windows()
        matches = []
        for window in all_windows:
            proc_name_clean = window.process_name.lower().replace(".exe", "")
            if query in proc_name_clean:
                matches.insert(0, window)
                continue
            if query in proc_name_clean:
                matches.append(window)
                continue
            if query in window.title.lower():
                matches.append(window)
        return matches
    
    def find_tab(self,query:str)->Optional[tuple[WindowInfo, TabInfo]]:
        query = query.lower().strip()
        all_windows = self.get_all_windows()

        for window in all_windows:
            if query in window.title.lower():
                return (window, None)
            
            bridge = self._get_bridge(window.process_name)
            if bridge and bridge.is_connected:
                tabs = bridge.get_tabs(window.hwnd)
                for tab in tabs:
                    if query in tab.title.lower():
                        return (window, tab)
                    if tab.url and query in tab.url.lower():
                        return (window,tab)
        return None
    
    def focus_window(self, hwnd: int)-> bool:
        if not win32gui.IsWindow(hwnd):
            return False
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        try:
            self._force_foreground(hwnd)
            self._update_focus_history(hwnd)
            return True
        except:
            return False
        
    def _force_foreground(self, hwnd: int) -> None:
        try:
            foreground_hwnd = win32gui.GetForegroundWindow()
            foreground_thread, _ = win32process.GetWindowThreadProcessId(foreground_hwnd)
            current_thread = win32api.GetCurrentThreadId()
            if foreground_thread != current_thread:
                win32process.AttachThreadInput(current_thread, foreground_thread, True)
            win32gui.SetForegroundWindow(hwnd)
            win32gui.BringWindowToTop(hwnd)
            if foreground_thread != current_thread:
                win32process.AttachThreadInput(current_thread, foreground_thread, False)
        except Exception:
            win32gui.SetForegroundWindow(hwnd)
        
    def _update_focus_history(self, hwnd: int) -> None:
        if hwnd in self._focus_history:
            self._focus_history.remove(hwnd)

        self._focus_history.insert(0,hwnd)
        self._focus_history = self._focus_history[:self._max_history]


    def focus_tab(self, hwnd: int, tab_id: str) -> bool:
        # Get window information
        window = self._build_window_info(hwnd)
        if not window:
            return False
        if not self.focus_window(hwnd):
            return False
        
        bridge = self._get_bridge(process_name=window.process_name)
        if bridge and bridge.is_connected:
            return bridge.switch_to_tab(hwnd, tab_id)
        else:
            return True
        
    def maximize_window(self, hwnd: int) -> bool:
        window = self._build_window_info(hwnd)
        if not window:
            return False
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        emit(event_type=EventType.WINDOW_CHANGED, source="WindowManager")
        return True

    def minimize_window(self, hwnd:int) ->bool:
        window = self._build_window_info(hwnd)
        if not window:
                return False
        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        emit(event_type=EventType.WINDOW_CHANGED, source="WindowManager")
        return True

    def restore_window(self, hwnd:int) -> bool:
        window = self._build_window_info(hwnd)
        if not window:
            return False
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        emit(event_type=EventType.WINDOW_CHANGED, source="WindowManager")
        return True
    
    def close_window(self, hwnd:int)->bool:
        window = self._build_window_info(hwnd)
        if not window:
            return False
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0,0)
        emit(event_type=EventType.WINDOW_CLOSED, source= "WindowManager")
        return True
    
    def close_tab(self, hwnd: int, tab_id: str)->bool:
        window = self._build_window_info(hwnd)
        if not window:
            return False

        bridge = self._get_bridge(window.process_name)
        if bridge and bridge.is_connected:
            closed =  bridge.close_tab(hwnd,tab_id=tab_id)
            if closed:
                emit(event_type=EventType.TAB_CLOSED, source="WindowManager")
        else:
            return False
        
    def move_window(self, hwnd:int, x:int, y:int)->bool:
        window = self._build_window_info(hwnd)
        if not window:
            return False
        rect = win32gui.GetWindowRect(hwnd)
        width = rect[2] - rect[0]
        height = rect[3] - rect[1]
        win32gui.MoveWindow(hwnd, x,y,width, height, True)
        return True
    
    def resize_window(self, hwnd: int, width: int, height: int) -> bool:
        window = self._build_window_info(hwnd)
        if not window:
            return False
        rect = win32gui.GetWindowRect(hwnd)
        x,y = rect[0], rect[1]
        win32gui.MoveWindow(hwnd,x,y,width,height,True)
        return True
    
    def get_window_by_pid(self, pid:int)->Optional[WindowInfo]:
        def enum_callback(hwnd, found_window):
            if found_window: return

            if not win32gui.IsWindowVisible(hwnd):
                return
            try:
                _,window_pid = win32process.GetWindowThreadProcessId(hwnd)
                if window_pid == pid:
                    if win32gui.GetWindowText(hwnd):
                        found_window.append(self._build_window_info(hwnd))
            except:
                pass
            found = []
            win32gui.EnumWindows(enum_callback, found)
            return found[0] if found else None
        
    def get_window_by_hwnd(self, hwnd: int) -> Optional[WindowInfo]:
        if not win32gui.IsWindow(hwnd):
            return None
        return self._build_window_info(hwnd)
    
    def _build_window_info(self,hwnd:int)->Optional[WindowInfo]:
        try:
            title = win32gui.GetWindowText(hwnd)
            _,pid =win32process.GetWindowThreadProcessId(hwnd)
            try:
                process = psutil.Process(pid)
                process_name = process.name()
            except:
                process_name = "unknown"
            rect = win32gui.GetWindowRect(hwnd)
            x,y = rect[0], rect[1]
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]

            is_visible = win32gui.IsWindowVisible(hwnd)
            is_minimized = win32gui.IsIconic(hwnd)
            placement = win32gui.GetWindowPlacement(hwnd)
            is_maximized = (placement[1] == win32con.SW_SHOWMAXIMIZED)
            return WindowInfo(hwnd=hwnd, 
                              title=title, 
                              process_name=process_name, 
                              pid=pid, 
                              x=x,
                              y=y,
                              width=width, 
                              height=height, 
                              is_visible=is_visible,
                              is_minimized=is_minimized,
                              is_maximized=is_maximized
                              )
        except:
            return None

    def _get_most_recent(self, windows: List[WindowInfo]) -> Optional[WindowInfo]:
        for hwnd in self._focus_history:
            for window in windows:
                if window.hwnd == hwnd:
                    return window
        return windows[0] if windows else None
     
    def _is_real_window(self, hwnd: int) -> bool:
        # Must be visible
        if not win32gui.IsWindowVisible(hwnd):
            return False
        
        # Must have title
        title = win32gui.GetWindowText(hwnd)
        if not title or len(title.strip()) == 0:
            return False
        
        # Skip known system windows
        skip_titles = ["program manager", "windows input experience", 
                    "msctfime ui", "default ime"]
        if title.lower() in skip_titles:
            return False
        
        # Must have size
        try:
            rect = win32gui.GetWindowRect(hwnd)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
            if width <= 0 or height <= 0:
                return False
        except:
            return False
        
        return True
    
_window_manager_instance: Optional[WindowManager] = None

def get_window_manager() -> WindowManager:
    global _window_manager_instance
    if _window_manager_instance is None:
        _window_manager_instance = WindowManager()
    return _window_manager_instance