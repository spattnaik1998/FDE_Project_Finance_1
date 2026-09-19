/* =====================================================================
   05 — Reference seed data
   Idempotent: MERGE-style guards, safe to re-run.

   ref.* holds slowly-changing entities, not facts, so it is the one place
   where updating in place is legitimate. ref.occupation is system-versioned,
   so its history is retained automatically.
   ===================================================================== */

USE FDE_TaskExposure;
GO

/* NAICS sectors used by this project. Level 2 = sector, 3 = subsector. */
MERGE ref.naics_sector AS target
USING (VALUES
    ('52',  'Finance and insurance', 2),
    ('521', 'Monetary authorities - central bank', 3),
    ('522', 'Credit intermediation and related activities', 3),
    ('523', 'Securities, commodity contracts, and other financial investments', 3),
    ('524', 'Insurance carriers and related activities', 3),
    ('525', 'Funds, trusts, and other financial vehicles', 3),
    ('51',  'Information', 2),
    ('54',  'Professional, scientific, and technical services', 2),
    ('55',  'Management of companies and enterprises', 2),
    ('00',  'Total for all sectors', 2)
) AS source (sector_code, label, level)
ON target.sector_code = source.sector_code
WHEN MATCHED AND (target.label <> source.label OR target.level <> source.level)
    THEN UPDATE SET label = source.label, level = source.level
WHEN NOT MATCHED THEN
    INSERT (sector_code, label, level)
    VALUES (source.sector_code, source.label, source.level);
GO

/* Target occupation plus the adjacent SOCs referenced by the weighting
   decision (TDD Appendix A, decision 1). has_onet_ratings records the
   source property that forced equal weighting for 13-2051. */
MERGE ref.occupation AS target
USING (VALUES
    ('13-2051.00', 'Financial and Investment Analysts', '29.3', 'Analyst',             CAST(0 AS BIT)),
    ('13-2099.01', 'Financial Quantitative Analysts',   '29.3', 'Occupational Expert',  CAST(1 AS BIT)),
    ('13-2041.00', 'Credit Analysts',                   '29.3', 'Occupational Expert',  CAST(1 AS BIT)),
    ('11-3031.00', 'Financial Managers',                '29.3', 'Incumbent',            CAST(1 AS BIT))
) AS source (soc_code, title, onet_version, domain_source, has_onet_ratings)
ON target.soc_code = source.soc_code
WHEN MATCHED AND (target.title <> source.title
               OR ISNULL(target.onet_version,'')  <> source.onet_version
               OR ISNULL(target.domain_source,'') <> source.domain_source
               OR target.has_onet_ratings <> source.has_onet_ratings)
    THEN UPDATE SET title            = source.title,
                    onet_version     = source.onet_version,
                    domain_source    = source.domain_source,
                    has_onet_ratings = source.has_onet_ratings
WHEN NOT MATCHED THEN
    INSERT (soc_code, title, onet_version, domain_source, has_onet_ratings)
    VALUES (source.soc_code, source.title, source.onet_version,
            source.domain_source, source.has_onet_ratings);
GO

PRINT 'Reference data seeded: naics_sector, occupation';
GO
