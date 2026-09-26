/* =====================================================================
   02 — Tables
   TDD Appendix B.1-B.4. Idempotent: safe to re-run.

   Persistence model (TDD B.0): facts are NEVER updated in place.
   A revised source artefact becomes a NEW ref.source_document row with a
   new SHA-256; core rows are appended against that new source_doc_id.
   Idempotency keys on source hash + natural key, not natural key alone.
   ===================================================================== */

USE FDE_TaskExposure;
GO

/* ---------------------------------------------------------------------
   B.1  Reference and provenance
   --------------------------------------------------------------------- */

IF OBJECT_ID('ref.source_document') IS NULL
BEGIN
    CREATE TABLE ref.source_document (
        doc_id                      NVARCHAR(64)   NOT NULL,
        title                       NVARCHAR(500)  NOT NULL,
        publisher                   NVARCHAR(300)  NOT NULL,
        url                         NVARCHAR(1000) NOT NULL,
        format                      NVARCHAR(16)   NOT NULL,
        sha256                      CHAR(64)       NOT NULL,
        bytes                       BIGINT         NULL,
        retrieved_at                DATETIME2      NOT NULL,
        provenance_note             NVARCHAR(MAX)  NULL,
        is_mirror                   BIT            NOT NULL CONSTRAINT DF_srcdoc_mirror   DEFAULT 0,
        verified_against_publisher  BIT            NOT NULL CONSTRAINT DF_srcdoc_verified DEFAULT 0,
        loaded_at                   DATETIME2      NOT NULL CONSTRAINT DF_srcdoc_loaded   DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_source_document    PRIMARY KEY (doc_id),
        CONSTRAINT CK_srcdoc_format      CHECK (format IN ('pdf','xlsx','tsv','csv','markdown','html','api')),
        CONSTRAINT CK_srcdoc_sha256      CHECK (LEN(sha256) = 64),
        /* doc_id carries VERSION identity: a revised artefact is a new row,
           so the same content may never appear under two ids.             */
        CONSTRAINT UQ_srcdoc_sha256      UNIQUE (sha256)
    );
    PRINT 'Created ref.source_document';
END
GO

/* System-versioned: occupation metadata changes between O*NET releases and a
   run must be reproducible against the metadata current at execution time. */
IF OBJECT_ID('ref.occupation') IS NULL
BEGIN
    CREATE TABLE ref.occupation (
        soc_code          NVARCHAR(16)  NOT NULL,
        title             NVARCHAR(300) NOT NULL,
        onet_version      NVARCHAR(16)  NULL,
        domain_source     NVARCHAR(64)  NULL,
        has_onet_ratings  BIT           NOT NULL,
        valid_from        DATETIME2     GENERATED ALWAYS AS ROW START NOT NULL,
        valid_to          DATETIME2     GENERATED ALWAYS AS ROW END   NOT NULL,
        CONSTRAINT PK_occupation PRIMARY KEY (soc_code),
        PERIOD FOR SYSTEM_TIME (valid_from, valid_to)
    )
    WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = ref.occupation_history));
    PRINT 'Created ref.occupation (system-versioned)';
END
GO

IF OBJECT_ID('ref.naics_sector') IS NULL
BEGIN
    CREATE TABLE ref.naics_sector (
        sector_code NVARCHAR(8)   NOT NULL,
        label       NVARCHAR(300) NOT NULL,
        level       TINYINT       NOT NULL,
        CONSTRAINT PK_naics_sector PRIMARY KEY (sector_code),
        CONSTRAINT CK_naics_level  CHECK (level BETWEEN 2 AND 6)
    );
    PRINT 'Created ref.naics_sector';
END
GO

/* ---------------------------------------------------------------------
   B.2  Core facts — append-only by source version
   --------------------------------------------------------------------- */

IF OBJECT_ID('core.task') IS NULL
BEGIN
    CREATE TABLE core.task (
        task_id        NVARCHAR(32)   NOT NULL,
        soc_code       NVARCHAR(16)   NOT NULL,
        statement      NVARCHAR(1000) NOT NULL,
        task_type      NVARCHAR(32)   NULL,
        importance     DECIMAL(4,2)   NULL,
        relevance_pct  DECIMAL(5,2)   NULL,
        weight_source  NVARCHAR(32)   NOT NULL,
        source_doc_id  NVARCHAR(64)   NOT NULL,
        is_current     BIT            NOT NULL CONSTRAINT DF_task_current DEFAULT 1,
        loaded_at      DATETIME2      NOT NULL CONSTRAINT DF_task_loaded  DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_task          PRIMARY KEY (task_id, source_doc_id),
        CONSTRAINT FK_task_occ      FOREIGN KEY (soc_code)      REFERENCES ref.occupation (soc_code),
        CONSTRAINT FK_task_doc      FOREIGN KEY (source_doc_id) REFERENCES ref.source_document (doc_id),
        CONSTRAINT CK_task_stmt     CHECK (LEN(LTRIM(RTRIM(statement))) > 0),
        CONSTRAINT CK_task_imp      CHECK (importance    IS NULL OR importance    BETWEEN 0 AND 5),
        CONSTRAINT CK_task_rel      CHECK (relevance_pct IS NULL OR relevance_pct BETWEEN 0 AND 100),
        CONSTRAINT CK_task_weight   CHECK (weight_source IN ('onet','adjacent_soc','equal'))
    );
    CREATE INDEX IX_task_soc_current ON core.task (soc_code) INCLUDE (statement) WHERE is_current = 1;
    PRINT 'Created core.task';
END
GO

IF OBJECT_ID('core.exposure_estimate') IS NULL
BEGIN
    CREATE TABLE core.exposure_estimate (
        estimate_id    BIGINT IDENTITY(1,1) NOT NULL,
        soc_code       NVARCHAR(16)  NOT NULL,
        measure        NVARCHAR(64)  NOT NULL,
        value          DECIMAL(12,6) NOT NULL,
        percentile     DECIMAL(5,2)  NULL,
        scale_note     NVARCHAR(MAX) NOT NULL,
        source_doc_id  NVARCHAR(64)  NOT NULL,
        is_current     BIT           NOT NULL CONSTRAINT DF_expest_current DEFAULT 1,
        loaded_at      DATETIME2     NOT NULL CONSTRAINT DF_expest_loaded  DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_exposure_estimate PRIMARY KEY (estimate_id),
        CONSTRAINT FK_expest_doc        FOREIGN KEY (source_doc_id) REFERENCES ref.source_document (doc_id),
        /* Values are standardised relative indices, meaningless without their
           scale statement — so the column may never be blank.               */
        CONSTRAINT CK_expest_scale      CHECK (LEN(LTRIM(RTRIM(scale_note))) > 0),
        CONSTRAINT CK_expest_pct        CHECK (percentile IS NULL OR percentile BETWEEN 0 AND 100),
        CONSTRAINT UQ_expest_version    UNIQUE (soc_code, measure, source_doc_id)
    );
    PRINT 'Created core.exposure_estimate';
END
GO

IF OBJECT_ID('core.adoption_observation') IS NULL
BEGIN
    CREATE TABLE core.adoption_observation (
        observation_id BIGINT IDENTITY(1,1) NOT NULL,
        survey         NVARCHAR(32)  NOT NULL,
        period_label   NVARCHAR(16)  NOT NULL,
        period_start   DATE          NULL,
        sector_code    NVARCHAR(8)   NULL,
        question_code  NVARCHAR(16)  NOT NULL,
        answer_label   NVARCHAR(200) NOT NULL,
        value          DECIMAL(8,3)  NULL,
        unit           NVARCHAR(16)  NOT NULL CONSTRAINT DF_adopt_unit    DEFAULT 'percent',
        is_suppressed  BIT           NOT NULL CONSTRAINT DF_adopt_supp    DEFAULT 0,
        source_doc_id  NVARCHAR(64)  NOT NULL,
        is_current     BIT           NOT NULL CONSTRAINT DF_adopt_current DEFAULT 1,
        loaded_at      DATETIME2     NOT NULL CONSTRAINT DF_adopt_loaded  DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_adoption_observation PRIMARY KEY (observation_id),
        CONSTRAINT FK_adopt_doc     FOREIGN KEY (source_doc_id) REFERENCES ref.source_document (doc_id),
        CONSTRAINT FK_adopt_sector  FOREIGN KEY (sector_code)   REFERENCES ref.naics_sector (sector_code),
        /* A suppressed cell is MISSING information, never zero.            */
        CONSTRAINT CK_adopt_value   CHECK (value IS NULL OR value BETWEEN 0 AND 100),
        CONSTRAINT CK_adopt_supp    CHECK (is_suppressed = 0 OR value IS NULL),
        CONSTRAINT CK_adopt_unit    CHECK (unit IN ('percent','count')),
        CONSTRAINT UQ_adopt_version UNIQUE (survey, period_label, sector_code,
                                            question_code, answer_label, source_doc_id)
    );
    CREATE INDEX IX_adopt_curve ON core.adoption_observation (sector_code, question_code, period_start)
        INCLUDE (value, answer_label) WHERE is_current = 1;
    PRINT 'Created core.adoption_observation';
END
GO

IF OBJECT_ID('core.extracted_claim') IS NULL
BEGIN
    CREATE TABLE core.extracted_claim (
        claim_id       NVARCHAR(200) NOT NULL,   -- version-scoped: includes source_doc_id
        topic          NVARCHAR(100) NOT NULL,
        quote          NVARCHAR(MAX) NOT NULL,   -- verbatim, never paraphrased
        page           INT           NOT NULL,
        note           NVARCHAR(500) NULL,
        source_doc_id  NVARCHAR(64)  NOT NULL,
        is_current     BIT           NOT NULL CONSTRAINT DF_claim_current DEFAULT 1,
        loaded_at      DATETIME2     NOT NULL CONSTRAINT DF_claim_loaded  DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_extracted_claim PRIMARY KEY (claim_id),
        CONSTRAINT FK_claim_doc    FOREIGN KEY (source_doc_id) REFERENCES ref.source_document (doc_id),
        CONSTRAINT CK_claim_page   CHECK (page >= 1),
        /* Too short to be checkable is the same as unusable.               */
        CONSTRAINT CK_claim_quote  CHECK (LEN(LTRIM(RTRIM(quote))) >= 20)
    );
    CREATE INDEX IX_claim_topic ON core.extracted_claim (topic) WHERE is_current = 1;
    PRINT 'Created core.extracted_claim';
END
GO

IF OBJECT_ID('core.industry_metric') IS NULL
BEGIN
    CREATE TABLE core.industry_metric (
        metric_id      BIGINT IDENTITY(1,1) NOT NULL,
        provider       NVARCHAR(16)  NOT NULL,
        series_id      NVARCHAR(64)  NOT NULL,
        industry_code  NVARCHAR(16)  NULL,
        period         DATE          NOT NULL,
        value          DECIMAL(18,6) NULL,
        unit           NVARCHAR(64)  NULL,
        source_doc_id  NVARCHAR(64)  NOT NULL,
        is_current     BIT           NOT NULL CONSTRAINT DF_metric_current DEFAULT 1,
        loaded_at      DATETIME2     NOT NULL CONSTRAINT DF_metric_loaded  DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_industry_metric PRIMARY KEY (metric_id),
        CONSTRAINT FK_metric_doc      FOREIGN KEY (source_doc_id) REFERENCES ref.source_document (doc_id),
        CONSTRAINT CK_metric_provider CHECK (provider IN ('BEA','BLS','CENSUS','FRED')),
        CONSTRAINT UQ_metric_version  UNIQUE (provider, series_id, industry_code, period, source_doc_id)
    );
    PRINT 'Created core.industry_metric';
END
GO

/* ---------------------------------------------------------------------
   B.3  Scoring output
   --------------------------------------------------------------------- */

IF OBJECT_ID('score.run') IS NULL
BEGIN
    CREATE TABLE score.run (
        run_id                      UNIQUEIDENTIFIER NOT NULL CONSTRAINT DF_run_id DEFAULT NEWID(),
        started_at                  DATETIME2    NOT NULL CONSTRAINT DF_run_started DEFAULT SYSUTCDATETIME(),
        finished_at                 DATETIME2    NULL,
        git_sha                     CHAR(40)     NOT NULL,
        config_hash                 CHAR(64)     NOT NULL,
        rubric_version              NVARCHAR(16) NOT NULL,
        calibration_policy_version  NVARCHAR(32) NOT NULL,
        is_customer_deliverable     BIT          NOT NULL CONSTRAINT DF_run_deliverable DEFAULT 0,
        status                      NVARCHAR(16) NOT NULL,
        notes                       NVARCHAR(MAX) NULL,
        CONSTRAINT PK_run        PRIMARY KEY (run_id),
        CONSTRAINT CK_run_status CHECK (status IN ('running','passed','review_required','failed','gate_rejected'))
    );
    PRINT 'Created score.run';
END
GO

IF OBJECT_ID('score.task_score') IS NULL
BEGIN
    CREATE TABLE score.task_score (
        run_id             UNIQUEIDENTIFIER NOT NULL,
        task_id            NVARCHAR(32)  NOT NULL,
        source_doc_id      NVARCHAR(64)  NOT NULL,
        exposure_raw       DECIMAL(5,3)  NOT NULL,
        tacitness          DECIMAL(5,3)  NOT NULL,
        exposure_adjusted  DECIMAL(5,3)  NOT NULL,
        direction          NVARCHAR(16)  NOT NULL,
        confidence         NVARCHAR(16)  NOT NULL,
        rationale          NVARCHAR(MAX) NOT NULL,
        evidence_claim_ids NVARCHAR(MAX) NULL,
        model              NVARCHAR(64)  NOT NULL,
        prompt_version     NVARCHAR(16)  NOT NULL,
        created_at         DATETIME2     NOT NULL CONSTRAINT DF_tscore_created DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_task_score     PRIMARY KEY (run_id, task_id),
        CONSTRAINT FK_tscore_run     FOREIGN KEY (run_id) REFERENCES score.run (run_id),
        CONSTRAINT FK_tscore_task    FOREIGN KEY (task_id, source_doc_id) REFERENCES core.task (task_id, source_doc_id),
        CONSTRAINT CK_tscore_raw     CHECK (exposure_raw      BETWEEN 0 AND 1),
        CONSTRAINT CK_tscore_tacit   CHECK (tacitness         BETWEEN 0 AND 1),
        CONSTRAINT CK_tscore_adj     CHECK (exposure_adjusted BETWEEN 0 AND 1),
        CONSTRAINT CK_tscore_dir     CHECK (direction  IN ('augment','substitute','unclear')),
        CONSTRAINT CK_tscore_conf    CHECK (confidence IN ('high','medium','low')),
        CONSTRAINT CK_tscore_reason  CHECK (LEN(LTRIM(RTRIM(rationale))) > 0),
        CONSTRAINT CK_tscore_json    CHECK (evidence_claim_ids IS NULL OR ISJSON(evidence_claim_ids) = 1)
    );
    PRINT 'Created score.task_score';
END
GO

IF OBJECT_ID('score.role_verdict') IS NULL
BEGIN
    CREATE TABLE score.role_verdict (
        run_id               UNIQUEIDENTIFIER NOT NULL,
        soc_code             NVARCHAR(16)  NOT NULL,
        exposure_index       DECIMAL(5,3)  NOT NULL,
        exposure_percentile  DECIMAL(5,2)  NULL,
        lag_years_p10        DECIMAL(4,1)  NOT NULL,
        lag_years_p50        DECIMAL(4,1)  NOT NULL,
        lag_years_p90        DECIMAL(4,1)  NOT NULL,
        lag_basis            NVARCHAR(MAX) NOT NULL,
        augmentation_share   DECIMAL(5,3)  NOT NULL,
        weight_source        NVARCHAR(32)  NOT NULL,
        caveats              NVARCHAR(MAX) NOT NULL,
        created_at           DATETIME2     NOT NULL CONSTRAINT DF_verdict_created DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_role_verdict   PRIMARY KEY (run_id),
        CONSTRAINT FK_verdict_run    FOREIGN KEY (run_id)   REFERENCES score.run (run_id),
        CONSTRAINT FK_verdict_occ    FOREIGN KEY (soc_code) REFERENCES ref.occupation (soc_code),
        /* The project's guardrails, made structural: a verdict cannot exist
           without stated caveats, and a lag interval cannot be inverted.   */
        CONSTRAINT CK_verdict_caveat CHECK (LEN(LTRIM(RTRIM(caveats))) > 0),
        CONSTRAINT CK_verdict_lag    CHECK (lag_years_p10 <= lag_years_p50 AND lag_years_p50 <= lag_years_p90),
        CONSTRAINT CK_verdict_index  CHECK (exposure_index BETWEEN 0 AND 1),
        CONSTRAINT CK_verdict_weight CHECK (weight_source IN ('onet','adjacent_soc','equal'))
    );
    PRINT 'Created score.role_verdict';
END
GO

IF OBJECT_ID('score.calibration') IS NULL
BEGIN
    CREATE TABLE score.calibration (
        run_id                UNIQUEIDENTIFIER NOT NULL,
        benchmark_measure     NVARCHAR(64)  NOT NULL,
        /* NULL where the comparison is not identifiable -- see the ALTER
           below for why this is not NOT NULL with a 0.00 default. */
        benchmark_percentile  DECIMAL(5,2)  NULL,
        our_percentile        DECIMAL(5,2)  NULL,
        delta                 DECIMAL(5,2)  NULL,
        within_tolerance      BIT           NOT NULL,
        outcome               NVARCHAR(24)  NOT NULL,
        explanation           NVARCHAR(MAX) NULL,
        created_at            DATETIME2     NOT NULL CONSTRAINT DF_calib_created DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_calibration  PRIMARY KEY (run_id, benchmark_measure),
        CONSTRAINT FK_calib_run    FOREIGN KEY (run_id) REFERENCES score.run (run_id),
        CONSTRAINT CK_calib_out    CHECK (outcome IN ('pass','review_required','gate_rejected')),
        /* Calibration DISAGREEMENT must carry a documented explanation;
           that is what distinguishes it from calibration FAILURE.          */
        CONSTRAINT CK_calib_expl   CHECK (outcome <> 'review_required' OR LEN(LTRIM(RTRIM(ISNULL(explanation,'')))) > 0)
    );
    PRINT 'Created score.calibration';
END
GO

/* ---------------------------------------------------------------------
   B.4  Audit
   --------------------------------------------------------------------- */

IF OBJECT_ID('audit.AgentAuditLog') IS NULL
BEGIN
    CREATE TABLE audit.AgentAuditLog (
        entry_id         BIGINT IDENTITY(1,1) NOT NULL,
        [timestamp]      DATETIME2    NOT NULL CONSTRAINT DF_audit_ts DEFAULT SYSUTCDATETIME(),
        run_id           UNIQUEIDENTIFIER NULL,
        user_prompt      NVARCHAR(MAX) NULL,
        node_invoked     NVARCHAR(64)  NULL,
        tool_invoked     NVARCHAR(64)  NULL,
        tool_raw_output  NVARCHAR(MAX) NULL,   -- stored unmodified
        llm_decision     NVARCHAR(MAX) NULL,
        provider         NVARCHAR(16)  NULL,
        model            NVARCHAR(64)  NULL,
        prompt_version   NVARCHAR(16)  NULL,
        input_tokens     INT           NULL,
        output_tokens    INT           NULL,
        duration_ms      INT           NULL,
        status           NVARCHAR(32)  NULL,
        CONSTRAINT PK_AgentAuditLog PRIMARY KEY (entry_id)
    );
    CREATE INDEX IX_audit_run ON audit.AgentAuditLog (run_id, [timestamp]);
    PRINT 'Created audit.AgentAuditLog';
END
GO

/* status was NVARCHAR(16), which a descriptive value such as
   'rejected_unsourced_figure' overflows. SQL Server raised rather than
   truncating -- the right behaviour -- but the column was simply too narrow
   for the vocabulary the orchestration nodes need. Widened idempotently so an
   existing database is migrated rather than rebuilt. */
IF EXISTS (SELECT 1 FROM sys.columns
           WHERE object_id = OBJECT_ID('audit.AgentAuditLog')
             AND name = 'status' AND max_length < 64)
BEGIN
    ALTER TABLE audit.AgentAuditLog ALTER COLUMN status NVARCHAR(32) NULL;
    PRINT 'Widened audit.AgentAuditLog.status to NVARCHAR(32)';
END
GO

/* score.calibration.our_percentile / benchmark_percentile / delta were
   NOT NULL, which forced the writer to coerce an absent value to 0.00. On a
   single-occupation run our percentile is genuinely UNIDENTIFIABLE -- a
   percentile is a rank within a distribution, and one score has no rank -- so
   the coercion persisted "0.00" and "delta 0.00" where the truth was "no
   comparison is possible". Rendered, that reads as a score at the 0th
   percentile in perfect agreement with the benchmark, while the same row says
   it is outside tolerance. A null coerced into a number that reads as a
   finding is exactly what this schema exists to prevent, so the columns now
   admit NULL and the writer stores NULL.

   within_tolerance stays NOT NULL: it is a decision, and the decision on an
   unidentifiable comparison is a definite "no". */
IF EXISTS (SELECT 1 FROM sys.columns
           WHERE object_id = OBJECT_ID('score.calibration')
             AND name = 'our_percentile' AND is_nullable = 0)
BEGIN
    ALTER TABLE score.calibration ALTER COLUMN our_percentile       DECIMAL(5,2) NULL;
    ALTER TABLE score.calibration ALTER COLUMN benchmark_percentile DECIMAL(5,2) NULL;
    ALTER TABLE score.calibration ALTER COLUMN delta                DECIMAL(5,2) NULL;
    PRINT 'Made score.calibration percentile columns nullable (unidentifiable <> zero)';
END
GO

/* Append-only in fact, not by convention. DENY covers the application
   principals; this trigger stops anything else, including sysadmin. */
IF OBJECT_ID('audit.trg_AgentAuditLog_append_only') IS NOT NULL
    DROP TRIGGER audit.trg_AgentAuditLog_append_only;
GO
CREATE TRIGGER audit.trg_AgentAuditLog_append_only
ON audit.AgentAuditLog
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 50001, 'audit.AgentAuditLog is append-only: UPDATE and DELETE are not permitted.', 1;
END
GO
PRINT 'Created audit.trg_AgentAuditLog_append_only';
GO

/* The cohort reference set: our exposure index per occupation, under one
   classifier and one rubric.

   Calibration needs a percentile, a percentile needs a distribution, and both
   our index and the published benchmark have to be ranked within the SAME
   reference set. That reference set is expensive -- one model call per task
   across every cohort member -- so it is computed once and stored here rather
   than recomputed per run. A graph run then ranks itself against these rows.

   Keyed on (classifier, rubric_version, soc_code) because a cohort scored by
   two different classifiers is not one cohort. Mixing them would make a
   percentile an artefact of which occupation got which method, so the key
   makes that unrepresentable rather than merely discouraged. */
IF OBJECT_ID('score.cohort_index') IS NULL
BEGIN
    CREATE TABLE score.cohort_index (
        cohort_name      NVARCHAR(64)  NOT NULL,
        classifier       NVARCHAR(64)  NOT NULL,
        rubric_version   NVARCHAR(16)  NOT NULL,
        soc_code         NVARCHAR(16)  NOT NULL,
        exposure_index   DECIMAL(5,3)  NOT NULL,
        tasks_scored     INT           NOT NULL,
        source_run_id    UNIQUEIDENTIFIER NULL,
        computed_at      DATETIME2     NOT NULL CONSTRAINT DF_cohort_at DEFAULT SYSUTCDATETIME(),
        cohort_index_id  INT IDENTITY(1,1) NOT NULL,
        is_current       BIT           NOT NULL CONSTRAINT DF_cohort_current DEFAULT 1,
        superseded_at    DATETIME2     NULL,
        CONSTRAINT PK_cohort_index PRIMARY KEY (cohort_index_id),
        CONSTRAINT FK_cohort_occ   FOREIGN KEY (soc_code) REFERENCES ref.occupation (soc_code),
        CONSTRAINT CK_cohort_index CHECK (exposure_index BETWEEN 0 AND 1),
        CONSTRAINT CK_cohort_tasks CHECK (tasks_scored > 0)
    );
    PRINT 'Created score.cohort_index';
END
GO

/* Migration: append-only versioning for an existing score.cohort_index.
   Idempotent -- keyed on the absence of the column, so re-running does nothing.

   The original table had (cohort, classifier, rubric, soc) as its primary key
   and persist_cohort refreshed it with DELETE-then-INSERT. That could not run
   under real privilege isolation at all: sql/04 holds
   DENY DELETE ON SCHEMA::score TO db_fde_score, deliberately. The contradiction
   was invisible for as long as every connection fell back to the developer
   credential.

   Granting DELETE would have been the quick fix and the wrong one. A past run's
   percentile in score.calibration is only interpretable against the
   distribution it was ranked in, so deleting that distribution silently changes
   what a stored figure means -- the same defect the architect caught in core.*
   at review, in a table nobody had applied the lesson to. */
IF COL_LENGTH('score.cohort_index', 'is_current') IS NULL
BEGIN
    ALTER TABLE score.cohort_index ADD
        cohort_index_id INT IDENTITY(1,1) NOT NULL,
        is_current      BIT NOT NULL CONSTRAINT DF_cohort_current DEFAULT 1,
        superseded_at   DATETIME2 NULL;
    PRINT 'Migrated score.cohort_index to append-only versioning';
END
GO

/* Separate batches from here, and not for tidiness. SQL Server compiles a whole
   batch before executing any of it, so a statement naming a column that an
   earlier statement in the same batch adds fails on "invalid column name" --
   even when the IF around it is false and the statement would never run. The
   first cut of this migration failed exactly that way against a database where
   the column was already present. */
/* Move the primary key to the surrogate, by inspecting which columns it
   actually covers rather than by name. OBJECT_ID('PK_cohort_index', 'PK')
   returns NULL for a constraint in the score schema unless it is qualified,
   which is how the first attempt skipped the drop and then failed adding a
   second primary key. Asking sys.indexes what the key covers is both correct
   and re-runnable. */
IF EXISTS (SELECT 1
             FROM sys.indexes i
             JOIN sys.index_columns ic ON ic.object_id = i.object_id
                                      AND ic.index_id = i.index_id
             JOIN sys.columns c ON c.object_id = i.object_id
                               AND c.column_id = ic.column_id
            WHERE i.object_id = OBJECT_ID('score.cohort_index')
              AND i.is_primary_key = 1 AND c.name = 'cohort_name')
BEGIN
    ALTER TABLE score.cohort_index DROP CONSTRAINT PK_cohort_index;
    PRINT 'Dropped the natural-key primary key on score.cohort_index';
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes
                WHERE object_id = OBJECT_ID('score.cohort_index')
                  AND is_primary_key = 1)
BEGIN
    ALTER TABLE score.cohort_index
        ADD CONSTRAINT PK_cohort_index PRIMARY KEY (cohort_index_id);
    PRINT 'Created PK_cohort_index on the surrogate key';
END
GO

/* One CURRENT row per key, enforced by a filtered unique index rather than by
   the primary key. The key is still (cohort, classifier, rubric, soc) -- a
   cohort scored by two classifiers is not one cohort -- but a superseded version
   may now sit beside the current one. */
IF INDEXPROPERTY(OBJECT_ID('score.cohort_index'), 'UX_cohort_current',
                 'IndexID') IS NULL
BEGIN
    CREATE UNIQUE INDEX UX_cohort_current ON score.cohort_index
        (cohort_name, classifier, rubric_version, soc_code)
        WHERE is_current = 1;
    PRINT 'Created UX_cohort_current';
END
GO

/* Which immutable sources a run ACTUALLY CONSUMED. No source_version column:
   under append-only, source_doc_id IS the version identity (TDD 3.3). */
IF OBJECT_ID('audit.run_source_binding') IS NULL
BEGIN
    CREATE TABLE audit.run_source_binding (
        run_id         UNIQUEIDENTIFIER NOT NULL,
        source_doc_id  NVARCHAR(64) NOT NULL,
        usage_type     NVARCHAR(32) NOT NULL,
        first_used_at  DATETIME2    NOT NULL CONSTRAINT DF_binding_used DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_run_source_binding PRIMARY KEY (run_id, source_doc_id, usage_type),
        CONSTRAINT FK_binding_run  FOREIGN KEY (run_id)        REFERENCES score.run (run_id),
        CONSTRAINT FK_binding_doc  FOREIGN KEY (source_doc_id) REFERENCES ref.source_document (doc_id),
        CONSTRAINT CK_binding_use  CHECK (usage_type IN
            ('task_source','exposure_benchmark','adoption_evidence','claim_evidence','industry_metric'))
    );
    PRINT 'Created audit.run_source_binding';
END
GO

/* Security-relevant changes to the instance or the principal set.

   Everything else in this warehouse is logged -- which evidence a run
   consumed, what a model decided, whether a mirror was checked -- but the
   change that matters most to a reviewer had no record at all: enabling
   mixed-mode authentication and creating four logins. In a regulated setting
   "when was SQL auth turned on, by whom, and what did it grant" is an audit
   question, and the answer was previously a shrug plus whatever the operator
   remembered.

   Append-only for the same reason as the rest: a security log that the holder
   of the privilege can edit is not a log. Deliberately holds no secret --
   event, actor, before/after state and detail only. A password or a
   connection string in an audit table is a new exposure, not a control. */
IF OBJECT_ID('audit.security_event') IS NULL
BEGIN
    CREATE TABLE audit.security_event (
        event_id      BIGINT IDENTITY(1,1) NOT NULL,
        occurred_at   DATETIME2     NOT NULL CONSTRAINT DF_secev_at DEFAULT SYSUTCDATETIME(),
        event_type    NVARCHAR(48)  NOT NULL,
        actor         NVARCHAR(128) NOT NULL,
        state_before  NVARCHAR(256) NULL,
        state_after   NVARCHAR(256) NULL,
        detail        NVARCHAR(MAX) NULL,
        CONSTRAINT PK_security_event PRIMARY KEY (event_id),
        CONSTRAINT CK_secev_type CHECK (event_type IN
            ('auth_mode_changed','logins_created','logins_dropped',
             'role_membership_changed','secret_acl_restricted')),
        /* An actor is not optional. An unattributed security event is not an
           audit record.                                                     */
        CONSTRAINT CK_secev_actor CHECK (LEN(LTRIM(RTRIM(actor))) > 0),
        /* Cheap guard against a secret being pasted into the detail column.  */
        CONSTRAINT CK_secev_nosecret CHECK (
            detail IS NULL OR (
                detail NOT LIKE '%PASSWORD =%' AND
                detail NOT LIKE '%PASSWORD=%'  AND
                detail NOT LIKE '%sk-%'))
    );
    CREATE INDEX IX_secev_time ON audit.security_event (occurred_at DESC);
    PRINT 'Created audit.security_event';
END
GO

/* A verification EVENT, not a correction to the artefact.

   ref.source_document is deliberately immutable -- db_fde_load holds
   DENY UPDATE on it, because a snapshot whose digest can be edited is not a
   snapshot. So "this mirror was checked against the publisher" cannot be
   recorded by flipping verified_against_publisher: that would require
   mutating the very row whose immutability the provenance chain rests on.

   It is also the wrong shape. A verification has a time, a method, a
   counterpart URL and an outcome, and it can be repeated -- a source that
   matched last month may not match today if the publisher revises it. A
   boolean cannot hold that; an append-only log of checks can, including a
   later FAILED check sitting next to an earlier passing one. */
IF OBJECT_ID('audit.source_verification') IS NULL
BEGIN
    CREATE TABLE audit.source_verification (
        verification_id   BIGINT IDENTITY(1,1) NOT NULL,
        source_doc_id     NVARCHAR(64)   NOT NULL,
        verified_at       DATETIME2      NOT NULL CONSTRAINT DF_srcver_at DEFAULT SYSUTCDATETIME(),
        method            NVARCHAR(32)   NOT NULL,
        publisher_url     NVARCHAR(1000) NOT NULL,
        publisher_sha256  CHAR(64)       NOT NULL,
        matched           BIT            NOT NULL,
        note              NVARCHAR(MAX)  NULL,
        CONSTRAINT PK_source_verification PRIMARY KEY (verification_id),
        CONSTRAINT FK_srcver_doc    FOREIGN KEY (source_doc_id) REFERENCES ref.source_document (doc_id),
        CONSTRAINT CK_srcver_sha    CHECK (LEN(publisher_sha256) = 64),
        CONSTRAINT CK_srcver_method CHECK (method IN ('sha256_match','manual_spot_check')),
        /* A passing check must carry the publisher URL it was checked against.
           "Verified" with no counterpart named is not a verification.        */
        CONSTRAINT CK_srcver_url    CHECK (matched = 0 OR LEN(LTRIM(RTRIM(publisher_url))) > 0)
    );
    CREATE INDEX IX_srcver_doc ON audit.source_verification (source_doc_id, verified_at DESC);
    PRINT 'Created audit.source_verification';
END
GO

IF OBJECT_ID('audit.quality_assertion') IS NULL
BEGIN
    CREATE TABLE audit.quality_assertion (
        assertion_id BIGINT IDENTITY(1,1) NOT NULL,
        run_id       UNIQUEIDENTIFIER NULL,
        check_name   NVARCHAR(100) NOT NULL,
        target       NVARCHAR(200) NOT NULL,
        passed       BIT           NOT NULL,
        observed     NVARCHAR(500) NULL,
        checked_at   DATETIME2     NOT NULL CONSTRAINT DF_qa_checked DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_quality_assertion PRIMARY KEY (assertion_id)
    );
    CREATE INDEX IX_qa_failed ON audit.quality_assertion (check_name, checked_at) WHERE passed = 0;
    PRINT 'Created audit.quality_assertion';
END
GO
