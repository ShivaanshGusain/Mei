"""
Shell commands and background process management.
"""
import subprocess
import shlex
import threading
import queue
import time
import os
from typing import Dict, Any, Tuple, Optional, List
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from ....core.config import ActionResult, ManagedProcess
from ....core.events import emit, EventType
from ...context import ExecutionContext
from .guardrails import validate_command_safe, truncate_output, get_limits


class _BackgroundProcessManager:
    """
    Singleton. Thread-safe via _lock on ALL dict access.
    Uses Queue-based output capture instead of thread-per-read.
    """
    
    def __init__(self):
        self._processes: Dict[int, ManagedProcess] = {}
        self._lock = threading.RLock() #Reentrant Lock 
    
    def active_count(self) -> int:
        with self._lock:
            self._cleanup_dead_locked()
            return sum(1 for mp in self._processes.values()
                      if mp.process.poll() is None)
    
    def can_start(self) -> bool:
        return self.active_count() < get_limits().max_concurrent_processes
    
    def start(self, command: str,
              cwd: str = None) -> Tuple[Optional[ManagedProcess], Optional[str]]:
        """
        Start a background process. Captures early output via Queue.
        """
        if not self.can_start():
            limit = get_limits().max_concurrent_processes
            return (None, f"Max {limit} concurrent processes. Kill one first.")
        
        # Parse command for shell=False execution
        try:
            args = shlex.split(command, posix=False)
        except ValueError as e:
            return (None, f"Cannot parse command: {e}")
        
        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=cwd,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        except FileNotFoundError:
            return (None, f"Executable not found: {args[0]}")
        except Exception as e:
            return (None, f"Failed to start: {e}")
        
        managed = ManagedProcess(
            pid=proc.pid, command=command, process=proc,
        )
        
        # ── Capture early output via Queue (single thread) ──
        early_queue = queue.Queue()
        wait_secs = get_limits().early_output_wait_seconds
        
        def early_reader():
            try:
                for line in proc.stdout:
                    line = line.rstrip("\n\r")
                    early_queue.put(line)
                    managed.log_buffer.append(line)
            except:
                pass
        
        reader = threading.Thread(target=early_reader, daemon=True,
                                  name=f"proc-reader-{proc.pid}")
        reader.start()
        managed._reader_thread = reader
        
        # Wait for early output (blocking, but only for wait_secs)
        deadline = time.time() + wait_secs
        early_lines = []
        while time.time() < deadline:
            try:
                line = early_queue.get(timeout=0.1)
                early_lines.append(line)
            except queue.Empty:
                if proc.poll() is not None:
                    break   # process already exited
        
        # Drain any remaining queued lines
        while not early_queue.empty():
            try:
                early_lines.append(early_queue.get_nowait())
            except queue.Empty:
                break
        
        # Check if process crashed during startup
        if proc.poll() is not None and proc.returncode != 0:
            return (None,
                    f"Process exited immediately (code {proc.returncode}).\n"
                    + "\n".join(early_lines[-20:]))
        
        with self._lock:
            self._processes[proc.pid] = managed
        
        return (managed, None)
    
    def get_logs(self, pid: int, lines: int = 50) -> Tuple[Optional[List[str]], bool]:
        """
        Get recent log lines. Returns (lines, is_alive).
        Returns (None, False) if PID not found.
        """
        with self._lock:
            managed = self._processes.get(pid)
            if not managed:
                return (None, False)
            logs = list(managed.log_buffer)[-lines:]
            alive = managed.process.poll() is None
            return (logs, alive)
    
    def get_return_code(self, pid: int) -> Optional[int]:
        with self._lock:
            managed = self._processes.get(pid)
            if not managed:
                return None
            return managed.process.returncode
    
    def kill(self, pid: int) -> Tuple[bool, str]:
        with self._lock:
            managed = self._processes.get(pid)
            if not managed:
                return (False, f"No managed process with PID {pid}")
            
            try:
                managed.process.terminate()
                try:
                    managed.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    managed.process.kill()
                self._processes.pop(pid, None)
                return (True, f"Process {pid} terminated")
            except Exception as e:
                return (False, f"Failed to kill {pid}: {e}")
    
    def list_processes(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._cleanup_dead_locked()
            return [
                {
                    "pid": pid,
                    "command": mp.command[:80],
                    "alive": mp.process.poll() is None,
                    "started_at": mp.started_at.isoformat(),
                    "log_lines": len(mp.log_buffer),
                }
                for pid, mp in self._processes.items()
            ]
    
    def _cleanup_dead_locked(self):
        """Remove dead processes older than 5 min. Caller MUST hold _lock."""
        now = datetime.now()
        dead = [
            pid for pid, mp in self._processes.items()
            if mp.process.poll() is not None
            and (now - mp.started_at).total_seconds() > 300
        ]
        for pid in dead:
            self._processes.pop(pid, None)


_bg_manager: Optional[_BackgroundProcessManager] = None

def _get_bg_manager() -> _BackgroundProcessManager:
    global _bg_manager
    if _bg_manager is None:
        _bg_manager = _BackgroundProcessManager()
    return _bg_manager


# ═══════════════════════════════════════════════════
# run_shell_command — shell=False, shlex-parsed
# ═══════════════════════════════════════════════════

RUN_SHELL_COMMAND_SCHEMA = {
    "command": {"type": "str", "required": True,
                "description": "Shell command to execute"},
    "timeout": {"type": "int", "required": False, "default": 30,
                "description": "Max seconds to wait"},
}

def run_shell_command_validate(params):
    cmd = params.get("command")
    if not cmd or not str(cmd).strip():
        return (False, "Missing 'command' parameter")
    return validate_command_safe(str(cmd))

def run_shell_command_execute(params, context):
    command = str(params["command"]).strip()
    max_timeout = get_limits().max_shell_timeout_seconds
    timeout = min(params.get("timeout", 30), max_timeout)
    cwd = context.get_variable("cwd", os.getcwd())
    
    try:
        args = shlex.split(command, posix=False)
    except ValueError as e:
        return ActionResult(
            success=False, error=f"Cannot parse: {e}",
            error_code="validation_error", method_used="subprocess"
        )
    
    try:
        result = subprocess.run(
            args,                       # NOT shell=True
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        
        stdout, trunc_out = truncate_output(result.stdout)
        stderr, trunc_err = truncate_output(result.stderr, max_chars=3000)
        
        return ActionResult(
            success=(result.returncode == 0),
            data={
                "stdout": stdout,
                "stderr": stderr,
                "return_code": result.returncode,
                "truncated": trunc_out or trunc_err,
                "cwd": cwd,
            },
            error=stderr[:500] if result.returncode != 0 else None,
            error_code="command_failed" if result.returncode != 0 else None,
            method_used="subprocess"
        )
    except subprocess.TimeoutExpired:
        return ActionResult(
            success=False, error=f"Command timed out after {timeout}s",
            error_code="timeout", method_used="subprocess"
        )
    except FileNotFoundError:
        return ActionResult(
            success=False, error=f"Executable not found: {args[0]}",
            error_code="not_found", method_used="subprocess"
        )
    except Exception as e:
        return ActionResult(
            success=False, error=str(e),
            error_code="unknown", method_used="subprocess"
        )


# ═══════════════════════════════════════════════════
# start_background_process
# ═══════════════════════════════════════════════════

START_BG_PROCESS_SCHEMA = {
    "command": {"type": "str", "required": True,
                "description": "Command to run in background"},
}

def start_bg_process_validate(params):
    cmd = params.get("command")
    if not cmd or not str(cmd).strip():
        return (False, "Missing 'command' parameter")
    return validate_command_safe(str(cmd))

def start_bg_process_execute(params, context):
    command = str(params["command"]).strip()
    cwd = context.get_variable("cwd", os.getcwd())
    
    manager = _get_bg_manager()
    managed, error = manager.start(command, cwd=cwd)
    
    if error:
        code = "process_limit" if "Max" in error else "command_failed"
        return ActionResult(
            success=False, error=error,
            error_code=code, method_used="subprocess"
        )
    
    early_logs = list(managed.log_buffer)
    
    emit(EventType.ACTION_COMPLETED,
         source="start_background_process",
         pid=managed.pid, command=command)
    
    return ActionResult(
        success=True,
        data={
            "pid": managed.pid,
            "command": command,
            "early_output": "\n".join(early_logs[-10:]),
            "alive": managed.process.poll() is None,
        },
        method_used="subprocess"
    )


# ═══════════════════════════════════════════════════
# get_process_logs — all access through public methods
# ═══════════════════════════════════════════════════

GET_PROCESS_LOGS_SCHEMA = {
    "pid": {"type": "int", "required": True},
    "lines": {"type": "int", "required": False, "default": 50},
}

def get_process_logs_validate(params):
    if "pid" not in params:
        return (False, "Missing 'pid' parameter")
    return (True, None)

def get_process_logs_execute(params, context):
    pid = int(params["pid"])
    lines = min(params.get("lines", 50), get_limits().max_log_lines)
    
    manager = _get_bg_manager()
    logs, alive = manager.get_logs(pid, lines)
    
    if logs is None:
        return ActionResult(
            success=False, error=f"No managed process with PID {pid}",
            error_code="not_found", method_used="process_manager"
        )
    
    return_code = None if alive else manager.get_return_code(pid)
    
    return ActionResult(
        success=True,
        data={
            "pid": pid,
            "alive": alive,
            "return_code": return_code,
            "log_lines": len(logs),
            "logs": "\n".join(logs),
        },
        method_used="process_manager"
    )


# ═══════════════════════════════════════════════════
# kill_process — through public method
# ═══════════════════════════════════════════════════

KILL_PROCESS_SCHEMA = {
    "pid": {"type": "int", "required": True},
}

def kill_process_validate(params):
    if "pid" not in params:
        return (False, "Missing 'pid' parameter")
    return (True, None)

def kill_process_execute(params, context):
    pid = int(params["pid"])
    manager = _get_bg_manager()
    success, message = manager.kill(pid)
    
    return ActionResult(
        success=success,
        data={"pid": pid, "message": message},
        error=message if not success else None,
        error_code="not_found" if not success else None,
        method_used="process_manager"
    )