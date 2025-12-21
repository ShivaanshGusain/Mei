import os
from ...core.config import ProcessInfo
from ...core.events import subscribe, emit, EventType
import psutil
from .applibrary import AppLibrary
from typing import List, Optional
import subprocess
from datetime import datetime
class ProcessManager:
    def __init__(self):
        self.app_library = AppLibrary()

    def get_running_processes(self) -> List[ProcessInfo]:
        result = []
        for process in psutil.process_iter(attrs=['pid','name','exe','status','memory_info','cpu_percent','create_time']):
            try:
                processed = self._build_process_info(process)
                result.append(processed)
            except (psutil.AccessDenied, psutil.ZombieProcess, psutil.NoSuchProcess):
                continue
        return result
    
    def is_running(self, name:str) -> bool:
        name = self._normalized_name(name)
        for process in psutil.process_iter(attrs=['name']):
            try:
                process_name = process.info.get('name', "")
                if name == process_name.lower():
                    return True
            except:
                continue
        return False
    
    def find_process(self, name: str) -> Optional[ProcessInfo]:
        name = self._normalized_name(name)
        for process in psutil.process_iter(attrs=['pid','name','exe','status','memory_info','cpu_percent','create_time']):
            try:
                if process.info.get("name", "").lower() == name:
                    processed = self._build_process_info(process)
                    return processed

            except:
                continue
        return None
    
    def find_all_processes(self, name: str) -> List[ProcessInfo]:
        name = self._normalized_name(name)
        result = []
        for process in psutil.process_iter(attrs=['pid','name','exe','status','memory_info','cpu_percent','create_time']):
            try:
                if process.info.get("name", "").lower() == name:
                    processed = self._build_process_info(process)
                    result.append(processed)
            except (psutil.AccessDenied, psutil.ZombieProcess, psutil.NoSuchProcess):
                continue
        return result 

    def get_process_by_pid(self, pid: int) -> Optional[ProcessInfo]:
        try:
            process = psutil.Process(pid)
            processed = self._build_process_info(process)
            return processed
        except psutil.NoSuchProcess:
            return None
        except psutil.AccessDenied:
            return processed
        
    def launch(self, app_name: str) -> Optional[int]:
        path = self.app_library.get_path(app_name)

        if path is None:
            print(f"[ProcessManager] '{app_name}' not in cache, scanning...")
            self.app_library.refresh_library()
            path = self.app_library.get_path(app_name)
            if path is None:
                return None


        if not os.path.exists(path):
            return None
        try:
            # Get process count BEFORE launching
            name_normalized = self._normalized_name(app_name)
            existing_pids = {p.pid for p in self.find_all_processes(app_name)}
            
            # Launch
            subprocess.Popen([path], shell=False, start_new_session=True)
            
            # Wait briefly for actual process to spawn
            import time
            time.sleep(1)
            
            # Find NEW process (not in existing_pids)
            for proc in self.find_all_processes(app_name):
                if proc.pid not in existing_pids:
                    emit(event_type=EventType.APP_LAUNCHED, source='ProcessManager', pid=proc.pid)
                    return proc.pid
            
            # Fallback: return any matching process
            found = self.find_process(app_name)
            if found:
                return found.pid
            
            return None
            
        except Exception as e:
            emit(event_type=EventType.ERROR, source='ProcessManager', error=str(e))
            return None

    def terminate(self, pid: int) -> bool:
        try:
            process = psutil.Process(pid)
            name = process.name()
            process.terminate()
            process.wait(timeout=3)
            emit(event_type=EventType.APP_CLOSED, source='ProcessManager', name = name)
            return True
        except psutil.TimeoutExpired:
            process.kill()
            return True
        except psutil.NoSuchProcess:
            return True
        except psutil.AccessDenied:
            emit(event_type=EventType.ERROR, source = 'ProcessManager')
            return False
        
    def terminate_by_name(self, name: str) -> int:
        processes = self.find_all_processes(name)
        terminated_count = 0
        for process in processes:
            if self.terminate(process.pid):
                terminated_count+=1

        return terminated_count
    

    def _normalized_name(self, name: str) -> str:
        name = name.lower().strip()
        if not name.endswith('.exe'):
            name = name + '.exe'
        return name
    
    def _build_process_info(self, proc) -> ProcessInfo:
        pid = proc.info['pid']
        name = proc.info.get('name', 'unknown')
        path = proc.info.get('exe', 'unknown')
        status = proc.info.get('status','unknown')
        memory_info = proc.info.get('memory_info')
        memory_mb = memory_info.rss/ (1024*1024) if memory_info else 0
        
        cpu_percent= proc.info.get('cpu_percent', 0.0)

        create_time = proc.info.get('create_time')

        if create_time:
            create_time = datetime.fromtimestamp(create_time)
        process = ProcessInfo(pid,name,path,status, memory_info, memory_mb, cpu_percent, create_time)
        return process
    


# At the end of processes.py

if __name__ == "__main__":
    pm = ProcessManager()
    
    print("\n" + "=" * 50)
    print("TEST 1: List Running Processes (first 10)")
    print("=" * 50)
    processes = pm.get_running_processes()[:10]
    for p in processes:
        print(f"  PID:{p.pid:6} | {p.name:25} | {p.memory_mb:.1f}MB")
    
    print("\n" + "=" * 50)
    print("TEST 2: Check if brave is running")
    print("=" * 50)
    is_brave = pm.is_running("brave")
    print(f"  Brave running: {is_brave}")
    
    print("\n" + "=" * 50)
    print("TEST 3: Find Notepad process")
    print("=" * 50)
    notepad = pm.find_process("notepad")
    if notepad:
        print(f"  Found: PID={notepad.pid}, Path={notepad.path}")
    else:
        print("  Notepad not running")
    
    print("\n" + "=" * 50)
    print("TEST 4: Launch Notepad")
    print("=" * 50)
    pid = pm.launch("notepad")
    print(pid)
    if pid:
        print(f"  Launched Notepad with PID: {pid}")
        
        import time
        time.sleep(1)  # Let it open
        
        print("\n" + "=" * 50)
        print("TEST 5: Terminate Notepad")
        print("=" * 50)
        success = pm.terminate(pid)
        print(f"  Terminated: {success}")
    else:
        print("  Failed to launch Notepad")
        