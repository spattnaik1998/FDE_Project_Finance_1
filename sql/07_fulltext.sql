/* =====================================================================
   07 — Full-text index on claim quotes   *** REQUIRES FULLTEXT FEATURE ***
   TDD 3.1 / B.5. Needed by VW_CLAIM_EVIDENCE retrieval in P3, not by P1.

   DEFERRED. SERVERPROPERTY('IsFullTextInstalled') is currently 0. Install
   via SQL Server Setup -> Add Features -> Full-Text and Semantic Extractions.

   The architect's position (review section 4): FULLTEXT is correct at this
   corpus size. It "breaks" when retrieval QUALITY degrades, not at a row
   count -- signals being paraphrastic queries missing lexically different
   evidence, or extensive chunking replacing curated claims. Benchmark
   Recall@k before reaching for vector infrastructure.
   ===================================================================== */

USE FDE_TaskExposure;
GO

IF CAST(SERVERPROPERTY('IsFullTextInstalled') AS int) = 0
BEGIN
    PRINT 'SKIPPED: Full-Text Search is not installed on this instance.';
END
ELSE
BEGIN
    IF NOT EXISTS (SELECT 1 FROM sys.fulltext_catalogs WHERE name = 'ft_fde')
        EXEC('CREATE FULLTEXT CATALOG ft_fde AS DEFAULT');

    IF NOT EXISTS (SELECT 1 FROM sys.fulltext_indexes
                   WHERE object_id = OBJECT_ID('core.extracted_claim'))
        EXEC('CREATE FULLTEXT INDEX ON core.extracted_claim (quote)
              KEY INDEX PK_extracted_claim ON ft_fde
              WITH CHANGE_TRACKING AUTO');

    PRINT 'Full-text index ready on core.extracted_claim (quote)';
END
GO
