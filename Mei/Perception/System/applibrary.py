import winreg
import os
import csv
from difflib import get_close_matches


class AppLibrary:
    def __init__(self, cache_file="known_apps.csv"):
        self.cache_file = cache_file
        self.apps = {}
        self._load_cache_only()

    def _load_cache_only(self):
        if not os.path.exists(self.cache_file):
            self.apps = {}
            return
        try:
            with open(self.cache_file, mode='r', encoding='utf-8') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) == 2:
                        self.apps[row[0]] = row[1]
        except Exception:
            self.apps = {}


    def load_cache(self):
        """Loads apps from CSV. If missing or corrupted, runs a scan."""
        if not os.path.exists(self.cache_file):
            print("[AppLib] Cache not found. Scanning system...")
            self.refresh_library()
            return
        
        print("[AppLib] Loading application cache...")
        try:
            with open(self.cache_file, mode='r', encoding='utf-8') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) == 2:
                        self.apps[row[0]] = row[1]
        except Exception as e:
            print(f"[AppLib] Cache corrupted: {e}")
            self.refresh_library()
            return
        
        if not self.apps:
            print("[AppLib] Cache empty, rescanning...")
            self.refresh_library()
        else:
            print(f"[AppLib] Loaded {len(self.apps)} applications from cache.")

    def refresh_library(self):
        """Scans the Registry, system folders, and common paths for installed apps."""
        found_apps = {}
        
        # 1. SCAN REGISTRY
        print("[AppLib] Scanning registry...")
        registry_paths = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
        ]
        
        for reg_path in registry_paths:
            self._scan_registry_key(winreg.HKEY_LOCAL_MACHINE, reg_path, found_apps)
            self._scan_registry_key(winreg.HKEY_CURRENT_USER, reg_path, found_apps)

        # 2. ADD SYSTEM TOOLS
        print("[AppLib] Adding system tools...")
        system_tools = self._get_system_tools()
        for name, path in system_tools.items():
            if name not in found_apps:
                found_apps[name] = path

        # 3. SCAN COMMON FOLDERS
        print("[AppLib] Scanning common folders...")
        self._scan_common_folders(found_apps)

        # 4. SAVE TO CSV
        self.apps = found_apps
        self._save_cache()
        
        print(f"[AppLib] Scan complete. Found {len(self.apps)} applications.")

    def _save_cache(self):
        """Save current apps to CSV cache."""
        with open(self.cache_file, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            for name, path in self.apps.items():
                writer.writerow([name, path])

    def _get_system_tools(self):
        """Get paths to common Windows system tools."""
        system_tools = {}
        
        windir = os.environ.get('WINDIR', r'C:\Windows')
        system32 = os.path.join(windir, 'System32')
        
        known_tools = {
            'notepad': os.path.join(system32, 'notepad.exe'),
            'cmd': os.path.join(system32, 'cmd.exe'),
            'powershell': os.path.join(system32, 'WindowsPowerShell', 'v1.0', 'powershell.exe'),
            'explorer': os.path.join(windir, 'explorer.exe'),
            'mspaint': os.path.join(system32, 'mspaint.exe'),
            'paint': os.path.join(system32, 'mspaint.exe'),  # Alias
            'regedit': os.path.join(windir, 'regedit.exe'),
            'taskmgr': os.path.join(system32, 'Taskmgr.exe'),
            'taskmanager': os.path.join(system32, 'Taskmgr.exe'),  # Alias
            'control': os.path.join(system32, 'control.exe'),
            'mstsc': os.path.join(system32, 'mstsc.exe'),
            'snippingtool': os.path.join(system32, 'SnippingTool.exe'),
            'calc': os.path.join(system32, 'calc.exe'),
            'calculator': os.path.join(system32, 'calc.exe'),  # Alias
            'charmap': os.path.join(system32, 'charmap.exe'),
            'magnify': os.path.join(system32, 'Magnify.exe'),
            'osk': os.path.join(system32, 'osk.exe'),  # On-screen keyboard
            'msconfig': os.path.join(system32, 'msconfig.exe'),
            'devmgmt': os.path.join(system32, 'devmgmt.msc'),
        }
        
        for name, path in known_tools.items():
            if os.path.exists(path):
                system_tools[name] = path
        
        # Windows Terminal (newer systems)
        localappdata = os.environ.get('LOCALAPPDATA', '')
        terminal_path = os.path.join(localappdata, 'Microsoft', 'WindowsApps', 'wt.exe')
        if os.path.exists(terminal_path):
            system_tools['terminal'] = terminal_path
            system_tools['wt'] = terminal_path
        
        return system_tools

    def _scan_common_folders(self, app_dict):
        """Scan common installation directories for executables."""
        program_files = os.environ.get('PROGRAMFILES', r'C:\Program Files')
        program_files_x86 = os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)')
        local_appdata = os.environ.get('LOCALAPPDATA', '')
        appdata = os.environ.get('APPDATA', '')
        
        scan_targets = [
            (os.path.join(program_files, 'Google', 'Chrome', 'Application'), 'chrome', 'chrome.exe'),
            (os.path.join(program_files_x86, 'Google', 'Chrome', 'Application'), 'chrome', 'chrome.exe'),
            (os.path.join(program_files, 'Mozilla Firefox'), 'firefox', 'firefox.exe'),
            (os.path.join(program_files_x86, 'Mozilla Firefox'), 'firefox', 'firefox.exe'),
            (os.path.join(program_files, 'VideoLAN', 'VLC'), 'vlc', 'vlc.exe'),
            (os.path.join(program_files_x86, 'VideoLAN', 'VLC'), 'vlc', 'vlc.exe'),
            (os.path.join(local_appdata, 'Programs', 'Microsoft VS Code'), 'vscode', 'Code.exe'),
            (os.path.join(local_appdata, 'Programs', 'Microsoft VS Code'), 'code', 'Code.exe'),
            (os.path.join(appdata, 'Spotify'), 'spotify', 'Spotify.exe'),
            (os.path.join(local_appdata, 'Discord'), 'discord', 'Discord.exe'),
            (os.path.join(local_appdata, 'slack'), 'slack', 'slack.exe'),
            (os.path.join(program_files, 'Notepad++'), 'notepad++', 'notepad++.exe'),
            (os.path.join(program_files_x86, 'Notepad++'), 'notepad++', 'notepad++.exe'),
            (os.path.join(program_files, '7-Zip'), '7zip', '7zFM.exe'),
            (os.path.join(program_files_x86, '7-Zip'), '7zip', '7zFM.exe'),
        ]
        
        for folder, app_name, exe_name in scan_targets:
            if app_name in app_dict:
                continue
            
            exe_path = os.path.join(folder, exe_name)
            if os.path.exists(exe_path):
                app_dict[app_name] = exe_path

    def _scan_registry_key(self, root, path, app_dict):
        """Helper to iterate through registry keys."""
        try:
            key = winreg.OpenKey(root, path)
        except (FileNotFoundError, OSError):
            return
        
        try:
            subkey_count = winreg.QueryInfoKey(key)[0]
            
            for i in range(subkey_count):
                try:
                    subkey_name = winreg.EnumKey(key, i)
                    subkey = winreg.OpenKey(key, subkey_name)
                    
                    try:
                        self._extract_app_info(subkey, app_dict)
                    finally:
                        winreg.CloseKey(subkey)
                        
                except (OSError, PermissionError):
                    continue
                    
        finally:
            winreg.CloseKey(key)

    def _extract_app_info(self, subkey, app_dict):
        """Extract app name and path from a registry subkey."""
        try:
            name = winreg.QueryValueEx(subkey, "DisplayName")[0]
        except FileNotFoundError:
            return
        
        if not name or not name.strip():
            return
        
        install_path = None
        
        # Try InstallLocation
        try:
            install_path = winreg.QueryValueEx(subkey, "InstallLocation")[0]
        except FileNotFoundError:
            pass
        
        # Try DisplayIcon as fallback
        if not install_path:
            try:
                icon_path = winreg.QueryValueEx(subkey, "DisplayIcon")[0]
                install_path = icon_path.split(',')[0].strip('"').strip("'")
            except FileNotFoundError:
                pass
        
        if not install_path:
            return
        
        clean_name = name.lower().strip()
        
        if os.path.isdir(install_path):
            exe_path = self._find_exe_in_folder(install_path, name)
            if exe_path:
                self._add_app(app_dict, clean_name, exe_path)
        elif install_path.lower().endswith('.exe') and os.path.exists(install_path):
            self._add_app(app_dict, clean_name, install_path)

    def _add_app(self, app_dict, full_name, path):
        """Add app with full name and short aliases."""
        app_dict[full_name] = path
        
        skip_words = {'microsoft', 'google', 'adobe', 'mozilla', 'the', 'for', 'and', 'or', 'inc', 'llc', 'corp'}
        words = full_name.replace('-', ' ').replace('_', ' ').split()
        
        for word in words:
            if word not in skip_words and len(word) > 2:
                if word not in app_dict:
                    app_dict[word] = path
                break

    def _find_exe_in_folder(self, folder, app_name):
        """Try to find the main executable in a folder."""
        if not os.path.isdir(folder):
            return None
        
        app_words = [w.lower() for w in app_name.split() if len(w) > 2]
        
        try:
            exe_files = [f for f in os.listdir(folder) if f.lower().endswith('.exe')]
            
            for exe in exe_files:
                exe_lower = exe.lower()
                for word in app_words:
                    if word in exe_lower:
                        full_path = os.path.join(folder, exe)
                        if os.path.isfile(full_path):
                            return full_path
            
            if len(exe_files) == 1:
                full_path = os.path.join(folder, exe_files[0])
                if os.path.isfile(full_path):
                    return full_path
                    
        except PermissionError:
            pass
        
        return None

    def get_path(self, app_name):
        """Smart lookup: exact → contains → fuzzy match."""
        query = app_name.lower().strip()
        
        # 1. Exact Match
        if query in self.apps:
            return self.apps[query]
        
        # 2. Substring Match
        for name, path in self.apps.items():
            if query in name:
                return path
        
        return None

    def list_apps(self):
        """Return list of all known app names."""
        return sorted(self.apps.keys())


# --- TEST BLOCK ---
if __name__ == "__main__":
    lib = AppLibrary()
    
    print("\n" + "=" * 50)
    print("TEST: Application Lookups")
    print("=" * 50)
    
    test_apps = ['chrome', 'firefox', 'vlc', 'notepad', 'code', 'vscode', 'calculator', 'paint']
    
    for app in test_apps:
        path = lib.get_path(app)
        status = "✓" if path else "✗"
        print(f"  {status} {app:15} → {path or 'Not found'}")
    
    print(f"\n  Total apps in library: {len(lib.apps)}")