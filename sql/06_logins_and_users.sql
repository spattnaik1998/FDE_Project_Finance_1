/* =====================================================================
   06 — Logins and users   *** REQUIRES MIXED-MODE AUTHENTICATION ***
   TDD 3.2. Idempotent: safe to re-run.

   DEFERRED. The instance is currently Windows-authentication only, so
   CREATE LOGIN for a SQL login will fail. Enabling mixed mode requires a
   server-level setting change AND a SQL Server service restart, which
   affects every other database on this instance.

   To enable (run as sysadmin in master, then restart the service):
       EXEC xp_instance_regwrite
            N'HKEY_LOCAL_MACHINE', N'Software\Microsoft\MSSQLServer\MSSQLServer',
            N'LoginMode', REG_DWORD, 2;
       -- then: Restart-Service MSSQLSERVER

   Passwords are placeholders. Replace them from an environment variable or
   a secret store before running; do not commit real passwords to the repo.

   All permissions already live on the ROLES (script 04). These principals
   only get membership — so the security model is already built and tested
   without this script having run.
   ===================================================================== */

USE master;
GO

IF SUSER_ID('USR_FDE_RO') IS NULL
    CREATE LOGIN USR_FDE_RO    WITH PASSWORD = '$(RO_PASSWORD)',    CHECK_POLICY = ON;
IF SUSER_ID('USR_FDE_LOAD') IS NULL
    CREATE LOGIN USR_FDE_LOAD  WITH PASSWORD = '$(LOAD_PASSWORD)',  CHECK_POLICY = ON;
IF SUSER_ID('USR_FDE_SCORE') IS NULL
    CREATE LOGIN USR_FDE_SCORE WITH PASSWORD = '$(SCORE_PASSWORD)', CHECK_POLICY = ON;
IF SUSER_ID('USR_FDE_AUDIT') IS NULL
    CREATE LOGIN USR_FDE_AUDIT WITH PASSWORD = '$(AUDIT_PASSWORD)', CHECK_POLICY = ON;
GO

/* No server-level roles. None of these principals needs anything beyond
   CONNECT plus membership in one database role. */
USE FDE_TaskExposure;
GO

IF DATABASE_PRINCIPAL_ID('USR_FDE_RO') IS NULL
    CREATE USER USR_FDE_RO    FOR LOGIN USR_FDE_RO;
IF DATABASE_PRINCIPAL_ID('USR_FDE_LOAD') IS NULL
    CREATE USER USR_FDE_LOAD  FOR LOGIN USR_FDE_LOAD;
IF DATABASE_PRINCIPAL_ID('USR_FDE_SCORE') IS NULL
    CREATE USER USR_FDE_SCORE FOR LOGIN USR_FDE_SCORE;
IF DATABASE_PRINCIPAL_ID('USR_FDE_AUDIT') IS NULL
    CREATE USER USR_FDE_AUDIT FOR LOGIN USR_FDE_AUDIT;
GO

ALTER ROLE db_fde_ro    ADD MEMBER USR_FDE_RO;
ALTER ROLE db_fde_load  ADD MEMBER USR_FDE_LOAD;
ALTER ROLE db_fde_score ADD MEMBER USR_FDE_SCORE;
ALTER ROLE db_fde_audit ADD MEMBER USR_FDE_AUDIT;
GO

/* Explicitly NOT members of db_datareader / db_datawriter / db_owner.
   The boundary is the credential, not the prompt. */
PRINT 'Logins, users and role membership applied';
GO
