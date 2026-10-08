"""Current-user scheduled task for the loopback Chrome identity service."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

TASK_NAME = "FramefetchIdentityService"


def manage_service(backend: Path, env_file: Path | None = None) -> None:
    script = """
$ErrorActionPreference = 'Stop'
$name = 'FramefetchIdentityService'
$description = 'Framefetch Chrome identity service'
$prefix = '-m app.workers.identity.cli run --env-file '
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$tasks = @(Get-ScheduledTask -TaskPath '\\' -ErrorAction Stop |
    Where-Object { $_.TaskName -eq $name })
if ($tasks.Count -gt 1) { exit 2 }
$task = if ($tasks.Count -eq 1) { $tasks[0] } else { $null }
if ($null -ne $task) {
    $principal = [Security.Principal.NTAccount]::new($task.Principal.UserId)
    try { $owner = $principal.Translate([Security.Principal.SecurityIdentifier]).Value }
    catch { $owner = $task.Principal.UserId }
    if ($owner -ne $sid.Value -or $task.Description -ne $description -or
        @($task.Actions).Count -ne 1 -or
        -not $task.Actions[0].Arguments.StartsWith($prefix)) {
        exit 2
    }
    $task | Stop-ScheduledTask
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        $task = Get-ScheduledTask -TaskPath '\\' -TaskName $name
        if ($task.State -ne 'Running') { break }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($task.State -eq 'Running') { exit 2 }
}
if ($env:FRAMEFETCH_IDENTITY_SERVICE_ACTION -eq 'uninstall') {
    if ($null -ne $task) { $task | Unregister-ScheduledTask -Confirm:$false }
    exit 0
}
$action = New-ScheduledTaskAction -Execute $env:FRAMEFETCH_IDENTITY_PYTHON `
    -Argument $env:FRAMEFETCH_IDENTITY_ARGUMENTS `
    -WorkingDirectory $env:FRAMEFETCH_IDENTITY_BACKEND
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $sid.Value
$principal = New-ScheduledTaskPrincipal -UserId $sid.Value `
    -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
    -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 999 -Hidden
Register-ScheduledTask -TaskPath '\\' -TaskName $name -Description $description `
    -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskPath '\\' -TaskName $name
"""
    python = backend / ".venv/Scripts/pythonw.exe"
    if env_file is not None and not python.is_file():
        raise ValueError("cookie_source_windows_python_missing")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env={
            **{k: v for k, v in os.environ.items() if k.lower() != "psmodulepath"},
            "FRAMEFETCH_IDENTITY_SERVICE_ACTION": (
                "install" if env_file is not None else "uninstall"
            ),
            "FRAMEFETCH_IDENTITY_PYTHON": str(python),
            "FRAMEFETCH_IDENTITY_BACKEND": str(backend),
            "FRAMEFETCH_IDENTITY_ARGUMENTS": subprocess.list2cmdline(
                [
                    "-m",
                    "app.workers.identity.cli",
                    "run",
                    "--env-file",
                    str(env_file) if env_file is not None else "",
                ]
            ),
        },
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=20,
    )
    if result.returncode:
        raise ValueError("cookie_source_windows_service_failed")
