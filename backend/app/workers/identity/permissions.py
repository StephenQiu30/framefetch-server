"""Owner-only identity files on POSIX and Windows, without exposing their contents."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def require_plain_path(path: Path) -> None:
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or ancestor.is_junction():
            raise ValueError("identity_directory_symlink")


def windows_permissions(path: Path, *, protect: bool = False) -> None:
    # Paths are data, never interpolated into PowerShell source. No file contents
    # are read or returned. SYSTEM is the only additional trusted principal.
    script = """
$ErrorActionPreference = 'Stop'
$path = $env:FRAMEFETCH_IDENTITY_PRIVATE_PATH
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$system = [Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$full = [Security.AccessControl.FileSystemRights]::FullControl
$acl = Get-Acl -LiteralPath $path
if ($env:FRAMEFETCH_IDENTITY_PROTECT -eq '1') {
    if ((Get-Item -LiteralPath $path).PSIsContainer) {
        $acl = [Security.AccessControl.DirectorySecurity]::new()
        $inherit = [Security.AccessControl.InheritanceFlags]'ContainerInherit,
            ObjectInherit'
    } else {
        $acl = [Security.AccessControl.FileSecurity]::new()
        $inherit = [Security.AccessControl.InheritanceFlags]::None
    }
    $acl.SetOwner($sid)
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($principal in @($sid, $system)) {
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $principal, 'FullControl', $inherit, 'None', 'Allow')
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $path -AclObject $acl
    $acl = Get-Acl -LiteralPath $path
}
if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $sid.Value) {
    exit 2
}
$rules = @($acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
if ($rules.Count -eq 0) { exit 2 }
$owned = $false
foreach ($rule in $rules) {
    if ($rule.AccessControlType -ne 'Allow' -or
        $rule.IdentityReference.Value -notin @($sid.Value, $system.Value)) { exit 2 }
    if ($rule.IdentityReference.Value -eq $sid.Value -and
        ($rule.FileSystemRights -band $full) -eq $full) { $owned = $true }
}
if (-not $owned) { exit 2 }
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env={
            **{k: v for k, v in os.environ.items() if k.lower() != "psmodulepath"},
            "FRAMEFETCH_IDENTITY_PRIVATE_PATH": str(path.absolute()),
            "FRAMEFETCH_IDENTITY_PROTECT": "1" if protect else "0",
        },
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=10,
    )
    if result.returncode:
        raise ValueError("cookie_source_env_requires_owner_only_permissions")


def require_private_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError("cookie_source_env_requires_owner_only_permissions")
    require_plain_path(path)
    if sys.platform == "win32":
        windows_permissions(path)
    else:
        metadata = path.lstat()
        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise ValueError("cookie_source_env_requires_owner_only_permissions")


def private_directory(path: Path) -> None:
    require_plain_path(path)
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if sys.platform == "win32":
        windows_permissions(path, protect=True)
    else:
        if path.stat().st_uid != os.getuid():
            raise ValueError("identity_directory_owner")
        path.chmod(0o700)


def private_write(path: Path, content: str) -> None:
    require_plain_path(path)
    if sys.platform == "win32":
        if path.exists():
            require_private_file(path)
        else:
            # Secure the empty file before writing any secret bytes.
            with path.open("x", encoding="utf-8"):
                pass
        windows_permissions(path, protect=True)
        path.write_text(content, encoding="utf-8")
    else:
        if path.exists() and path.stat().st_uid != os.getuid():
            raise ValueError("identity_file_owner")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(path, flags, 0o600), "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
