/* =====================================================================
   03 — Agent-visible view layer
   TDD 3.1. Idempotent: CREATE OR ALTER.

   The agent reads ONLY these five views. Base tables are DENIED to the
   read-only role, so exposing a flat view schema physically prevents
   DROP / UPDATE / DELETE and prevents reaching any unpublished column.

   Every view exposes Source_Doc_ID. That is load-bearing, not decoration:
   audit.run_source_binding records which sources a run CONSUMED, and it
   can only be populated if the retrieval layer can see the document each
   returned row resolves to.

   Views project is_current = 1 — the latest valid version. A historical
   run resolves through run_source_binding instead.
   ===================================================================== */

USE FDE_TaskExposure;
GO

CREATE OR ALTER VIEW dbo.VW_ROLE_TASKS
AS
SELECT
    t.task_id        AS Task_ID,
    t.soc_code       AS SOC_Code,
    o.title          AS Occupation,
    t.statement      AS Statement,
    t.task_type      AS Task_Type,
    t.importance     AS Importance,
    t.relevance_pct  AS Relevance_Pct,
    t.weight_source  AS Weight_Source,
    t.source_doc_id  AS Source_Doc_ID
FROM core.task AS t
JOIN ref.occupation AS o ON o.soc_code = t.soc_code
WHERE t.is_current = 1;
GO

CREATE OR ALTER VIEW dbo.VW_EXPOSURE_BENCHMARK
AS
SELECT
    e.soc_code       AS SOC_Code,
    e.measure        AS Measure,
    e.value          AS Value,
    e.percentile     AS Percentile,
    e.scale_note     AS Scale_Note,   -- never omitted: the index is meaningless without it
    e.source_doc_id  AS Source_Doc_ID
FROM core.exposure_estimate AS e
WHERE e.is_current = 1;
GO

CREATE OR ALTER VIEW dbo.VW_ADOPTION_CURVE
AS
SELECT
    a.survey         AS Survey,
    a.period_label   AS Period_Label,
    a.period_start   AS Period_Start,
    a.sector_code    AS Sector_Code,
    s.label          AS Sector_Label,
    a.question_code  AS Question_Code,
    a.answer_label   AS Answer_Label,
    a.value          AS Value,
    a.unit           AS Unit,
    a.is_suppressed  AS Is_Suppressed,  -- suppressed is MISSING, never zero
    a.source_doc_id  AS Source_Doc_ID
FROM core.adoption_observation AS a
LEFT JOIN ref.naics_sector AS s ON s.sector_code = a.sector_code
WHERE a.is_current = 1;
GO

CREATE OR ALTER VIEW dbo.VW_CLAIM_EVIDENCE
AS
SELECT
    c.claim_id       AS Claim_ID,
    c.topic          AS Topic,
    c.quote          AS Quote,       -- verbatim; Quote and Page always travel together
    c.page           AS Page,
    c.note           AS Note,
    d.title          AS Doc_Title,
    d.publisher      AS Publisher,
    d.is_mirror      AS Is_Mirror,   -- surfaced so the gate can block mirrors on delivery
    d.verified_against_publisher AS Verified_Against_Publisher,
    c.source_doc_id  AS Source_Doc_ID
FROM core.extracted_claim AS c
JOIN ref.source_document AS d ON d.doc_id = c.source_doc_id
WHERE c.is_current = 1;
GO

CREATE OR ALTER VIEW dbo.VW_INDUSTRY_METRIC
AS
SELECT
    m.provider       AS Provider,
    m.series_id      AS Series_ID,
    m.industry_code  AS Industry_Code,
    m.period         AS Period,
    m.value          AS Value,
    m.unit           AS Unit,
    m.source_doc_id  AS Source_Doc_ID
FROM core.industry_metric AS m
WHERE m.is_current = 1;
GO

PRINT 'Views ready: VW_ROLE_TASKS, VW_EXPOSURE_BENCHMARK, VW_ADOPTION_CURVE, VW_CLAIM_EVIDENCE, VW_INDUSTRY_METRIC';
GO
GO

/* Citation metadata, as a view rather than a carve-out on the base table.

   The tool surface previously whitelisted ref.source_document itself, on the
   reasoning that it is reference metadata rather than evidence and carries no
   facts. That reasoning is fine; the implementation was not. sql/04 denies
   db_fde_ro every object in SCHEMA::ref, so the tool surface and the grant
   model disagreed -- and while mixed-mode auth was off, both were satisfied
   vacuously because every connection ran as the developer. The moment real
   isolation was enabled, get_source_document broke.

   The TDD is not ambiguous about which side is right: the agent reads flat
   views and is denied every base table. So the sixth published object is a
   view like the other five, and the exception disappears rather than being
   granted. Ownership chaining means SELECT here needs no permission on the
   underlying table, which is exactly the property the view layer exists for.

   Exposes doc_id AS Source_Doc_ID for the same reason the others do: without
   it audit.run_source_binding cannot be populated from a tool result. */
CREATE OR ALTER VIEW dbo.VW_SOURCE_DOCUMENT
AS
SELECT
    d.doc_id                      AS Source_Doc_ID,
    d.doc_id,
    d.title,
    d.publisher,
    d.url,
    d.format,
    d.sha256,
    d.bytes,
    d.retrieved_at,
    d.provenance_note,
    d.is_mirror,
    d.verified_against_publisher
FROM ref.source_document AS d;
GO
PRINT 'Created dbo.VW_SOURCE_DOCUMENT';
GO
