"""Audit the warehouse for the failure classes this project has actually produced.

Not a re-run of the constraint tests --- ``verify_database.py`` already proves the
schema refuses what it should. This looks for damage that is *representable*: rows
the constraints permit but that would make a figure wrong, or wrong about why it is
empty.

Every check is drawn from a defect that really happened here, which is why the list
is this specific rather than generic:

1. **Two current versions of one fact.** Append-only keeps superseded rows. A
   second ``is_current = 1`` for the same natural key would double-count in any
   aggregate, and a percentile would become an artefact of which version a query
   happened to read first.
2. **No current version at all.** The inverse, and the one demotion-before-insert
   can leave behind if it fails between the two statements. It degrades safely
   (reads as "absent") but silently, so it should be visible.
3. **Zero standing in for null.** ``score.calibration.our_percentile`` was NOT
   NULL, so an absent percentile was persisted as 0.00 with a delta of 0.00 --- a
   score at the bottom of the distribution in exact agreement with a benchmark the
   same row records it as failing to match. Fixed; this asserts it stays fixed, and
   that the coerced shape has not reappeared.
4. **A cohort mixed across classifiers.** The reference set is keyed on
   ``(cohort, classifier, rubric_version)`` precisely so a mixture is
   unrepresentable. A hardcoded model name upstream defeated that once already.
5. **Unprovenanced facts.** A foreign key makes this impossible, so a non-zero
   count here means the FK is gone.
6. **Orphaned or unhashed source documents**, and mirrors whose verification does
   not match the digest it was recorded against.
7. **Runs that persisted a verdict with no source bindings.** A figure that cannot
   name the artefacts its run consumed is unsupported for that run even when it is
   correct in general.
8. **Index coverage on the columns every read filters by.** A table scan on
   ``core.industry_metric`` (16k rows and growing) is the one query in this system
   that will degrade first.

Read-only. Runs as ``db_fde_score``, which holds SELECT on ``core`` and ``score``
and is denied every write this script has no business making.
"""

from __future__ import annotations

import argparse
import logging
import sys

sys.path.insert(0, "src")

from warehouse.session import Principal, connect

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                    datefmt="%H:%M:%S")

OK, WARN, BAD = "OK", "WARN", "BAD"

# The append-only fact tables and the natural key that identifies one fact.
# Read off sys.columns rather than written from memory: the first cut of this
# script guessed `measure` on adoption_observation and `sector_code, metric` on
# industry_metric, and an audit whose query does not compile is not an audit.
VERSIONED = {
    "core.task": "soc_code, task_id",
    "core.exposure_estimate": "soc_code, measure",
    "core.adoption_observation":
        "survey, sector_code, question_code, answer_label, period_start",
    "core.extracted_claim": "claim_id",
    "core.industry_metric": "provider, series_id, industry_code, period",
}


class Audit:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

    def record(self, area: str, verdict: str, check: str, detail: str) -> None:
        self.rows.append((area, verdict, check, detail))

    @property
    def failures(self) -> list[tuple[str, str, str, str]]:
        return [r for r in self.rows if r[1] == BAD]

    @property
    def warnings(self) -> list[tuple[str, str, str, str]]:
        return [r for r in self.rows if r[1] == WARN]


def check_versioning(cursor, audit: Audit) -> None:
    for table, key in VERSIONED.items():
        duplicates = cursor.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT {key} FROM {table} WHERE is_current = 1
                GROUP BY {key} HAVING COUNT(*) > 1) d""").fetchone()[0]
        audit.record("versioning", OK if duplicates == 0 else BAD,
                     f"{table}: one current row per key",
                     f"{duplicates} key(s) with two current versions")

        orphaned = cursor.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT {key} FROM {table}
                GROUP BY {key} HAVING SUM(CAST(is_current AS INT)) = 0) d""").fetchone()[0]
        # Expected for core.extracted_claim and nowhere else: the claim extractor
        # went from v1 to v2 and the version is part of claim_id, so every v1 key
        # is legitimately superseded by a row under a DIFFERENT key. Calling that
        # a warning every run would train the reader to skim, so it is named.
        expected = table == "core.extracted_claim"
        verdict = OK if orphaned == 0 or expected else WARN
        detail = f"{orphaned} key(s) fully superseded with no successor"
        if orphaned and expected:
            detail += " — expected: the extractor version is part of the key"
        audit.record("versioning", verdict,
                     f"{table}: every key has a current row", detail)


def check_cohort(cursor, audit: Audit) -> None:
    rows = cursor.execute("""
        SELECT cohort_name, classifier, rubric_version, COUNT(*),
               MIN(exposure_index), MAX(exposure_index)
        FROM score.cohort_index WHERE is_current = 1
        GROUP BY cohort_name, classifier, rubric_version""").fetchall()
    for cohort, classifier, rubric, count, low, high in rows:
        # A reference set below the minimum cannot yield a percentile, and one
        # whose values are all equal cannot rank anything.
        spread = float(high) - float(low)
        verdict = OK if count >= 10 and spread > 0.01 else WARN
        audit.record("cohort", verdict, f"{classifier} / {rubric}",
                     f"{count} members, index {float(low):.3f}-{float(high):.3f}")

    duplicates = cursor.execute("""
        SELECT COUNT(*) FROM (
            SELECT cohort_name, classifier, rubric_version, soc_code
            FROM score.cohort_index WHERE is_current = 1
            GROUP BY cohort_name, classifier, rubric_version, soc_code
            HAVING COUNT(*) > 1) d""").fetchone()[0]
    audit.record("cohort", OK if duplicates == 0 else BAD,
                 "no occupation appears twice in one reference set",
                 f"{duplicates} duplicate member(s)")

    # An occupation in a reference set but absent from core.task means the set
    # was built against facts that are no longer current.
    stale = cursor.execute("""
        SELECT COUNT(*) FROM score.cohort_index c
        WHERE c.is_current = 1 AND NOT EXISTS (
            SELECT 1 FROM core.task t
            WHERE t.soc_code = c.soc_code AND t.is_current = 1)""").fetchone()[0]
    audit.record("cohort", OK if stale == 0 else BAD,
                 "every cohort member still has current tasks",
                 f"{stale} member(s) with no current task rows")


def check_calibration(cursor, audit: Audit) -> None:
    # The W7 defect: an absent percentile stored as 0.00 alongside a delta of
    # 0.00 against a benchmark the same row records as unmatched.
    coerced = cursor.execute("""
        SELECT COUNT(*) FROM score.calibration
        WHERE our_percentile = 0 AND delta = 0
          AND benchmark_percentile IS NOT NULL AND benchmark_percentile <> 0
          AND outcome <> 'pass'""").fetchone()[0]
    audit.record("calibration", OK if coerced == 0 else BAD,
                 "no absent percentile stored as zero",
                 f"{coerced} row(s) with the coerced signature")

    # Arithmetic consistency: where all three are present, delta must be the
    # difference. A row that disagrees with itself is worse than a missing one.
    inconsistent = cursor.execute("""
        SELECT COUNT(*) FROM score.calibration
        WHERE our_percentile IS NOT NULL AND benchmark_percentile IS NOT NULL
          AND delta IS NOT NULL
          AND ABS(delta - (our_percentile - benchmark_percentile)) > 0.02""").fetchone()[0]
    audit.record("calibration", OK if inconsistent == 0 else BAD,
                 "delta equals ours minus benchmark",
                 f"{inconsistent} self-inconsistent row(s)")

    blank = cursor.execute("""
        SELECT COUNT(*) FROM score.calibration
        WHERE outcome <> 'pass' AND (explanation IS NULL OR LEN(explanation) = 0)
        """).fetchone()[0]
    audit.record("calibration", OK if blank == 0 else BAD,
                 "every non-pass outcome carries an explanation",
                 f"{blank} unexplained row(s)")


def check_provenance(cursor, audit: Audit) -> None:
    for table in VERSIONED:
        missing = cursor.execute(f"""
            SELECT COUNT(*) FROM {table}
            WHERE source_doc_id IS NULL OR source_doc_id = ''""").fetchone()[0]
        audit.record("provenance", OK if missing == 0 else BAD,
                     f"{table}: every fact names a source",
                     f"{missing} unprovenanced row(s)")

    unhashed = cursor.execute("""
        SELECT COUNT(*) FROM ref.source_document
        WHERE sha256 IS NULL OR LEN(sha256) <> 64""").fetchone()[0]
    audit.record("provenance", OK if unhashed == 0 else BAD,
                 "every source document carries a 64-char digest",
                 f"{unhashed} document(s) without one")

    # Which documents carry no facts, and whether that is expected.
    #
    # A blanket count was the first version and it was not actionable: 21 of 29
    # documents carry nothing, and most of them should. Catalogues and code lists
    # are consulted during ingestion to resolve names and are registered so their
    # digest is on record; they were never meant to become rows. What matters is
    # the other kind -- a data extract that was fetched, hashed and then never
    # loaded, because a figure quoted from it has no source in this warehouse.
    #
    # The Census ABS modules are exactly that case, and it was not theoretical:
    # four percentages from census_abs_workforce_impact_2018 were typed into a
    # caveat string and rendered as traced, because report/render.py attributes
    # every number in a caveat to the run's bound sources wholesale.
    reference_only = ("catalog", "codes", "metadata", "search")
    unreferenced = cursor.execute("""
        SELECT d.doc_id FROM ref.source_document d
        WHERE NOT EXISTS (SELECT 1 FROM core.task t WHERE t.source_doc_id = d.doc_id)
          AND NOT EXISTS (SELECT 1 FROM core.exposure_estimate e WHERE e.source_doc_id = d.doc_id)
          AND NOT EXISTS (SELECT 1 FROM core.adoption_observation a WHERE a.source_doc_id = d.doc_id)
          AND NOT EXISTS (SELECT 1 FROM core.extracted_claim c WHERE c.source_doc_id = d.doc_id)
          AND NOT EXISTS (SELECT 1 FROM core.industry_metric m WHERE m.source_doc_id = d.doc_id)
        ORDER BY d.doc_id""").fetchall()
    catalogues = [r[0] for r in unreferenced
                  if any(word in r[0] for word in reference_only)]
    unloaded = [r[0] for r in unreferenced if r[0] not in catalogues]
    audit.record("provenance", OK, "reference-only documents registered",
                 f"{len(catalogues)} catalogue/code list(s), never meant to be rows")
    audit.record("provenance", OK if not unloaded else WARN,
                 "no data extract is fetched but unloaded",
                 f"{len(unloaded)} unloaded: {', '.join(unloaded[:4])}"
                 f"{'…' if len(unloaded) > 4 else ''}"
                 if unloaded else "every extract carries facts")

    # A mirror is cleared only by a passing check recorded against ITS digest.
    mirrors = cursor.execute("""
        SELECT COUNT(*) FROM ref.source_document d
        WHERE d.is_mirror = 1 AND NOT EXISTS (
            SELECT 1 FROM audit.source_verification v
            WHERE v.source_doc_id = d.doc_id AND v.matched = 1
              AND v.publisher_sha256 = d.sha256)""").fetchone()[0]
    audit.record("provenance", OK if mirrors == 0 else WARN,
                 "every mirror is verified against its own digest",
                 f"{mirrors} unverified mirror(s)")


def check_runs(cursor, audit: Audit) -> None:
    unbound = cursor.execute("""
        SELECT COUNT(*) FROM score.role_verdict v
        WHERE NOT EXISTS (SELECT 1 FROM audit.run_source_binding b
                          WHERE b.run_id = v.run_id)""").fetchone()[0]
    audit.record("runs", OK if unbound == 0 else BAD,
                 "every persisted verdict bound its sources",
                 f"{unbound} verdict(s) with no bindings")

    uncaveated = cursor.execute("""
        SELECT COUNT(*) FROM score.role_verdict
        WHERE caveats IS NULL OR LEN(caveats) = 0""").fetchone()[0]
    audit.record("runs", OK if uncaveated == 0 else BAD,
                 "no caveat-free verdict",
                 f"{uncaveated} verdict(s) without caveats")

    # A verdict whose status contradicts its gate outcome. The audit record and
    # the gate disagreeing is how a rejected run comes to look like a passed one.
    contradictory = cursor.execute("""
        SELECT COUNT(*) FROM score.run r
        JOIN score.calibration c ON c.run_id = r.run_id
        WHERE r.status = 'passed' AND c.outcome = 'gate_rejected'""").fetchone()[0]
    audit.record("runs", OK if contradictory == 0 else BAD,
                 "no run stored as passed over a rejected calibration",
                 f"{contradictory} contradictory run(s)")

    orphan_scores = cursor.execute("""
        SELECT COUNT(*) FROM score.task_score s
        WHERE NOT EXISTS (SELECT 1 FROM score.run r WHERE r.run_id = s.run_id)
        """).fetchone()[0]
    audit.record("runs", OK if orphan_scores == 0 else BAD,
                 "no task score without its run",
                 f"{orphan_scores} orphan score(s)")

    # score.task_score.model is the column that attributes a figure to its
    # producer. It used to fall back to the literal "unknown" when the ledger held
    # no classifier call, which is what a baseline run looks like -- so 26 rows in
    # one run carry a placeholder instead of an attribution, written silently.
    #
    # Those rows cannot be corrected: sql/04 holds DENY UPDATE ON score.task_score
    # for db_fde_score, deliberately, because a published finding must not be
    # revisable by the tier that published it. The guardrail is behaving exactly as
    # designed, and the cost is that this particular damage is permanent.
    #
    # So the run is named here rather than left to fail the audit forever. An
    # audit with a standing failure is an audit nobody reads, and an exception
    # that is written down is not the same as one that is hidden.
    ACKNOWLEDGED = {"FB87DB0F-2F84-405D-8033-9FE3E4162FFE"}
    rows = cursor.execute("""
        SELECT CAST(run_id AS NVARCHAR(36)), COUNT(*) FROM score.task_score
        WHERE model IS NULL OR model = '' OR model = 'unknown'
        GROUP BY run_id""").fetchall()
    unexpected = [(r[0], r[1]) for r in rows if r[0].upper() not in ACKNOWLEDGED]
    known = sum(r[1] for r in rows if r[0].upper() in ACKNOWLEDGED)
    audit.record("runs", OK if not unexpected else BAD,
                 "every score names the model that produced it",
                 f"{len(unexpected)} unattributed run(s)"
                 + (f"; {known} row(s) in 1 acknowledged pre-fix run"
                    if known else ""))


def check_efficiency(cursor, audit: Audit) -> None:
    """Where this schema will degrade first, measured rather than assumed."""
    sizes = cursor.execute("""
        SELECT t.name, SUM(p.rows) AS rows
        FROM sys.tables t
        JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1)
        GROUP BY t.name ORDER BY rows DESC""").fetchall()
    largest = ", ".join(f"{name}={rows:,}" for name, rows in sizes[:4])
    audit.record("efficiency", OK, "table sizes", largest)

    # The hot filter on every read is (natural key, is_current). A heap or a
    # clustered scan on the largest table is the first thing to hurt.
    for table, columns in (("industry_metric", "industry_code"),
                           ("task", "soc_code"),
                           ("exposure_estimate", "soc_code"),
                           ("adoption_observation", "sector_code")):
        indexed = cursor.execute("""
            SELECT COUNT(*) FROM sys.indexes i
            JOIN sys.index_columns ic ON ic.object_id = i.object_id
                                     AND ic.index_id = i.index_id
            JOIN sys.columns c ON c.object_id = i.object_id
                              AND c.column_id = ic.column_id
            WHERE i.object_id = OBJECT_ID(?) AND c.name = ?""",
            f"core.{table}", columns).fetchone()[0]
        audit.record("efficiency", OK if indexed else WARN,
                     f"core.{table}: {columns} is indexed",
                     "covered" if indexed else "no index — filtered scans")

        # A FILTERED index, not is_current as a key column. The first cut of
        # this check looked for is_current among the index columns and warned on
        # four tables that were already covered -- three by a filtered index and
        # one about to be. A false warning in an audit is as harmful as a missing
        # check: it teaches the reader to skim the output.
        filtered = cursor.execute("""
            SELECT COUNT(*) FROM sys.indexes
             WHERE object_id = OBJECT_ID(?) AND has_filter = 1""",
            f"core.{table}").fetchone()[0]
        audit.record("efficiency", OK if filtered else WARN,
                     f"core.{table}: is_current is covered",
                     f"{filtered} filtered index(es)" if filtered else
                     "every read filters is_current = 1 with no filtered index")

    # Superseded weight: append-only grows, and a table that is mostly history
    # makes every current-version read pay for it.
    for table in VERSIONED:
        total, current = cursor.execute(f"""
            SELECT COUNT(*), SUM(CAST(is_current AS INT)) FROM {table}""").fetchone()
        if not total:
            continue
        share = (total - (current or 0)) / total
        # Size-aware, because the concern is cost and not proportion. Half of a
        # 42-row table being history costs nothing; a quarter of 16,000 rows
        # makes every current-version read pay for the archive.
        costly = total > 1000 and share >= 0.25
        audit.record("efficiency", WARN if costly else OK,
                     f"{table}: superseded share",
                     f"{total - (current or 0):,} of {total:,} rows "
                     f"({share:.0%}) are history")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=None)
    args = parser.parse_args()

    audit = Audit()
    with connect(Principal.SCORE, database=args.database) as conn:
        cursor = conn.cursor()
        for area in (check_versioning, check_cohort, check_calibration,
                     check_provenance, check_runs, check_efficiency):
            area(cursor, audit)

    width = 78
    last_area = None
    for area, verdict, check, detail in audit.rows:
        if area != last_area:
            print(f"\n{'=' * width}\n{area.upper()}\n{'=' * width}")
            last_area = area
        print(f"  {verdict:4s} {check:52s} {detail}")

    print(f"\n{'=' * width}")
    print(f"{len(audit.rows)} checks · {len(audit.failures)} failed · "
          f"{len(audit.warnings)} warning(s)")
    print(f"{'=' * width}")
    if audit.failures:
        print("\nFAILURES — each one means a figure could be wrong:")
        for area, _, check, detail in audit.failures:
            print(f"  {area}: {check} — {detail}")
    return 1 if audit.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
