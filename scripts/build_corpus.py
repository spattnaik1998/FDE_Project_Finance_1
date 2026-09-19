"""Normalise every downloaded document into one typed Corpus."""
from __future__ import annotations
import json, logging, sys
sys.path.insert(0, "src")
import pandas as pd
from config import PROJECT_ROOT, DATA_INTERIM, ensure_dirs
from documents.schemas import Corpus
from documents.adapters import onet, exposure, btos, pdf

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                    datefmt="%H:%M:%S")
LOG = logging.getLogger("build_corpus")

DOCS = PROJECT_ROOT / "data" / "docs"
TARGET_SOC = "13-2051"       # Financial and Investment Analysts
FINANCE_SECTOR = "52"


def main() -> None:
    ensure_dirs()
    docs = json.loads((DOCS / "_documents.json").read_text(encoding="utf-8"))
    corpus = Corpus(documents=docs)

    # 1. Tasks
    tasks = onet.load_tasks(DOCS / "onet_task_statements.txt",
                            DOCS / "onet_task_ratings.txt",
                            soc_prefix=TARGET_SOC,
                            source_doc_id="onet_task_statements")
    corpus.tasks = onet.attach_titles(tasks, DOCS / "onet_occupation_data.txt")

    # 2. Exposure benchmark
    corpus.exposure_estimates = exposure.load_language_modeling_aioe(
        DOCS / "felten_aioe_language_modeling.xlsx",
        source_doc_id="felten_aioe_language_modeling")

    # 3. Adoption curve
    for qid in (btos.QUESTION_CURRENT_AI, btos.QUESTION_FUTURE_AI):
        corpus.adoption_observations += btos.load_ai_adoption(
            DOCS / "btos_sector.xlsx", source_doc_id="btos_sector",
            question_id=qid, sector_filter=FINANCE_SECTOR)

    # 4. Claims from prose
    corpus.claims += pdf.find_claims(DOCS / "eloundou_gpts_are_gpts.pdf",
                                     pdf.ELOUNDOU_TOPICS, "eloundou_gpts_are_gpts")
    corpus.claims += pdf.find_claims(DOCS / "brynjolfsson_productivity_j_curve.pdf",
                                     pdf.J_CURVE_TOPICS, "brynjolfsson_productivity_j_curve")

    out = DATA_INTERIM / "corpus.json"
    out.write_text(corpus.model_dump_json(indent=2), encoding="utf-8")

    print(f"\n{'='*78}\nCORPUS BUILT\n{'='*78}")
    for k, v in corpus.summary().items():
        print(f"  {k:24s} {v}")
    print(f"\nWritten to {out}")


if __name__ == "__main__":
    main()
