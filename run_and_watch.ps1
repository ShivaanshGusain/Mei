<#
run_and_watch.ps1

Launches Mei (TUI or headless) normally in its own window, while this script
watches its run log (logs/run_<timestamp>.log, from Mei/core/run_logger.py)
in the background. If the log goes quiet for too long while the process is
still alive, it automatically captures a py-spy dump of EVERY thread's stack
— so a hang produces an actual stack trace on disk, without you needing to
notice in time and run py-spy yourself mid-freeze.

Mei's run_logger.py also writes a periodic faulthandler stack dump of every
thread every ~20s into logs/run_<timestamp>_stacks.log, in-process — that one
needs no external tool or admin rights at all, and is often the fastest way
to see exactly where a hang is.

It can also optionally drive Sysinternals Process Monitor for OS-level
"what process/file/registry activity happened" tracing, and ProcDump for a
full memory dump as a heavier fallback if py-spy's dumps aren't enough — both
off by default (see $procmonPath / $procdumpPath below).

Usage (from the repo root, in a normal PowerShell prompt):
    .\run_and_watch.ps1                    # headless (default)
    .\run_and_watch.ps1 -Mode tui           # TUI
    .\run_and_watch.ps1 -StallSeconds 90    # widen the "is it hung" threshold

Notes:
  - Run as Administrator if py-spy fails to attach ("permission denied" is
    the usual symptom otherwise).
  - In headless mode, going quiet just because you haven't typed the next
    command yet will ALSO trigger a dump (it can't tell "waiting for you"
    apart from "actually stuck") — that's expected, not a bug. Bump
    -StallSeconds up if that gets noisy for how you work.
  - Ctrl+C stops this watcher; Mei itself keeps running in its own window.
#>

param(
    [ValidateSet("headless", "tui")]
    [string]$Mode = "headless",
    [int]$StallSeconds = 60,
    [int]$PollSeconds = 5
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

# ---- 0. Sanity checks -------------------------------------------------------
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Could not find $python — run this from the Mei repo root with .venv already set up."
    exit 1
}

if (-not (Get-Command py-spy -ErrorAction SilentlyContinue)) {
    Write-Host "py-spy not found — installing into .venv..." -ForegroundColor Yellow
    & $python -m pip install py-spy
}

New-Item -ItemType Directory -Force -Path "logs" | Out-Null
New-Item -ItemType Directory -Force -Path "logs\hang_dumps" | Out-Null

# ---- 1. Optional: Process Monitor for OS-level activity tracing -------------
# Download Sysinternals Suite and point this at Procmon64.exe to enable.
# Left disabled by default (path won't exist) rather than guessing your setup.
$procmonPath = "C:\Sysinternals\Procmon64.exe"
$procmonTrace = "logs\procmon_{0}.pml" -f (Get-Date -Format "yyyyMMdd_HHmmss")
$procmonProc = $null
if (Test-Path $procmonPath) {
    Write-Host "Starting Process Monitor -> $procmonTrace" -ForegroundColor Cyan
    $procmonProc = Start-Process -FilePath $procmonPath `
        -ArgumentList "/AcceptEula", "/Quiet", "/Minimized", "/BackingFile", (Join-Path $root $procmonTrace) `
        -PassThru
} else {
    Write-Host "Process Monitor not found at $procmonPath — skipping OS-level tracing. (Download Sysinternals Suite and edit `$procmonPath in this script to enable.)" -ForegroundColor DarkYellow
}

# ---- 1b. Optional: ProcDump as a second stall-capture method alongside py-spy
# A full memory dump (-ma) is much heavier than a py-spy stack dump (can be
# multi-GB with local models loaded), so this stays off by default too — only
# reach for it if py-spy's dumps aren't enough to explain a hang (e.g. it's
# stuck inside a native extension with no Python frame active).
$procdumpPath = "C:\Sysinternals\procdump.exe"
$useProcdump = Test-Path $procdumpPath
if (-not $useProcdump) {
    Write-Host "ProcDump not found at $procdumpPath — will rely on py-spy + faulthandler stacks only. (Edit `$procdumpPath to enable full memory dumps on stall too.)" -ForegroundColor DarkYellow
}

# ---- 2. Launch Mei in its own window ----------------------------------------
$startBefore = Get-Date
$appArgs = if ($Mode -eq "headless") { @("app.py", "--headless") } else { @("app.py") }

Write-Host "Launching Mei ($Mode)..." -ForegroundColor Cyan
$meiProc = Start-Process -FilePath $python -ArgumentList $appArgs -PassThru
Write-Host "Mei PID: $($meiProc.Id)"

# ---- 3. Find the run log this process just created --------------------------
$logFile = $null
for ($i = 0; $i -lt 20 -and -not $logFile; $i++) {
    Start-Sleep -Seconds 1
    $candidate = Get-ChildItem "logs\run_*.log" -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -ge $startBefore } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($candidate) { $logFile = $candidate.FullName }
}
if (-not $logFile) {
    Write-Warning "Could not find a logs\run_*.log file yet — the watchdog will keep looking as it polls."
}
Write-Host "Watching log: $logFile"
Write-Host "Stall threshold: ${StallSeconds}s (checked every ${PollSeconds}s). Ctrl+C stops watching; Mei keeps running."

# ---- 4. Watchdog loop --------------------------------------------------------
$dumpCount = 0
$procdumpTaken = $false
try {
    while (-not $meiProc.HasExited) {
        Start-Sleep -Seconds $PollSeconds

        if (-not $logFile) {
            $candidate = Get-ChildItem "logs\run_*.log" -ErrorAction SilentlyContinue |
                Where-Object { $_.LastWriteTime -ge $startBefore } |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($candidate) { $logFile = $candidate.FullName }
            continue
        }

        $lastWrite = (Get-Item $logFile).LastWriteTime
        $quietFor = (Get-Date) - $lastWrite

        if ($quietFor.TotalSeconds -ge $StallSeconds) {
            $dumpCount++
            $dumpPath = "logs\hang_dumps\hang_{0}_{1}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"), $dumpCount
            Write-Host "No output for $([int]$quietFor.TotalSeconds)s — capturing py-spy dump #$dumpCount -> $dumpPath" -ForegroundColor Red
            try {
                & py-spy dump --pid $meiProc.Id *> $dumpPath
            } catch {
                Write-Warning "py-spy dump failed: $_. Try re-running this script as Administrator."
            }

            # Full memory dump only once per run, and only if ProcDump is
            # available — heavy (can be multi-GB with local models loaded),
            # so this is a "py-spy wasn't enough" fallback, not the default.
            if ($useProcdump -and -not $procdumpTaken) {
                $procdumpTaken = $true
                $dmpPath = "logs\hang_dumps\mei-hang_{0}.dmp" -f (Get-Date -Format "yyyyMMdd_HHmmss")
                Write-Host "Also capturing a full ProcDump memory dump -> $dmpPath (this can take a while and produce a large file)" -ForegroundColor Red
                try {
                    & $procdumpPath -ma $meiProc.Id (Join-Path $root $dmpPath)
                } catch {
                    Write-Warning "ProcDump failed: $_. Try re-running this script as Administrator."
                }
            }

            # Back off so a genuinely stuck process doesn't get spammed with
            # a dump every single poll interval.
            Start-Sleep -Seconds ([Math]::Max($StallSeconds, 30))
        }
    }
    Write-Host "Mei process exited (code $($meiProc.ExitCode))." -ForegroundColor Cyan
} finally {
    if ($procmonProc -and -not $procmonProc.HasExited) {
        Write-Host "Stopping Process Monitor..." -ForegroundColor Cyan
        Start-Process -FilePath $procmonPath -ArgumentList "/Terminate" -Wait
    }
    Write-Host ""
    Write-Host "=== Summary ===" -ForegroundColor Green
    Write-Host "Run log:          $logFile"
    $stacksGuess = if ($logFile) { [System.IO.Path]::ChangeExtension($logFile, $null).TrimEnd('.') + "_stacks.log" } else { $null }
    if ($stacksGuess -and (Test-Path $stacksGuess)) {
        Write-Host "Periodic stacks:  $stacksGuess  (faulthandler — every thread's exact line, every ~20s)"
    }
    Get-ChildItem "logs\hang_dumps\hang_*.log" -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "py-spy dump:      $($_.FullName)"
    }
    Get-ChildItem "logs\hang_dumps\mei-hang_*.dmp" -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "ProcDump memory:  $($_.FullName)"
    }
    if (Test-Path $procmonTrace) {
        Write-Host "Procmon trace:    $procmonTrace  (open with Process Monitor)"
    }
}
