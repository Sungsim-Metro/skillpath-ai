"""Build repeatable Lambda ZIPs from runtime code and explicitly selected data."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
COMMON = (
    "ai/__init__.py",
    "ai/bedrock.py",
    "ai/usage.py",
    "backend/__init__.py",
    "backend/dynamodb.py",
    "backend/jobs.py",
    "pipeline/__init__.py",
)
TOOLS = (
    "backend/api.py",
    "backend/levels.py",
    "backend/lambda_tools.py",
    "pipeline/aliases.py",
    "pipeline/search.py",
    "pipeline/courses/queries.csv",
    "pipeline/courses/queries_ai_engineer.csv",
    "data/aliases.json",
    "data/skill_areas.json",
    "data/skill_areas_ai_engineer.json",
    "data/skill_levels.json",
    "data/skill_levels_ai_engineer.json",
    "data/required_levels.json",
)
RECOMMEND = (
    "pipeline/embed.py",
    "pipeline/rocketpunch.py",
    "pipeline/reviewed_postings.py",
    "pipeline/storage.py",
    "backend/experiments.py",
    "ai/recommend.py",
    "ai/recommend_review.py",
    "ai/prompts/__init__.py",
    "ai/prompts/recommend_v1.py",
    "data/courses/course_subskill.csv",
    "data/courses/courses.csv",
    "data/courses/catalog_all.csv",
    "data/foundation_courses.json",
)
BATCH = (
    "ai/extract.py",
    "ai/evidence.py",
    "ai/sections.py",
    "ai/prompts/__init__.py",
    "ai/prompts/extract_v1.py",
    "ai/prompts/extract_v2.py",
    "ai/prompts/extract_v2_1.py",
    "backend/demand.py",
    "pipeline/serverless_batch.py",
    "pipeline/extraction_batch.py",
    "pipeline/batch_manifest.py",
    "pipeline/reviewed_postings.py",
    "pipeline/storage.py",
    "pipeline/standardize.py",
    "pipeline/ncs.py",
    "pipeline/aliases.py",
    "pipeline/search.py",
    "pipeline/rocketpunch.py",
    "pipeline/courses/queries.csv",
    "pipeline/courses/queries_ai_engineer.csv",
    "data/aliases.json",
    "data/skill_areas.json",
    "data/skill_areas_ai_engineer.json",
    "data/ncs_subskill.json",
    "data/ncs_units.json",
)


def build(stage: str, destination: Path) -> str:
    """Write a ZIP atomically; its digest identifies the S3 object used by CloudFormation."""
    files = COMMON + (BATCH if stage == "preprocessing" else TOOLS)
    if stage == "recommend":
        files += RECOMMEND
    if stage != "preprocessing" and (ROOT / "data/required_levels_ai_engineer.json").is_file():
        files += ("data/required_levels_ai_engineer.json",)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        archive = Path(tmp) / "runtime.zip"
        with zipfile.ZipFile(archive, "w") as out:
            for name in sorted(set(files)):
                info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
                info.external_attr = 0o100644 << 16
                out.writestr(info, (ROOT / name).read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        os.replace(archive, destination)
    return digest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("demand", "preprocessing", "recommend"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(build(args.stage, args.output))
