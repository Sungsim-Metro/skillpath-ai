"""과정 검색 방식 비교: 키워드(BM25) / 임베딩(코사인) / 둘을 섞은 방식(RRF), 그리고 기준선(지금 서비스의 검색).

개발 중에 돌리는 비교다. 서비스가 쓰는 pipeline/search.py 는 바꾸지 않는다. 결과를 보고 따로 정한다.
2026-11-17 반대편 검토를 받아 설계를 고쳤다. 고친 이유는 아래 "왜 이렇게 재나"에 있다.

실행 (저장소 루트에서)
  python -m pipeline.eval_search compare                    정답 없이 기술마다 방식별 상위 과정을 나란히 본다(사례표)
  python -m pipeline.eval_search template                   사람이 정답을 표시할 양식을 만든다(outputs/eval/search_pool.csv)
  python -m pipeline.eval_search run --labels <채운 양식>    사람 정답으로 점수표를 낸다

왜 이렇게 재나
- 질의는 서비스가 실제로 받는 문자열, 곧 **기술 대표명**(data/skill_areas.json 의 기술들)이다. 모든 방식에 같은 문자열을 준다.
  과정을 줄 수 없는 기술(Python, Java 등)도 일부러 넣는다. "없어야 할 때 비우는가"도 재야 하기 때문이다.
- 문서는 모든 방식에 과정의 제목 + 학습 목표로 통일한다. k 는 서비스가 보여 주는 3 이다.
- 지금 서비스의 검색(search_courses)은 **기준선**으로만 놓고 다른 방식과 순위를 매기지 않는다.
  그 검색은 과정을 모을 때의 Skill Builder 검색 순위와 사람이 적은 별칭 연결표(course_subskill.csv)를 조회한다.
  검색 알고리즘이 아니라 조회이고, 연결표로 만든 정답으로 채점하면 정답표를 보고 답하는 셈이 된다.
- 정답은 사람이 붙인다. 방식들의 상위 k 를 모은(풀링) 양식에 어느 방식이 찾았는지 감추고 1/0 을 적는다.
  연결표로 만든 "약한 정답"은 낱말 일치로 만들어져 키워드 방식에 유리하므로 기본으로는 쓰지 않는다(--weak 를 줘야 나오고 기준선은 뺀다).
- 질의가 30개 남짓이다. 비율이 아니라 **건수**로 보고하고, 방식 쌍마다 "한쪽만 맞힌 질의 수"를 함께 낸다. 한두 건 차이는 우열이 아니다.
- 풀링의 한계: 어느 방식도 찾지 못한 맞는 과정은 정답에 들어오지 못한다. 그래서 재현율은 내지 않는다.
- 임베딩 방식은 기준값 없이 늘 k 개를 낸다. 맞는 과정이 없는 기술에서 "잘못 채운 질의 수"로 그 약점을 본다.

가짜 모드(BEDROCK_MOCK=1)의 임베딩은 글자 조각을 해시한 가짜 벡터다. 그래서 가짜 모드에서는 임베딩·혼합 방식을 계산하지 않고,
양식도 만들지 않는다(엉뚱한 후보에 사람 시간을 쓰지 않게). 점수는 전부 코드가 계산한다.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
from collections import Counter
from itertools import combinations
from pathlib import Path

from pipeline import embed, search

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "outputs" / "eval"
POOL = OUT_DIR / "search_pool.csv"
SKILL_AREAS = ROOT / "data" / "skill_areas.json"
COMPARED = ("keyword", "embedding", "hybrid")  # 서로 비교하는 검색 방식
BASELINE = "baseline"                           # 지금 서비스의 검색. 비교 대상이 아니라 기준선
NEEDS_EMBEDDING = ("embedding", "hybrid")
LABEL = {"keyword": "키워드(BM25)", "embedding": "임베딩(코사인)", "hybrid": "혼합(RRF)", "baseline": "기준선(지금 서비스)"}
POOL_COLUMNS = ["skill", "course_id", "title", "level", "objectives", "relevant"]
DEFAULT_K = 3  # 서비스가 기술 하나에 보여 주는 과정 수(ai/recommend.py 가 search_courses 를 기본값으로 부른다)
RRF_K = 60
_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.-]*|[가-힣]+")


def tokens(text: str) -> list[str]:
    """소문자 낱말. 문장 끝에 붙은 마침표·붙임표는 뗀다("EC2." 와 "EC2" 가 같은 낱말이 되게). 어간 처리는 하지 않는다."""
    return [t.rstrip(".-") for t in _TOKEN.findall(text.lower()) if t.rstrip(".-")]


def service_skills() -> list[str]:
    """서비스가 받는 질의: 영역에 배정된 기술 대표명 전부. 과정을 줄 수 없는 기술도 들어 있다."""
    return list(json.loads(SKILL_AREAS.read_text(encoding="utf-8"))["skills"])


def usable_courses() -> list[dict]:
    return [c for c in search._courses().values() if search._usable(c)]


def doc_text(course: dict) -> str:
    """모든 방식이 보는 과정 글: 제목 + 학습 목표. 방식마다 다른 글을 보면 방식 차이와 글 차이가 섞인다."""
    return f"{course['title']}. {course['objectives']}"


def weak_labels(skills: list[str]) -> dict[str, set[str]]:
    """연결표의 certain 연결로 만든 약한 정답 {기술: 과정 id}. 낱말 일치로 만든 것이라 키워드 방식에 유리하다."""
    usable = {c["course_id"] for c in usable_courses()}
    by_subskill: dict[str, set[str]] = {}
    for row in search._read(search.LINKS):
        if row["match"] == "certain" and row["course_id"] in usable:
            by_subskill.setdefault(row["subskill_id"], set()).add(row["course_id"])
    return {s: set().union(*[by_subskill.get(sid, set()) for sid in search.subskills_of(s)] or [set()]) for s in skills}


class BM25:
    def __init__(self, docs: dict[str, str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = {cid: Counter(tokens(text)) for cid, text in docs.items()}
        self.length = {cid: sum(tf.values()) for cid, tf in self.tf.items()}
        self.avg = sum(self.length.values()) / max(len(self.length), 1)
        df = Counter(t for tf in self.tf.values() for t in tf)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def rank(self, query: str) -> list[str]:
        """점수가 0보다 큰 과정만, 점수 높은 순. 질의 낱말이 하나도 없으면 빈 목록이다. 동점은 과정 id 순(뜻 없는 순서)."""
        terms = tokens(query)
        scores = {}
        for cid, tf in self.tf.items():
            s = 0.0
            for t in terms:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.length[cid] / self.avg))
            if s > 0:
                scores[cid] = s
        return sorted(scores, key=lambda c: (-scores[c], c))


def rrf(*rankings: list[str]) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for i, cid in enumerate(ranking, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1 / (RRF_K + i)
    return sorted(scores, key=lambda c: (-scores[c], c))


def methods_available() -> tuple[str, ...]:
    """가짜 모드에서는 임베딩이 가짜 벡터라 임베딩·혼합 방식을 계산하지 않는다."""
    return tuple(m for m in COMPARED if not (embed.is_mock() and m in NEEDS_EMBEDDING))


def rank_all(skills: list[str], k: int) -> dict[str, dict[str, list[str]]]:
    """{방식: {기술: 상위 k 과정 id}}. 기준선도 함께 낸다. 모든 방식이 같은 질의 문자열(기술 대표명)을 받는다."""
    courses = usable_courses()
    methods = methods_available()
    bm25 = BM25({c["course_id"]: doc_text(c) for c in courses})
    out: dict[str, dict[str, list[str]]] = {m: {} for m in (*methods, BASELINE)}
    use_embedding = any(m in NEEDS_EMBEDDING for m in methods)
    if use_embedding:  # 질의를 한 번에 임베딩한다(하나씩 부르면 캐시 파일을 질의 수만큼 다시 쓴다)
        ids = [c["course_id"] for c in courses]
        vectors = dict(zip(ids, embed.embed_many([doc_text(c) for c in courses])))
        query_vectors = dict(zip(skills, embed.embed_many(skills)))
    for skill in skills:
        kw = bm25.rank(skill)
        out["keyword"][skill] = kw[:k]
        if use_embedding:
            qv = query_vectors[skill]
            em = sorted(vectors, key=lambda c: (-embed.cosine(qv, vectors[c]), c))
            out["embedding"][skill] = em[:k]
            out["hybrid"][skill] = rrf(kw[:50], em[:50])[:k]
        out[BASELINE][skill] = [f["course_id"] for f in search.search_courses(skill, k=k)]
    return out


def score(ranked: dict[str, list[str]], labels: dict[str, set[str]], k: int) -> dict:
    """한 방식의 점수. 전부 건수다.

    - 맞는 과정이 있는 기술(answerable): 상위 k 안에 맞는 과정이 하나라도 있는 기술 수(hit)
    - 보여 준 과정 가운데 맞는 과정 수(shown_relevant / shown): 사용자가 보는 카드 기준의 정밀도
    - 맞는 과정이 없는 기술(empty): 그런데도 과정을 하나 이상 낸 기술 수(wrongly_filled). 비워야 맞다
    labels 에 없는 기술은 세지 않는다.
    """
    judged = [s for s in ranked if s in labels]
    answerable = [s for s in judged if labels[s]]
    empty = [s for s in judged if not labels[s]]
    return {
        "answerable": len(answerable),
        "hit": sum(any(c in labels[s] for c in ranked[s][:k]) for s in answerable),
        "shown": sum(len(ranked[s][:k]) for s in judged),
        "shown_relevant": sum(c in labels[s] for s in judged for c in ranked[s][:k]),
        "empty": len(empty),
        "wrongly_filled": sum(bool(ranked[s][:k]) for s in empty),
        "hit_skills": sorted(s for s in answerable if any(c in labels[s] for c in ranked[s][:k])),
    }


def pairwise(table: dict[str, dict]) -> list[dict]:
    """비교 방식 쌍마다 한쪽만 맞힌 기술. 평균 차이보다 이 목록이 정직하다."""
    out = []
    for a, b in combinations([m for m in COMPARED if m in table], 2):
        ha, hb = set(table[a]["hit_skills"]), set(table[b]["hit_skills"])
        out.append({"a": a, "b": b, "only_a": sorted(ha - hb), "only_b": sorted(hb - ha)})
    return out


def _open_csv(path: Path):
    """엑셀의 "CSV UTF-8" 과 한국어 엑셀의 기본 CSV(cp949)를 모두 읽는다."""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(encoding).splitlines(keepends=True)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path.name} 을 읽지 못했습니다. 엑셀에서 'CSV UTF-8(쉼표로 분리)'로 저장해 주세요")


def read_labels(path: Path, expected: set[tuple[str, str]] | None = None) -> dict[str, set[str]]:
    """사람이 채운 양식 → {기술: 맞는 과정 id}. 0만 적힌 기술은 빈 집합으로 남긴다(맞는 과정이 없다는 판정이다).

    조용히 점수를 부풀리지 않게 엄격하게 읽는다: 빈 칸, 1/0 이 아닌 값, 같은 쌍에 다른 판정, 모르는 과정 id 는 오류.
    expected 를 주면 그 (기술, 과정) 쌍이 모두 판정됐는지도 본다(다른 k 나 다른 모드로 만든 양식을 막는다).
    """
    known = {c["course_id"] for c in usable_courses()}
    verdict: dict[tuple[str, str], str] = {}
    for line, row in enumerate(csv.DictReader(_open_csv(path)), start=2):
        skill, cid = (row.get("skill") or "").strip(), (row.get("course_id") or "").strip()
        if not skill and not cid:
            continue  # 엑셀이 끝에 붙인 빈 줄
        cell = (row.get("relevant") or "").strip()
        cell = {"1.0": "1", "0.0": "0"}.get(cell, cell)
        if cell not in ("0", "1"):
            raise ValueError(f"{path.name} {line}행 relevant 칸이 {cell!r} 입니다. 1 이나 0 으로 적어 주세요(빈 칸도 안 됩니다)")
        if cid not in known:
            raise ValueError(f"{path.name} {line}행의 과정 {cid!r} 는 과정 목록에 없습니다")
        if verdict.setdefault((skill, cid), cell) != cell:
            raise ValueError(f"{path.name} {line}행: ({skill}, {cid}) 가 두 번 나오고 판정이 다릅니다")
    if expected is not None:
        missing = expected - set(verdict)
        if missing:
            raise ValueError(
                f"판정되지 않은 (기술, 과정)이 {len(missing)}쌍 있습니다(예: {sorted(missing)[:3]}). "
                "양식을 만들 때와 같은 k, 같은 모드(BEDROCK_MOCK)로 실행했는지 확인하세요"
            )
    labels: dict[str, set[str]] = {}
    for (skill, cid), cell in verdict.items():
        labels.setdefault(skill, set())
        if cell == "1":
            labels[skill].add(cid)
    return labels


def _titles(ids: list[str]) -> str:
    courses = search._courses()
    return " | ".join(courses[c]["title"][:34] for c in ids) or "(없음)"


def compare(args) -> int:
    """정답 없이 보는 사례표. 방식이 갈리는 기술을 찾는 데 쓴다. 점수는 내지 않는다."""
    skills = args.skills or service_skills()
    ranked = rank_all(skills, args.k)
    methods = list(ranked)
    print(f"과정 {len(usable_courses())}개, 기술 {len(skills)}개, k={args.k}. 정답 없이 상위 과정만 나란히 놓은 표입니다. 점수가 아닙니다.")
    differ = 0
    for skill in skills:
        tops = {m: ranked[m][skill] for m in methods}
        same = len({tuple(sorted(v)) for v in tops.values()}) == 1
        differ += not same
        if same and not args.all:
            continue
        print(f"\n■ {skill}")
        for m in methods:
            print(f"  {LABEL[m]:18} {_titles(tops[m])}")
    print(f"\n방식끼리 상위 {args.k}개가 다른 기술: {differ} / {len(skills)}" + ("" if args.all else " (같은 기술은 생략. 모두 보려면 --all)"))
    if embed.is_mock():
        print("가짜 모드라 임베딩·혼합 방식은 계산하지 않았습니다. 실제 모드(BEDROCK_MOCK=0)에서 다시 실행하세요.")
    return 0


def template(args) -> int:
    if embed.is_mock() and not args.allow_mock:
        sys.exit("가짜 모드(BEDROCK_MOCK=1)에서는 양식을 만들지 않습니다. 임베딩 후보가 빠진 양식에 사람 시간을 쓰게 되기 때문입니다.\n"
                 "실제 모드(BEDROCK_MOCK=0)에서 실행하세요. 형식만 보려면 --allow-mock 을 붙입니다.")
    skills = args.skills or service_skills()
    ranked = rank_all(skills, args.k)
    courses = search._courses()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = 0
    with POOL.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=POOL_COLUMNS)
        w.writeheader()
        for skill in skills:
            pool = sorted({cid for m in ranked for cid in ranked[m][skill]})  # 어느 방식이 찾았는지 알 수 없게 id 순
            for cid in pool:
                c = courses[cid]
                w.writerow({"skill": skill, "course_id": cid, "title": c["title"], "level": c["level"],
                            "objectives": c["objectives"], "relevant": ""})
                rows += 1
    empty = [s for s in skills if not any(ranked[m][s] for m in ranked)]
    print(f"양식 저장: {POOL.relative_to(ROOT)} (기술 {len(skills)}개, 행 {rows}개, k={args.k}, 방식 {', '.join(ranked)})")
    print("relevant 칸에 그 과정이 그 기술을 실제로 가르치면 1, 아니면 0 을 적습니다. 제목과 학습 목표만 보고 판단합니다.")
    print("엑셀로 열었으면 'CSV UTF-8(쉼표로 분리)'로 저장하세요. 채점은 양식을 만든 때와 같은 k, 같은 모드로 실행합니다.")
    if empty:
        print(f"어느 방식도 과정을 내지 않아 양식에 없는 기술 {len(empty)}개: {', '.join(empty)}")
    if embed.is_mock():
        print("주의: 가짜 모드로 만든 형식 확인용 양식입니다. 임베딩·혼합 방식의 후보가 없어 채점에 쓸 수 없습니다.")
    return 0


def _print_table(table: dict[str, dict], k: int) -> None:
    print(f"\n{'방식':20} {'맞힌 기술':>12} {'맞는 과정/보여 준 과정':>22} {'비워야 하는데 채움':>18}")
    for m, row in table.items():
        if m == BASELINE:
            print("  " + "-" * 74 + "\n  (아래는 비교 대상이 아닌 기준선입니다. 연결표와 수집 순위를 조회하는 방식이라 같은 줄에 놓고 우열을 말하지 않습니다)")
        print(f"{LABEL[m]:20} {row['hit']:>6} / {row['answerable']:<5} {row['shown_relevant']:>10} / {row['shown']:<10} "
              f"{row['wrongly_filled']:>8} / {row['empty']:<5}")
    for p in pairwise(table):
        print(f"{LABEL[p['a']]}만 맞힌 기술 {len(p['only_a'])}개 {p['only_a']} / {LABEL[p['b']]}만 맞힌 기술 {len(p['only_b'])}개 {p['only_b']}")
    n = next(iter(table.values()))["answerable"]
    print(f"맞는 과정이 있는 기술이 {n}개뿐입니다. 한두 건 차이는 우열로 읽지 않습니다. 위의 '한쪽만 맞힌 기술'을 사례로 보세요.")


def run(args) -> int:
    mode = "mock" if embed.is_mock() else "bedrock"
    if not args.labels and not args.weak:
        sys.exit("정답이 필요합니다. `template` 로 양식을 만들어 사람이 채운 뒤 `run --labels <양식>` 으로 실행하세요.\n"
                 "정답 없이 방식이 어디서 갈리는지 보려면 `compare` 를 씁니다. (연결표로 만든 약한 정답은 --weak. 발표에 쓰지 않습니다)")
    skills = args.skills or service_skills()
    ranked = rank_all(skills, args.k)
    if args.labels:
        expected = {(s, c) for m in ranked for s, v in ranked[m].items() for c in v}
        labels, label_name = read_labels(Path(args.labels), expected), "사람 정답"
        for s in skills:  # 어느 방식도 과정을 내지 않아 양식에 없던 기술: 풀 안에 맞는 과정이 없다
            labels.setdefault(s, set())
        table = {m: score(ranked[m], labels, args.k) for m in ranked}
    else:
        labels, label_name = weak_labels(skills), "약한 정답(연결표의 certain). 낱말 일치로 만든 정답이라 키워드 방식에 유리합니다"
        labels = {s: v for s, v in labels.items() if v}  # 약한 정답은 '없음'을 판정하지 못한다
        table = {m: score(ranked[m], labels, args.k) for m in ranked if m != BASELINE}  # 기준선은 이 정답표를 읽고 답하므로 뺀다
    print(f"과정 {len(usable_courses())}개, 기술 {len(skills)}개, k={args.k}, 임베딩: {mode}\n정답: {label_name}")
    _print_table(table, args.k)
    if args.weak and not args.labels:
        print("주의: 약한 정답으로 낸 표입니다. 발표나 보고서에 쓰지 않습니다. 기준선은 이 정답표를 읽고 답하므로 뺐습니다.")
    if mode == "mock":
        print("주의: 가짜 모드라 임베딩·혼합 방식은 계산하지 않았습니다.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"search_compare_{mode}_{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({
        "run_at": time.strftime("%Y-%m-%d %H:%M:%S"), "embedding_mode": mode, "k": args.k, "labels": label_name,
        "labels_file": args.labels, "courses": len(usable_courses()), "skills": skills,
        "table": table, "pairwise": pairwise(table), "ranked": ranked, "embed_usage": embed.usage(),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"원본 저장: {out.relative_to(ROOT)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="과정 검색 방식 비교")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("compare", "template", "run"):
        p = sub.add_parser(name)
        p.add_argument("--k", type=int, default=DEFAULT_K)
        p.add_argument("--skills", nargs="+", help="기본: data/skill_areas.json 의 기술 전부")
    sub.choices["compare"].add_argument("--all", action="store_true", help="방식끼리 결과가 같은 기술도 보여 준다")
    sub.choices["template"].add_argument("--allow-mock", action="store_true", help="가짜 모드에서도 형식 확인용 양식을 만든다")
    sub.choices["run"].add_argument("--labels", help="사람이 채운 양식")
    sub.choices["run"].add_argument("--weak", action="store_true", help="연결표로 만든 약한 정답으로 본다(발표에 쓰지 않는다)")
    args = ap.parse_args(argv)
    return {"compare": compare, "template": template, "run": run}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
