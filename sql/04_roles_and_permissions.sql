/* =====================================================================
   04 — Database roles and permissions
   TDD 3.2. Idempotent: safe to re-run.

   All grants live on ROLES, not on logins. Logins are merely added to a
   role (script 05). This means the entire security model is built and
   testable without mixed-mode authentication being enabled.

   The principle: the boundary is the credential, not the prompt.
   ===================================================================== */

USE FDE_TaskExposure;
GO

/* --- Roles ---------------------------------------------------------- */
IF DATABASE_PRINCIPAL_ID('db_fde_ro')    IS NULL CREATE ROLE db_fde_ro;
IF DATABASE_PRINCIPAL_ID('db_fde_load')  IS NULL CREATE ROLE db_fde_load;
IF DATABASE_PRINCIPAL_ID('db_fde_score') IS NULL CREATE ROLE db_fde_score;
IF DATABASE_PRINCIPAL_ID('db_fde_audit') IS NULL CREATE ROLE db_fde_audit;
GO
PRINT 'Roles ready: db_fde_ro, db_fde_load, db_fde_score, db_fde_audit';
GO

/* =====================================================================
   db_fde_ro — the agent runtime.
   SELECT on the five views ONLY. Every base schema is explicitly DENIED.
   DENY outranks GRANT in SQL Server, so this holds even if a future
   grant is made carelessly.
   ===================================================================== */
GRANT SELECT ON dbo.VW_ROLE_TASKS          TO db_fde_ro;
GRANT SELECT ON dbo.VW_EXPOSURE_BENCHMARK  TO db_fde_ro;
GRANT SELECT ON dbo.VW_ADOPTION_CURVE      TO db_fde_ro;
GRANT SELECT ON dbo.VW_CLAIM_EVIDENCE      TO db_fde_ro;
GRANT SELECT ON dbo.VW_INDUSTRY_METRIC     TO db_fde_ro;

DENY SELECT, INSERT, UPDATE, DELETE ON SCHEMA::ref   TO db_fde_ro;
DENY SELECT, INSERT, UPDATE, DELETE ON SCHEMA::core  TO db_fde_ro;
DENY SELECT, INSERT, UPDATE, DELETE ON SCHEMA::score TO db_fde_ro;
DENY SELECT, INSERT, UPDATE, DELETE ON SCHEMA::audit TO db_fde_ro;
DENY ALTER, CREATE TABLE, CREATE VIEW, CREATE PROCEDURE TO db_fde_ro;
GO

/* =====================================================================
   db_fde_load — offline ingestion.
   INSERT only on facts: under the append-only model a revised artefact
   produces a NEW row, so ingestion has no legitimate reason to mutate a
   fact in place. UPDATE is permitted only on ref.occupation, which is
   system-versioned and therefore keeps its own history.
   ===================================================================== */
GRANT SELECT, INSERT ON SCHEMA::ref  TO db_fde_load;
GRANT SELECT, INSERT ON SCHEMA::core TO db_fde_load;
GRANT SELECT          ON SCHEMA::score TO db_fde_load;

DENY UPDATE, DELETE ON SCHEMA::core TO db_fde_load;
DENY UPDATE, DELETE ON ref.source_document TO db_fde_load;   -- immutable snapshots
DENY DELETE ON SCHEMA::ref TO db_fde_load;
GRANT UPDATE ON ref.occupation    TO db_fde_load;            -- temporal: history retained
GRANT UPDATE ON ref.naics_sector  TO db_fde_load;

GRANT INSERT ON audit.quality_assertion TO db_fde_load;
/* Verification is an ingestion-side activity: whoever fetches the publisher's
   copy records the check. INSERT and SELECT only -- a verification record that
   can be edited afterwards proves nothing, which is the same reason
   ref.source_document is immutable in the first place. */
GRANT INSERT, SELECT ON audit.source_verification TO db_fde_load;
/* No application principal writes audit.security_event. It records privilege
   changes, which only a sysadmin can make, so only a sysadmin can record one.
   Granting INSERT to an application role would let the application fabricate
   its own security history. */
DENY SELECT, INSERT, UPDATE, DELETE ON audit.security_event TO db_fde_load;
DENY UPDATE, DELETE ON audit.source_verification TO db_fde_load;
DENY SELECT, INSERT, UPDATE, DELETE ON audit.AgentAuditLog TO db_fde_load;
GO

/* =====================================================================
   db_fde_score — the deterministic scoring service.
   Reads evidence, writes scores. UPDATE is allowed on score.run alone,
   so a run can be closed out (finished_at, status); every other scoring
   table is insert-only.
   ===================================================================== */
GRANT SELECT ON SCHEMA::ref  TO db_fde_score;
GRANT SELECT ON SCHEMA::core TO db_fde_score;
GRANT SELECT, INSERT ON SCHEMA::score TO db_fde_score;
GRANT UPDATE ON score.run TO db_fde_score;
DENY UPDATE ON score.task_score   TO db_fde_score;
DENY UPDATE ON score.role_verdict TO db_fde_score;
DENY UPDATE ON score.calibration  TO db_fde_score;
DENY DELETE ON SCHEMA::score TO db_fde_score;

GRANT INSERT, SELECT ON audit.run_source_binding TO db_fde_score;
GRANT INSERT, SELECT ON audit.quality_assertion  TO db_fde_score;
/* The scoring/report side reads verifications to decide whether a mirror still
   blocks customer delivery. Read only: it must not be able to clear its own
   blocker. */
GRANT SELECT ON audit.source_verification TO db_fde_score;
DENY SELECT, INSERT, UPDATE, DELETE ON audit.security_event TO db_fde_score;
DENY INSERT, UPDATE, DELETE ON audit.source_verification TO db_fde_score;
DENY UPDATE, DELETE ON audit.run_source_binding  TO db_fde_score;
DENY SELECT, UPDATE, DELETE ON audit.AgentAuditLog TO db_fde_score;
GO

/* =====================================================================
   db_fde_audit — the local audit adapter.
   INSERT on the decision log and NOTHING else. No orchestration node
   holds a write credential of any kind: nodes call the adapter, and the
   adapter owns this connection.
   ===================================================================== */
GRANT INSERT ON audit.AgentAuditLog TO db_fde_audit;

DENY SELECT, UPDATE, DELETE ON audit.AgentAuditLog TO db_fde_audit;
DENY SELECT, INSERT, UPDATE, DELETE ON SCHEMA::ref   TO db_fde_audit;
DENY SELECT, INSERT, UPDATE, DELETE ON SCHEMA::core  TO db_fde_audit;
DENY SELECT, INSERT, UPDATE, DELETE ON SCHEMA::score TO db_fde_audit;
DENY SELECT ON audit.run_source_binding TO db_fde_audit;
DENY SELECT ON audit.quality_assertion  TO db_fde_audit;
DENY SELECT, INSERT, UPDATE, DELETE ON audit.source_verification TO db_fde_audit;
DENY SELECT, INSERT, UPDATE, DELETE ON audit.security_event TO db_fde_audit;
GO

PRINT 'Permissions applied to all four roles';
GO
