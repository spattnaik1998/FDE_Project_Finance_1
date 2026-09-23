<#
.SYNOPSIS
    Restrict the .env file so only its owner, SYSTEM and Administrators can read it.

.DESCRIPTION
    .env inherits its ACL from the enclosing folder, which on this machine
    grants BUILTIN\Users FullControl. That means every local account can read
    the six API keys -- and, once scripts\enable_sql_auth.ps1 appends them, the
    four SQL principal passwords as well.

    Gitignoring a secrets file keeps it out of the repository. It does nothing
    about who on the machine can open it. Those are different controls for
    different threats, and only the first one was in place.

    This must run BEFORE enable_sql_auth.ps1. Appending database passwords to a
    world-readable file would take a contained problem -- API keys that can be
    rotated -- and turn it into database credentials readable by any local
    account.

    Needs no elevation: changing the ACL on a file you own is an owner right.

.NOTES
    Dry run first if you want to see the change without making it:

        powershell -File scripts\harden_secrets.ps1 -WhatIf

    To reverse (restores inheritance from the parent folder):

        icacls .env /inheritance:e
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Path = '.env'
)

$ErrorActionPreference = 'Stop'

$resolved = Resolve-Path -Path $Path -ErrorAction Stop
Write-Host "Target: $resolved"

# --- Report the current state, so the change is visible before and after ----
function Show-Acl([string]$file, [string]$label) {
    Write-Host ""
    Write-Host "$label" -ForegroundColor Cyan
    (Get-Acl $file).Access | ForEach-Object {
        $flag = if ($_.IsInherited) { 'inherited' } else { 'explicit ' }
        Write-Host ("  {0}  {1,-34} {2}" -f $flag, $_.IdentityReference, $_.FileSystemRights)
    }
}

Show-Acl $resolved 'BEFORE'

$broad = (Get-Acl $resolved).Access | Where-Object {
    $_.IdentityReference -match 'Users|Everyone|Authenticated Users' -and
    $_.AccessControlType -eq 'Allow'
}
if (-not $broad) {
    Write-Host ""
    Write-Host 'Already restricted: no broad Allow entry found. Nothing to do.' -ForegroundColor Green
    exit 0
}

Write-Host ""
Write-Host ("Found {0} broad Allow entr{1} to remove." -f $broad.Count,
    $(if ($broad.Count -eq 1) { 'y' } else { 'ies' })) -ForegroundColor Yellow

# --- Apply -----------------------------------------------------------------
# icacls rather than Set-Acl: /inheritance:r drops the inherited ACEs in one
# step, and /grant:r replaces rather than accumulates, so re-running cannot
# silently widen the result.
#
# The owner gets Read+Write, not FullControl: nothing needs to rewrite this
# file's ACL as part of normal operation, and the narrower grant is the one
# that survives review.
$account = "$env:USERDOMAIN\$env:USERNAME"

if ($PSCmdlet.ShouldProcess($resolved, "restrict ACL to $account, SYSTEM, Administrators")) {
    & icacls "$resolved" /inheritance:r `
        /grant:r "${account}:(R,W)" `
        /grant:r '*S-1-5-18:(F)' `
        /grant:r '*S-1-5-32-544:(F)' | Out-Null

    if ($LASTEXITCODE -ne 0) { throw "icacls failed with exit code $LASTEXITCODE" }

    Show-Acl $resolved 'AFTER'

    # --- Verify, rather than trust the exit code ---------------------------
    $still = (Get-Acl $resolved).Access | Where-Object {
        $_.IdentityReference -match 'Users|Everyone|Authenticated Users' -and
        $_.AccessControlType -eq 'Allow'
    }
    if ($still) {
        throw "A broad Allow entry survived: $($still.IdentityReference -join ', ')"
    }

    # The owner must still be able to read it, or the project stops working.
    try {
        [void](Get-Content $resolved -TotalCount 1 -ErrorAction Stop)
    } catch {
        throw "The file is no longer readable by its owner. Restore with: icacls `"$resolved`" /inheritance:e"
    }

    Write-Host ""
    Write-Host 'Restricted, and still readable by the owner.' -ForegroundColor Green
    Write-Host 'Reverse with:  icacls .env /inheritance:e'

    # Record it, if the warehouse is reachable. Best-effort by design: the ACL
    # change is the control, and failing to log it must not undo it or stop the
    # script. The warning makes the gap visible rather than silent.
    $actor = "$env:USERDOMAIN\$env:USERNAME"
    $env:SEC_ACTOR = $actor
    try {
        sqlcmd -S 'LAPTOP-FO95TROJ' -E -b -d 'FDE_TaskExposure' -Q @"
SET NOCOUNT ON;
INSERT INTO audit.security_event
    (event_type, actor, state_before, state_after, detail)
VALUES ('secret_acl_restricted', '`$(SEC_ACTOR)',
        'BUILTIN\Users FullControl (inherited)',
        'owner R/W, SYSTEM and Administrators full, inheritance removed',
        '.env ACL restricted by scripts/harden_secrets.ps1 before database passwords were written to it.');
"@ 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning 'ACL restricted, but the audit record could not be written.'
        }
    } catch {
        Write-Warning 'ACL restricted, but the audit record could not be written.'
    } finally {
        Remove-Item Env:SEC_ACTOR -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host 'Note: this controls who on THIS MACHINE can read the file.' -ForegroundColor Yellow
Write-Host 'It does not rotate anything. The six API keys have been readable by'
Write-Host 'every local account and the repository is public, so they should be'
Write-Host 'rotated regardless of this change.'
