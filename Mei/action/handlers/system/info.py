"""
System information tool — provides OS metrics to the planner.
"""
import os
import platform
from typing import Dict, Any, Tuple, Optional

from ....core.config import ActionResult
from ...context import ExecutionContext


GET_SYSTEM_INFO_SCHEMA = {}

def get_system_info_validate(params):
    return (True, None)

def get_system_info_execute(params, context):
    # ── Use context cwd, not os.getcwd() (v2 fix) ──
    cwd = context.get_variable("cwd", os.getcwd())

    try:
        import psutil

        drive = os.path.splitdrive(cwd)[0]
        disk_path = drive + "\\" if drive else "C:\\"

        try:
            disk = psutil.disk_usage(disk_path)
            disk_data = {
                "disk_total_gb": round(disk.total / (1024**3), 1),
                "disk_free_gb": round(disk.free / (1024**3), 1),
                "disk_percent": round(disk.used / disk.total * 100, 1),
            }
        except OSError:
            # cwd's drive is unreachable (e.g. a disconnected network/removable
            # drive) — degrade gracefully rather than failing the whole call.
            disk_data = {
                "disk_total_gb": None,
                "disk_free_gb": None,
                "disk_percent": None,
                "disk_note": f"Could not read disk usage for '{disk_path}'",
            }

        mem = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=0.5)

        data = {
            "os": platform.system(),
            "os_version": platform.version(),
            "machine": platform.machine(),
            "hostname": platform.node(),
            "python_version": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "cpu_percent": cpu_percent,
            "memory_total_gb": round(mem.total / (1024**3), 1),
            "memory_available_gb": round(mem.available / (1024**3), 1),
            "memory_percent": mem.percent,
            **disk_data,
            "cwd": cwd,
        }

    except ImportError:
        # psutil not installed — basic info only. Not a failure; the
        # planner still gets a usable, if smaller, result.
        data = {
            "os": platform.system(),
            "os_version": platform.version(),
            "machine": platform.machine(),
            "hostname": platform.node(),
            "python_version": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "cwd": cwd,
            "note": "Install psutil for CPU/memory/disk metrics",
        }

        return ActionResult(
            success=True,
            data=data,
            method_used="platform"
        )
    except Exception as e:
        return ActionResult(
            success=False,
            error=str(e),
            error_code="unavailable",
            method_used="platform"
        )

    return ActionResult(
        success=True,
        data=data,
        method_used="platform"
    )