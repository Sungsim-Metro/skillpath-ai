"""추천 이유 LLM 채점과 사람 재채점 일치율 (2026-11-16 결정). 개발 중에 돌리는 평가이고 서비스 실행 경로가 아니다.

실행 (저장소 루트에서. 채점 기준표와 절차는 ai/eval/JUDGE.md)
  python -m ai.eval.judge run                      추천을 만들고 LLM 이 채점한다. 결과와 사람 재채점 양식을 outputs/eval/ 에 쓴다
      --skills Docker Kubernetes ...               채점할 부족 기술 (기본: data/sample/demand.json 의 기술 전부)
      --modes single debate                        단일 추천과 토론 추천(ai/debate.py 가 있을 때)을 같은 입력으로 비교한다
      --human 10                                   사람 재채점 양식에 넣을 항목 수 (기본 10, 무작위지만 --seed 로 고정)
  python -m ai.eval.judge agree <결과.json> <사람이 채운 양식.csv>
                                                   LLM 채점과 사람 채점의 일치율을 계산한다
  python -m ai.eval.judge cases                    지금 가진 평가 케이스 수를 센다(추출 정답 항목 + 채점 항목)

실제 모드: BEDROCK_MOCK=0 과 BEDROCK_MODEL_ID 가 필요하다. 기술·모드마다 채점 호출 1번(추천 호출은 별도).
JUDGE_MODEL_ID 를 주면 채점만 그 모델로 한다. 추천을 쓴 모델이 자기 글을 채점하면 후하게 줄 수 있어서다.

세기는 전부 코드로 한다: 평균, 합계, 일치율, 단일 대 토론 비교. LLM 은 항목마다 0·1·2 점만 매긴다.
수요 숫자는 가짜 data/sample/demand.json 에서 가져온다(ai/eval/recommend_demo.py 와 같다).
결과 원본은 outputs/eval/ 에 저장한다(.gitignore 대상).
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")  # 이미 설정된 환경 변수는 덮어쓰지 않는다
except ImportError:
    pass

import ai.recommend as rec  # noqa: E402
from ai.bedrock import USAGE_KEYS, BedrockJSONError, ConverseResult, add_usage, converse_json, is_mock  # noqa: E402
from ai.prompts import judge_v1  # noqa: E402

DEMAND = ROOT / "data" / "sample" / "demand.json"
GOLD_FILES = (ROOT / "ai" / "eval" / "gold_extraction.json", ROOT / "data" / "raw" / "eval_test" / "gold_test.json")
OUT_DIR = ROOT / "outputs" / "eval"
MOCK_FILE = "mock_bedrock_judge.json"
CRITERIA = judge_v1.CRITERIA
SCORES = (0, 1, 2)
HUMAN_COLUMNS = ["item_id", "skill", "title", "level", "prerequisites", "objectives", "reason", *CRITERIA, "memo"]


def demand_table() -> dict:
    return json.loads(DEMAND.read_text(encoding="utf-8"))


def demand_of(skill: str, table: dict) -> dict:
    s = next(x for x in table["skills"] if x["skill"] == skill)
    return {"postings": s["postings"], "of": table["total_postings"],
            "required_ratio": round(s["required"] / s["postings"], 2) if s["postings"] else 0}


def available_modes() -> list[str]:
    try:
        import ai.debate  # noqa: F401
    except ImportError:
        return ["single"]
    return ["single", "debate"]


@contextlib.contextmanager
def _env(**values):
    old = {k: os.environ.get(k) for k in values}
    os.environ.update({k: v for k, v in values.items() if v is not None})
    try:
        yield
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def recommend(skill: str, demand: dict, mode: str):
    """mode 에 맞는 추천 1건. debate 는 ai/debate.py(추천 → 검증 → 수정 → 코드 결정)를 켜고 부른다."""
    if mode == "single":
        return rec.build_recommendation(skill, demand)
    import ai.debate as debate

    with _env(RECOMMEND_DEBATE="1"):
        return debate.build_recommendation(skill, demand)


def items_of(skill: str, mode: str, recommendation: dict) -> list[dict]:
    """추천 1건을 채점 항목으로 푼다. 항목 = (기술, 모드, 과정)."""
    objectives = {(c["title"], c["url"]): c["objectives"] for c in rec.candidate_courses(skill)}
    return [
        {
            "skill": skill, "mode": mode, "title": c["title"], "level": c["level"], "prerequisites": c["prerequisites"],
            "objectives": objectives[(c["title"], c["url"])], "reason": c["reason"], "match": c["match"],
            "review_status": (c.get("review") or {}).get("status"),
        }
        for c in recommendation["courses"]
    ]


def validate_scores(data: dict, item_ids: list[str]) -> None:
    scores = data.get("scores")
    if not isinstance(scores, list):
        raise ValueError('"scores" 목록이 없습니다')
    got = [s.get("item_id") if isinstance(s, dict) else None for s in scores]
    if got != item_ids:
        raise ValueError(f"item_id 가 입력과 다릅니다: 입력 {item_ids}, 응답 {got}")
    for s in scores:
        for k in CRITERIA:
            if type(s.get(k)) is not int or s[k] not in SCORES:
                raise ValueError(f"{s['item_id']} 의 {k} 가 {s.get(k)!r} 입니다. 0, 1, 2 중 하나여야 합니다")
        if s.get("note") is not None and not isinstance(s["note"], str):
            raise ValueError(f"{s['item_id']} 의 note 는 문자열이나 null 이어야 합니다")


def _mock_keys() -> frozenset[str]:
    table = json.loads((rec.SAMPLE_DIR / MOCK_FILE).read_text(encoding="utf-8"))
    return frozenset(k for k in table if k not in ("_note", "default"))


def judge(skill: str, items: list[dict]) -> ConverseResult:
    """한 기술·한 모드의 항목들을 한 번에 채점한다. 채점자는 어느 모드의 추천인지 모른다(입력에 넣지 않는다)."""
    judge_input = {
        "skill": skill,
        "items": [{k: it[k] for k in ("item_id", "title", "level", "prerequisites", "objectives", "reason")} for it in items],
    }
    ids = [it["item_id"] for it in items]
    key = f"{skill}:{items[0]['mode']}"
    if is_mock() and key not in _mock_keys():  # 가짜 모드에서 응답 예시가 없으면 모두 2점. 결과에 mock 이라고 남는다
        data = {"scores": [{"item_id": i, **{k: 2 for k in CRITERIA}, "note": None} for i in ids]}
        return ConverseResult(data, 1, {k: 0 for k in USAGE_KEYS}, ())
    with _env(BEDROCK_MODEL_ID=os.getenv("JUDGE_MODEL_ID") or None):
        return converse_json(judge_v1.SYSTEM, judge_v1.user_message(judge_input), mock_file=MOCK_FILE, mock_key=key,
                             validate=lambda data: validate_scores(data, ids), max_tokens=2048)


def summarize(items: list[dict]) -> dict:
    """모드별 평균(0~2)과 항목 수. 코드로 계산한다."""
    out = {}
    for mode in sorted({it["mode"] for it in items}):
        rows = [it for it in items if it["mode"] == mode and it.get("scores")]
        out[mode] = {
            "n": len(rows),
            **{k: round(sum(r["scores"][k] for r in rows) / len(rows), 2) if rows else None for k in CRITERIA},
            "total": round(sum(sum(r["scores"][k] for k in CRITERIA) for r in rows) / len(rows), 2) if rows else None,
            "uncertain": sum(r["match"] == "uncertain" for r in rows),
        }
    return out


def paired_change(items: list[dict]) -> dict | None:
    """같은 (기술, 과정)에 단일과 토론 점수가 모두 있을 때, 토론 쪽이 높아진·같은·낮아진 항목 수."""
    by = {}
    for it in items:
        if it.get("scores"):
            by.setdefault((it["skill"], it["title"]), {})[it["mode"]] = sum(it["scores"][k] for k in CRITERIA)
    pairs = [(v["single"], v["debate"]) for v in by.values() if {"single", "debate"} <= set(v)]
    if not pairs:
        return None
    return {"pairs": len(pairs), "higher": sum(d > s for s, d in pairs), "same": sum(d == s for s, d in pairs),
            "lower": sum(d < s for s, d in pairs)}


def print_summary(summary: dict, change: dict | None) -> None:
    names = {r[0]: r[1] for r in judge_v1.RUBRIC}
    print(f"\n{'모드':8} {'항목':>4} " + " ".join(f"{names[k]:>10}" for k in CRITERIA) + f" {'합계(0~6)':>10} {'불확실':>6}")
    for mode, row in summary.items():
        cells = " ".join(f"{'-' if row[k] is None else format(row[k], '.2f'):>12}" for k in CRITERIA)
        print(f"{mode:8} {row['n']:>6} {cells} {'-' if row['total'] is None else format(row['total'], '.2f'):>12} {row['uncertain']:>8}")
    if change:
        print(f"같은 과정 {change['pairs']}쌍에서 토론 추천의 합계가 높아짐 {change['higher']} / 같음 {change['same']} / 낮아짐 {change['lower']}")


def write_human_sheet(path: Path, items: list[dict], n: int, seed: int) -> list[str]:
    """사람 재채점 양식. LLM 점수와 모드는 넣지 않는다(보고 따라 매기지 않게). 고른 item_id 목록을 돌려준다."""
    scored = [it for it in items if it.get("scores")]
    picked = random.Random(seed).sample(scored, min(n, len(scored)))
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HUMAN_COLUMNS)
        w.writeheader()
        for it in picked:
            w.writerow({"item_id": it["item_id"], "skill": it["skill"], "title": it["title"], "level": it["level"],
                        "prerequisites": it["prerequisites"], "objectives": " / ".join(it["objectives"]),
                        "reason": it["reason"], **{k: "" for k in CRITERIA}, "memo": ""})
    return [it["item_id"] for it in picked]


def run(args) -> int:
    table = demand_table()
    skills = args.skills or [s["skill"] for s in table["skills"]]
    modes = [m for m in args.modes if m in available_modes()]
    skipped = [m for m in args.modes if m not in modes]
    mode_name = "mock" if is_mock() else "bedrock"
    print(f"채점 {judge_v1.VERSION} / 추천 {rec.PROMPT_VERSION} / 모드 {mode_name} / 비교 {modes} / 기술 {len(skills)}개")
    if skipped:
        print(f"건너뜀: {skipped} (ai/debate.py 가 이 브랜치에 없습니다)")
    if mode_name == "mock":
        print("가짜 모드: 점수는 예시입니다. 발표나 보고서에 쓰지 않습니다.")

    items, errors, usage = [], [], {"recommend": {}, "judge": {}}
    rng = random.Random(args.seed)
    for skill in skills:
        demand = demand_of(skill, table)
        for mode in modes:
            try:
                recommendation, result = recommend(skill, demand, mode)
            except BedrockJSONError as e:
                add_usage(usage["recommend"], e.usage)
                errors.append({"skill": skill, "mode": mode, "stage": "recommend", "error": str(e)})
                continue
            if result is not None:
                add_usage(usage["recommend"], result.usage)
            batch = items_of(skill, mode, recommendation)
            if not batch:
                continue
            for it in batch:  # 채점자와 사람에게 모드를 감추려고 뜻 없는 번호를 붙인다
                it["item_id"] = f"i{rng.randrange(16**6):06x}"
            try:
                judged = judge(skill, batch)
            except BedrockJSONError as e:
                add_usage(usage["judge"], e.usage)
                errors.append({"skill": skill, "mode": mode, "stage": "judge", "error": str(e)})
                items += batch
                continue
            add_usage(usage["judge"], judged.usage)
            for it, s in zip(batch, judged.data["scores"]):
                it["scores"] = {k: s[k] for k in CRITERIA}
                it["note"] = s.get("note")
            items += batch

    summary, change = summarize(items), paired_change(items)
    print_summary(summary, change)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"judge_{mode_name}_{stamp}.json"
    sheet = OUT_DIR / f"judge_{mode_name}_{stamp}_human.csv"
    human_ids = write_human_sheet(sheet, items, args.human, args.seed)
    out.write_text(json.dumps({
        "run_at": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": mode_name, "judge_prompt": judge_v1.VERSION,
        "recommend_prompt": rec.PROMPT_VERSION, "model": os.getenv("BEDROCK_MODEL_ID") if mode_name == "bedrock" else None,
        "judge_model": (os.getenv("JUDGE_MODEL_ID") or os.getenv("BEDROCK_MODEL_ID")) if mode_name == "bedrock" else None,
        "skills": skills, "modes": modes, "seed": args.seed, "counts": {"items": len(items), "scored": sum(bool(i.get("scores")) for i in items)},
        "summary": summary, "paired_change": change, "human_item_ids": human_ids, "usage": usage, "errors": errors, "items": items,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n채점 항목 {len(items)}개, 오류 {len(errors)}건")
    print(f"원본 저장: {out.relative_to(ROOT)}")
    print(f"사람 재채점 양식({len(human_ids)}개): {sheet.relative_to(ROOT)}  → 채운 뒤 `python -m ai.eval.judge agree` 로 일치율을 계산합니다")
    return 1 if errors else 0


def agreement(llm: dict[str, dict], human: dict[str, dict]) -> dict:
    """기준마다 정확히 같은 비율, 1점 이내 비율, 평균 차이(LLM − 사람). 사람이 채운 항목만 센다."""
    out = {}
    for k in CRITERIA:
        pairs = [(llm[i][k], human[i][k]) for i in human if i in llm and human[i].get(k) is not None]
        n = len(pairs)
        out[k] = {
            "n": n,
            "exact": round(sum(a == b for a, b in pairs) / n, 2) if n else None,
            "within_1": round(sum(abs(a - b) <= 1 for a, b in pairs) / n, 2) if n else None,
            "mean_diff": round(sum(a - b for a, b in pairs) / n, 2) if n else None,
        }
    return out


def read_human_sheet(path: Path) -> dict[str, dict]:
    rows = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            scores = {}
            for k in CRITERIA:
                cell = (row.get(k) or "").strip()
                if cell == "":
                    scores[k] = None
                elif cell in ("0", "1", "2"):
                    scores[k] = int(cell)
                else:
                    raise ValueError(f"{path.name} {line}행 {k} 칸이 {cell!r} 입니다. 0, 1, 2 중 하나로 적어 주세요")
            rows[row["item_id"]] = scores
    return rows


def agree(args) -> int:
    result = json.loads(Path(args.result).read_text(encoding="utf-8"))
    llm = {it["item_id"]: it["scores"] for it in result["items"] if it.get("scores")}
    human = read_human_sheet(Path(args.sheet))
    unknown = sorted(set(human) - set(llm))
    if unknown:
        print(f"양식에 결과 파일에 없는 item_id 가 있습니다: {unknown}")
        return 1
    table = agreement(llm, human)
    names = {r[0]: r[1] for r in judge_v1.RUBRIC}
    print(f"LLM 채점({result['judge_prompt']}, {result['mode']})과 사람 채점의 일치율")
    print(f"{'기준':12} {'항목':>4} {'정확히 같음':>10} {'1점 이내':>8} {'평균 차이(LLM−사람)':>18}")
    for k, row in table.items():
        if not row["n"]:
            print(f"{names[k]:12} {0:>6} (사람이 채운 항목 없음)")
            continue
        print(f"{names[k]:12} {row['n']:>6} {row['exact']:>14.0%} {row['within_1']:>12.0%} {row['mean_diff']:>+20.2f}")
    if result["mode"] == "mock":
        print("가짜 모드 결과입니다. 발표나 보고서에 쓰지 않습니다.")
    return 0


def count_cases() -> dict:
    """평가 케이스 수. 추출 정답은 기술 항목 단위로 센다(정답지가 없는 파일은 0)."""
    out = {}
    for path in GOLD_FILES:
        if path.exists():
            gold = json.loads(path.read_text(encoding="utf-8"))
            out[str(path.relative_to(ROOT))] = {"postings": len(gold), "skill_items": sum(len(g["skills"]) for g in gold)}
        else:
            out[str(path.relative_to(ROOT))] = None
    return out


def cases(args) -> int:
    total = 0
    for name, row in count_cases().items():
        if row is None:
            print(f"{name}: 없음")
        else:
            total += row["skill_items"]
            print(f"{name}: 공고 {row['postings']}건, 기술 항목 {row['skill_items']}개")
    judged = sorted(OUT_DIR.glob("judge_bedrock_*.json"))
    if judged:
        last = json.loads(judged[-1].read_text(encoding="utf-8"))
        total += last["counts"]["scored"]
        print(f"{judged[-1].relative_to(ROOT)}: 채점한 추천 항목 {last['counts']['scored']}개")
    else:
        print("실제 모드로 채점한 추천 결과: 없음")
    print(f"평가 케이스 합계: {total}개 (추출 기술 항목 + 실제 모드 채점 항목. 가짜 공고 정답과 채점용 정답을 따로 보고할 때는 위 줄을 쓰세요)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="추천 이유 LLM 채점과 사람 재채점 일치율")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--skills", nargs="+")
    r.add_argument("--modes", nargs="+", default=["single", "debate"], choices=["single", "debate"])
    r.add_argument("--human", type=int, default=10)
    r.add_argument("--seed", type=int, default=20261116)
    a = sub.add_parser("agree")
    a.add_argument("result")
    a.add_argument("sheet")
    sub.add_parser("cases")
    args = ap.parse_args(argv)
    return {"run": run, "agree": agree, "cases": cases}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
