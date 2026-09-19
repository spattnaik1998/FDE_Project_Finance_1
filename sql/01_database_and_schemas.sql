/* =====================================================================
   01 — Database and schemas
   TDD Appendix B. Idempotent: safe to re-run.

   Four schemas separated by WHO MAY WRITE TO THEM. That separation is
   the security boundary described in TDD 3.2, not merely organisation.
   ===================================================================== */

IF DB_ID('FDE_TaskExposure') IS NULL
BEGIN
    PRINT 'Creating database FDE_TaskExposure';
    CREATE DATABASE FDE_TaskExposure;
END
ELSE
    PRINT 'Database FDE_TaskExposure already exists — skipping create';
GO

ALTER DATABASE FDE_TaskExposure SET RECOVERY SIMPLE;
GO

USE FDE_TaskExposure;
GO

/* Reference data: occupations, sectors, source documents. */
IF SCHEMA_ID('ref') IS NULL EXEC('CREATE SCHEMA ref');
GO

/* Normalised facts from sources. Append-only (TDD B.0). */
IF SCHEMA_ID('core') IS NULL EXEC('CREATE SCHEMA core');
GO

/* Scoring engine and model output. */
IF SCHEMA_ID('score') IS NULL EXEC('CREATE SCHEMA score');
GO

/* Run metadata, agent decision trail, quality assertions. */
IF SCHEMA_ID('audit') IS NULL EXEC('CREATE SCHEMA audit');
GO

PRINT 'Schemas ready: ref, core, score, audit';
GO
