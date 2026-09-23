<#
.SYNOPSIS
    Enable mixed-mode SQL authentication and create the four FDE principals.

.DESCRIPTION
    This is the one step in the build that cannot be automated from the project,
    because it needs Administrator rights:

      1. Sets LoginMode = 2 (Windows + SQL auth) in the registry.
      2. RESTARTS the SQL Server service. This drops every open connection on
         the instance, including to the other databases hosted on it.
      3. Generates a strong password per principal and appends them to .env
         (gitignored). They are never written to the console or to the repo.
      4. Runs sql/06_logins_and_users.sql to create the logins and add them to
         the database roles that already carry the grants.

    Why it matters: until this runs, the loader and scoring service connect as
    the developer, so the DENY grants in sql/04 are built but unproven at
    runtime. src/warehouse/session.py logs a WARNING on every such run and the
    integration suite asserts the isolation is NOT in force.

.NOTES
    Run from an ELEVATED PowerShell, from the project root:

        powershell -File scripts\enable_sql_auth.ps1

    No -ExecutionPolicy Bypass: CurrentUser is already RemoteSigned, which
    permits a local unsigned script, and this file carries no mark-of-the-web.
    Bypass would weaken the policy for the whole process to buy nothing.

    To reverse: set LoginMode back to 1, restart the service, and
    DROP LOGIN each USR_FDE_* principal.
#>

[CmdletBinding()]
param(
    [string]$ServiceName = 'MSSQLSERVER',
    [string]$ServerName  = 'LAPTOP-FO95TROJ',
    [string]$Database    = 'FDE_TaskExposure',
    [switch]$SkipRestart
)

$ErrorActionPreference = 'Stop'

function Assert-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'This script must run from an elevated (Administrator) PowerShell.'
    }
}

function New-StrongPassword {
    # 28 chars from a set that satisfies SQL Server's CHECK_POLICY without
    # containing quote or backslash characters that would break a connection
    # string or a .env line.
    $alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!#%*+-=?@_'
    $bytes = New-Object byte[] 28
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    -join ($bytes | ForEach-Object { $alphabet[$_ % $alphabet.Length] })
}

Assert-Elevated
Write-Host 'Elevated: yes' -ForegroundColor Green

# --- 1. Current state -------------------------------------------------------
$mode = sqlcmd -S $ServerName -E -h -1 -W -Q `
    "SET NOCOUNT ON; SELECT CAST(SERVERPROPERTY('IsIntegratedSecurityOnly') AS int)"
Write-Host "LoginMode before: $(if ($mode -match '1') { 'Windows only' } else { 'Mixed already' })"

# --- 2. Registry ------------------------------------------------------------
$regPath = 'HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\MSSQL16.MSSQLSERVER\MSSQLServer'
if (-not (Test-Path $regPath)) {
    # Instance key names vary by version; find the one that exists.
    $regPath = (Get-ChildItem 'HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server' `
        -ErrorAction SilentlyContinue |
        Where-Object { $_.PSChildName -like 'MSSQL*.MSSQLSERVER' } |
        Select-Object -First 1).PSPath + '\MSSQLServer'
}
if (-not (Test-Path $regPath)) { throw "Could not locate the instance registry key." }

Set-ItemProperty -Path $regPath -Name 'LoginMode' -Value 2 -Type DWord
Write-Host "LoginMode set to 2 at $regPath" -ForegroundColor Green

# --- 3. Restart -------------------------------------------------------------
if ($SkipRestart) {
    Write-Warning 'Restart skipped. The change takes effect on the next service start.'
} else {
    Write-Host "Restarting $ServiceName (this drops all open connections)..."
    Restart-Service -Name $ServiceName -Force
    Start-Sleep -Seconds 5
    Write-Host "Service state: $((Get-Service $ServiceName).Status)" -ForegroundColor Green
}

# --- 4. Passwords into .env -------------------------------------------------
$envPath = Join-Path (Split-Path $PSScriptRoot -Parent) '.env'
if (-not (Test-Path $envPath)) { throw "No .env found at $envPath" }

# Refuse to write database passwords into a file every local account can read.
# .env inherits BUILTIN\Users FullControl from the enclosing folder by default,
# which would turn "API keys that can be rotated" into "database credentials
# readable by anyone with a login on this box".
$broad = (Get-Acl $envPath).Access | Where-Object {
    $_.IdentityReference -match 'Users|Everyone|Authenticated Users' -and
    $_.AccessControlType -eq 'Allow'
}
if ($broad) {
    throw ("$envPath is readable by $($broad.IdentityReference -join ', '). " +
           "Run scripts\harden_secrets.ps1 first; this script will not write " +
           "database passwords into a world-readable file.")
}
Write-Host '.env ACL: restricted (no broad Allow entry)' -ForegroundColor Green

$existing = Get-Content $envPath -Raw
$principals = @('USR_FDE_RO', 'USR_FDE_LOAD', 'USR_FDE_SCORE', 'USR_FDE_AUDIT')
$passwords = @{}

foreach ($p in $principals) {
    if ($existing -match "(?m)^\s*$($p)_PASSWORD\s*[:=]") {
        Write-Host "  $($p)_PASSWORD already present in .env; reusing it."
        $line = ($existing -split "`n" | Where-Object { $_ -match "^\s*$($p)_PASSWORD" })[0]
        $passwords[$p] = ($line -split '[:=]', 2)[1].Trim().Trim("'").Trim('"')
    } else {
        $passwords[$p] = New-StrongPassword
        Add-Content -Path $envPath -Value "$($p)_PASSWORD = '$($passwords[$p])'" -Encoding utf8
        Write-Host "  generated $($p)_PASSWORD and appended to .env" -ForegroundColor Green
    }
}

# --- 5. Create logins and users --------------------------------------------
$sqlPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'sql\06_logins_and_users.sql'
Write-Host "Applying $sqlPath ..."

# Passwords go in as ENVIRONMENT VARIABLES, not as -v arguments.
#
# sqlcmd resolves $(VAR) from the environment as well as from -v, and a command
# line is not a secret: on Windows any process able to enumerate processes can
# read another's full command line. Passing four database passwords as -v
# arguments would publish them to every process running as this user -- and this
# script runs elevated. The window is short but the exposure is avoidable.
#
# Scoped to this process and cleared in the finally block, so they do not leak
# into anything this shell launches afterwards.
try {
    $env:RO_PASSWORD    = $passwords['USR_FDE_RO']
    $env:LOAD_PASSWORD  = $passwords['USR_FDE_LOAD']
    $env:SCORE_PASSWORD = $passwords['USR_FDE_SCORE']
    $env:AUDIT_PASSWORD = $passwords['USR_FDE_AUDIT']

    sqlcmd -S $ServerName -E -b -i $sqlPath

    if ($LASTEXITCODE -ne 0) { throw "sqlcmd failed with exit code $LASTEXITCODE" }
} finally {
    Remove-Item Env:RO_PASSWORD, Env:LOAD_PASSWORD, Env:SCORE_PASSWORD, `
                Env:AUDIT_PASSWORD -ErrorAction SilentlyContinue
}

# --- 6. Verify --------------------------------------------------------------
Write-Host ''
Write-Host 'Verifying...' -ForegroundColor Cyan
sqlcmd -S $ServerName -E -Q @"
SET NOCOUNT ON;
SELECT CASE WHEN CAST(SERVERPROPERTY('IsIntegratedSecurityOnly') AS int) = 0
            THEN 'mixed mode: ON' ELSE 'mixed mode: STILL OFF' END AS auth_mode;
SELECT name AS login_created FROM sys.sql_logins WHERE name LIKE 'USR_FDE%' ORDER BY name;
USE [$Database];
SELECT dp.name AS db_user, r.name AS role_membership
FROM sys.database_role_members m
JOIN sys.database_principals r ON r.principal_id = m.role_principal_id
JOIN sys.database_principals dp ON dp.principal_id = m.member_principal_id
WHERE dp.name LIKE 'USR_FDE%' ORDER BY dp.name;
"@

# --- 7. Record the change ---------------------------------------------------
# Every other kind of evidence in this warehouse is logged. A privilege change
# should not be the exception, and "the operator remembers doing it" is not an
# audit trail. No secret goes into this record: event, actor, before/after only.
Write-Host ''
Write-Host 'Recording the change in audit.security_event ...' -ForegroundColor Cyan
$actor = "$env:USERDOMAIN\$env:USERNAME"
$env:SEC_ACTOR = $actor
try {
    sqlcmd -S $ServerName -E -b -d $Database -Q @"
SET NOCOUNT ON;
INSERT INTO audit.security_event
    (event_type, actor, state_before, state_after, detail)
VALUES ('auth_mode_changed', '`$(SEC_ACTOR)', 'windows_only', 'mixed_mode',
        'LoginMode set to 2 and the instance restarted by scripts/enable_sql_auth.ps1.');
INSERT INTO audit.security_event
    (event_type, actor, state_before, state_after, detail)
VALUES ('logins_created', '`$(SEC_ACTOR)', 'no USR_FDE logins',
        'USR_FDE_RO, USR_FDE_LOAD, USR_FDE_SCORE, USR_FDE_AUDIT',
        'Created with CHECK_POLICY=ON, no server roles, and membership only in the db_fde_* database roles that already carry the grants.');
SELECT event_id, event_type, actor FROM audit.security_event ORDER BY event_id DESC;
"@
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'Could not write the security_event record. The privilege change itself succeeded; record it manually.'
    }
} finally {
    Remove-Item Env:SEC_ACTOR -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host 'Done. Next, from the project root (non-elevated is fine):' -ForegroundColor Green
Write-Host '    python -m pytest tests/test_privileges.py -v'
Write-Host '    python scripts/verify_database.py'
