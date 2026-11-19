"""Load the industry Skills Gap inputs and export the dashboard CSV and Top 3 report."""

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
    GapRow,
    analyze_gap,
    calculate_gap,
    gap_csv,
)
from pipeline.reviewed_postings import SNAPSHOT, reviewed_paths

ROOT = Path(__file__).resolve().parents[1]
CLEAN = Path("outputs/postings_clean.json")
RAW = Path("data/raw/job_postings_raw.json")
REVIEWED = RAW.parent / SNAPSHOT / "postings-reviewed"
PROGRAM_CATALOGS = {"AWS Skill Builder": Path("data/courses/courses.csv")}
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


def _load_programs(root: Path) -> list[dict[str, str]]:
    """Collect one record per learning program from each registered catalog."""
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
    return programs


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


def _load_inputs(root: Path, *, example: bool) -> tuple[list[dict], list[dict], str]:
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
    programs = _load_programs(root)
    providers = ", ".join(PROGRAM_CATALOGS)
    return postings, programs, f"{source} ({len(postings)}건) · {providers} (학습 프로그램 {len(programs)}개)"


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
    postings, programs, source = _load_inputs(root, example=example)
    return {"rows": calculate_gap(postings, programs), "source": source}


def _publish(path: Path, content: bytes) -> None:
    # Readers should always see one complete version, even during a rebuild.
    with TemporaryDirectory(dir=path.parent) as directory:
        temporary = Path(directory) / path.name
        temporary.write_bytes(content)
        temporary.replace(path)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="directory containing data/ and outputs/")
    parser.add_argument("--output-dir", type=Path, help="destination for both reports")
    parser.add_argument("--example", action="store_true", help="use example postings with the registered program catalogs")
    args = parser.parse_args(argv)
    try:
        postings, programs, source = _load_inputs(args.root, example=args.example)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"{exc}\n")
    result = analyze_gap(postings, programs)
    dest = args.output_dir or args.root / ("outputs/example" if args.example else "outputs")
    dest.mkdir(parents=True, exist_ok=True)
    lines = ["# 산업별 Skills Gap Top 3", "", source, ""]
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
