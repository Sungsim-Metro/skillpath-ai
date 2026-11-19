"""Export learning program supply counts and industry Skills Gap results."""

import argparse
import csv
import json
import math
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.industry_gap import (
    CSV_FIELDS,
    PROGRAM_TEXT_FIELDS,
    EducationSupply,
    GapRow,
    aggregate_supply,
    analyze_gap_from_supply,
    gap_csv,
)
from pipeline.reviewed_postings import SNAPSHOT, reviewed_paths

ROOT = Path(__file__).resolve().parents[1]
CLEAN = Path("outputs/postings_clean.json")
RAW = Path("data/raw/job_postings_raw.json")
REVIEWED = RAW.parent / SNAPSHOT / "postings-reviewed"
PROGRAM_CATALOGS = {"AWS Skill Builder": Path("data/courses/courses.csv")}
SUPPLY = Path("outputs/learning_program_supply.json")
TABLE = Path("outputs/learning_program_gap_table.csv")
REPORT_NAME = "learning_program_gap_report.md"


def _records(path: Path, keys: tuple[str, ...], fields: tuple[str, ...]) -> list[dict]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"{path.name}에 {'.'.join(keys)} 필드가 필요합니다.")
        value = value[key]
    if not isinstance(value, list):
        raise ValueError(f"{path.name}의 레코드는 배열이어야 합니다.")  # noqa: TRY004 - invalid file contents
    for index, row in enumerate(value, start=1):
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in fields):
            raise ValueError(f"{path.name} {index}번째 레코드의 {', '.join(fields)} 필드를 확인하세요.")
    return value


def _clean_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&[a-z]+;", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def catalog_supply(root: Path) -> EducationSupply:
    """Count the programs in the registered catalogs without requiring job postings."""
    programs = []
    for provider, relative_path in PROGRAM_CATALOGS.items():
        path = root / relative_path
        if not path.is_file():
            raise FileNotFoundError(f"{provider}의 학습 프로그램 파일 {relative_path}을 준비하세요.")
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            missing = [field for field in PROGRAM_TEXT_FIELDS if field not in (reader.fieldnames or ())]
            if missing:
                raise ValueError(f"{relative_path}에 {', '.join(missing)} 열이 필요합니다.")
            for row in reader:
                if None in row or any(row[field] is None for field in PROGRAM_TEXT_FIELDS):
                    raise ValueError(f"{relative_path} {reader.line_num}행의 열 수를 확인하세요.")
                programs.append({field: row[field] for field in PROGRAM_TEXT_FIELDS})
    return aggregate_supply(programs, source=", ".join(PROGRAM_CATALOGS))


def _read_supply(path: Path) -> EducationSupply:
    supply = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(supply, dict) or not isinstance(supply.get("source"), str):
        raise ValueError(f"{path.name}에 공급 출처가 필요합니다.")
    total = supply.get("total_courses")
    if type(total) is not int or total < 0 or not isinstance(supply.get("skills"), list):
        raise ValueError(f"{path.name}의 전체 과정 수와 기술 목록을 확인하세요.")
    seen = set()
    for row in supply["skills"]:
        if not isinstance(row, dict) or not isinstance(row.get("skill"), str):
            raise ValueError(f"{path.name}의 기술 이름을 확인하세요.")
        skill, count = row["skill"], row.get("courses")
        if not skill.strip() or skill in seen or type(count) is not int or not 0 <= count <= total:
            raise ValueError(f"{path.name}의 기술별 과정 수 또는 중복 기술을 확인하세요.")
        seen.add(skill)
    return supply


def dashboard_supply(root: Path, *, allow_example: bool) -> EducationSupply:
    """Read the published counts, or count the available catalogs on the first run."""
    if (root / SUPPLY).is_file():
        return _read_supply(root / SUPPLY)
    sample = root / "data/sample/supply.json"
    if allow_example and sample.is_file() and not any((root / path).exists() for path in PROGRAM_CATALOGS.values()):
        return _read_supply(sample)
    return catalog_supply(root)


def _load_reviewed_postings(root: Path) -> tuple[list[dict[str, str]], str]:
    """Load each reviewed posting ID once and retain postings with no industry."""
    postings = []
    missing = 0
    for path in reviewed_paths(raw_dir=root / RAW.parent):
        row = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(row, dict) or not isinstance(row.get("text"), str):
            raise ValueError(f"{path.name}의 text 필드를 확인하세요.")  # noqa: TRY004 - invalid file contents
        industry = row.get("industry")
        if industry is not None and not isinstance(industry, str):
            raise ValueError(f"{path.name}의 industry 필드를 확인하세요.")
        if not industry or not industry.strip():
            missing += 1
            industry = "산업 미기재"
        postings.append({"industry": industry, "text": row["text"]})
    return postings, f"{REVIEWED} AI·클라우드 검토본, 공고 ID 중복 제거, 산업 미기재 {missing}건 포함"


def _load_postings(root: Path, *, example: bool) -> tuple[list[dict], str]:
    clean = ROOT / "data/sample/market_postings.json" if example else root / CLEAN
    if clean.is_file():
        postings = _records(clean, (), ("industry", "text"))
        source = "예시 공고" if example else str(CLEAN)
    elif not example and (root / RAW).is_file():
        raw = _records(root / RAW, ("response", "items"), ("indTpNm", "jobCont"))
        postings = [{"industry": row["indTpNm"], "text": _clean_text(row["jobCont"])} for row in raw]
        source = str(RAW)
    elif not example and (root / REVIEWED).exists():
        postings, source = _load_reviewed_postings(root)
    else:
        raise FileNotFoundError(f"산업별 채용공고 파일 {CLEAN}, {RAW} 또는 검토 공고 폴더 {REVIEWED}을 준비하세요.")
    return postings, f"{source} ({len(postings)}건)"


def _gap_source(posting_source: str, supply: EducationSupply) -> str:
    return f"{posting_source} · {supply['source']} (학습 프로그램 {supply['total_courses']}개)"


def _read_table(path: Path) -> list[GapRow]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(CSV_FIELDS):
            raise ValueError(f"{path.name}의 열은 {', '.join(CSV_FIELDS)} 순서여야 합니다.")
        rows = []
        for row in reader:
            try:
                demand, supply, gap = (float(row[field]) for field in CSV_FIELDS[2:])
                if None in row or not all(map(math.isfinite, (demand, supply, gap))):
                    raise ValueError
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{path.name} {reader.line_num}행의 열과 수치를 확인하세요.") from exc
            rows.append(GapRow(industry=row["industry"], skill=row["skill"],
                               demand_pct=demand, supply_pct=supply, gap_pp=gap))
        return rows


def dashboard_gap(root: Path, *, allow_example: bool) -> dict:
    """Use the learning-program export or calculate from the configured catalogs."""
    if (root / TABLE).is_file():
        return {"rows": _read_table(root / TABLE), "source": f"{TABLE} · 등록된 공급 출처 {', '.join(PROGRAM_CATALOGS)}"}
    example = allow_example and not any((root / name).exists() for name in (CLEAN, RAW, REVIEWED))
    postings, source = _load_postings(root, example=example)
    supply = dashboard_supply(root, allow_example=allow_example)
    return {"rows": analyze_gap_from_supply(postings, supply)["rows"], "source": _gap_source(source, supply)}


def _publish(path: Path, content: bytes) -> None:
    # Readers should always see one complete version, even during a rebuild.
    with TemporaryDirectory(dir=path.parent) as directory:
        temporary = Path(directory) / path.name
        temporary.write_bytes(content)
        temporary.replace(path)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="directory containing data/ and outputs/")
    parser.add_argument("--output-dir", type=Path, help="destination for the generated files")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--example", action="store_true", help="use example postings with the registered program catalogs")
    mode.add_argument("--supply-only", action="store_true", help="export program counts without job postings")
    args = parser.parse_args(argv)
    dest = args.output_dir or args.root / ("outputs/example" if args.example else "outputs")
    try:
        supply = catalog_supply(args.root)
        if not args.supply_only:
            postings, source = _load_postings(args.root, example=args.example)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"{exc}\n")
    dest.mkdir(parents=True, exist_ok=True)
    _publish(dest / SUPPLY.name, (json.dumps(supply, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(f"{dest / SUPPLY.name} (학습 프로그램 {supply['total_courses']}개)")
    if args.supply_only:
        return
    result = analyze_gap_from_supply(postings, supply)
    lines = ["# 산업별 Skills Gap Top 3", "", _gap_source(source, supply), ""]
    for industry, ranking in result["top3"].items():
        lines.extend([f"## {industry}", ""])
        lines.extend(f"{rank}. {row['skill']} {row['gap_pp']:+.1f}%p"
                     for rank, row in enumerate(ranking, start=1))
        lines.append("")
    _publish(dest / REPORT_NAME, "\n".join(lines).encode("utf-8"))
    _publish(dest / TABLE.name, gap_csv(result["rows"]))
    print(f"{dest / TABLE.name} ({len(result['rows'])}행)\n{dest / REPORT_NAME}")


if __name__ == "__main__":
    main()
