"""Hard-killable process-tree containment.

A timeout on a blocking native call (e.g. a stuck ``llama.cpp`` inference)
cannot be interrupted cooperatively -- Mei has no cancellation check inside
those calls. The supervisor's only real recourse is to kill the whole
process tree it spawned. This module is the one place that knows how to do
that per platform:

- POSIX: the child is started in its own process group (``setsid``); the
  whole group is killed with ``SIGKILL`` via ``killpg``.
- Windows: the child is created *suspended*, assigned to a Job Object with
  ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``, then resumed. Doing it in that
  order (suspend -> assign -> resume) closes the race where a child could
  spawn grandchildren before containment is in place. Closing the job
  handle kills every process still in it.

Both backends are exercised by harness/tests; the Windows backend was first
validated on the target Windows 11 machine on 2026-10-25, including an
explicit check that a grandchild process dies with the job.
"""
from __future__ import annotations

import os
import platform
import signal
import subprocess
from typing import Optional, Sequence

IS_WINDOWS = platform.system() == "Windows"


class ContainedProcess:
    """A subprocess whose full process tree can be hard-killed as a unit."""

    def __init__(self, cmd: Sequence[str], **popen_kwargs):
        self._cmd = list(cmd)
        self._popen_kwargs = popen_kwargs
        self._proc: Optional[subprocess.Popen] = None
        self._job = None  # Windows job handle, if applicable

    def start(self) -> None:
        if IS_WINDOWS:
            self._start_windows()
        else:
            self._start_posix()

    def _start_posix(self) -> None:
        self._proc = subprocess.Popen(
            self._cmd,
            preexec_fn=os.setsid,
            **self._popen_kwargs,
        )

    def _start_windows(self) -> None:
        import ctypes

        import psutil

        CREATE_SUSPENDED = 0x00000004
        CREATE_NEW_PROCESS_GROUP = 0x00000200

        # 1. Create suspended -- nothing it spawns can run (or escape
        #    containment) before step 2 assigns it to the job.
        self._proc = subprocess.Popen(
            self._cmd,
            creationflags=CREATE_SUSPENDED | CREATE_NEW_PROCESS_GROUP,
            **self._popen_kwargs,
        )

        kernel32 = ctypes.windll.kernel32
        _declare_kernel32_handles(kernel32)

        self._job = kernel32.CreateJobObjectW(None, None)
        if not self._job:
            raise OSError("CreateJobObjectW failed")

        info = _JobObjectExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = kernel32.SetInformationJobObject(
            self._job,
            _JobObjectExtendedLimitInformationClass,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            raise OSError("SetInformationJobObject failed")

        PROCESS_ALL_ACCESS = 0x1F0FFF
        hproc = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, self._proc.pid)
        try:
            # 2. Assign to the job while still suspended.
            if not kernel32.AssignProcessToJobObject(self._job, hproc):
                raise OSError("AssignProcessToJobObject failed")
        finally:
            kernel32.CloseHandle(hproc)

        # 3. Only now resume -- containment is already in place.
        psutil.Process(self._proc.pid).resume()

    @property
    def pid(self) -> int:
        assert self._proc is not None
        return self._proc.pid

    def poll(self) -> Optional[int]:
        assert self._proc is not None
        return self._proc.poll()

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        """Returns the exit code, or None if `timeout` elapsed first."""
        assert self._proc is not None
        try:
            return self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def is_alive(self) -> bool:
        return self.poll() is None

    def kill_tree(self) -> None:
        """Hard-kill this process and everything it spawned.

        No graceful phase: the motivating case is a blocked native call that
        never checks for a signal anyway, so there is nothing to wait on.
        """
        if IS_WINDOWS:
            self._kill_tree_windows()
        else:
            self._kill_tree_posix()

    def _kill_tree_posix(self) -> None:
        if self._proc is None:
            return
        try:
            pgid = os.getpgid(self._proc.pid)
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    def _kill_tree_windows(self) -> None:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        _declare_kernel32_handles(kernel32)
        if self._job:
            # Closing the job handle triggers KILL_ON_JOB_CLOSE for every
            # process still assigned to it.
            kernel32.CloseHandle(self._job)
            self._job = None
        if self._proc is not None:
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass


# --- Windows ctypes structures (only ever instantiated on Windows) ---------

_JobObjectExtendedLimitInformationClass = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


def _declare_kernel32_handles(kernel32) -> None:
    """Declare HANDLE types so ctypes doesn't truncate 64-bit handles to int."""
    import ctypes
    from ctypes import wintypes

    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _build_windows_structs():
    import ctypes

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JobObjectBasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class _JobObjectExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JobObjectBasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    return _JobObjectExtendedLimitInformation


if IS_WINDOWS:
    _JobObjectExtendedLimitInformation = _build_windows_structs()
