"""과정 검색 방식 비교: 키워드(BM25) / 임베딩(코사인) / 둘을 섞은 방식(RRF) / 지금 서비스가 쓰는 방식 (2026-11-16 결정).

개발 중에 돌리는 비교다. 서비스가 쓰는 pipeline/search.py 는 바꾸지 않는다. 결과를 보고 따로 정한다.

실행 (저장소 루트에서)
  python -m pipeline.eval_search run                       약한 정답(아래 설명)으로 방식별 점수표를 낸다
  python -m pipeline.eval_search template                  사람이 정답을 표시할 양식을 만든다(outputs/eval/search_pool.csv)
  python -m pipeline.eval_search run --labels <채운 양식>   사람이 표시한 정답으로 점수표를 낸다

질의: pipeline/courses/queries.csv 의 세부 능력 31개. 질의 문장은 search_text(예: "Amazon EC2")다.
방식
  keyword   BM25. 과정의 제목·학습 목표·설명에서 질의 낱말을 찾는다
  embedding 질의와 과정(제목 + 학습 목표)을 임베딩해 코사인 유사도로 줄 세운다(pipeline/embed.py, Titan)
  hybrid    keyword 와 embedding 의 순위를 RRF(1 / (60 + 순위) 의 합)로 섞는다
  current   pipeline.search.search_courses. 세부 능력의 별칭 가운데 결과가 나오는 첫 별칭으로 부른다
점수(전부 코드로 계산): hit@k(상위 k 안에 정답이 하나라도 있는 질의의 비율), recall@k, MRR.

정답 두 가지
  약한 정답(기본): data/courses/course_subskill.csv 에서 그 세부 능력에 certain 으로 이어진 과정.
      **이 연결은 낱말이 제목·학습 목표에 나오는지로 만들어졌다. keyword 와 current 에 유리하다.**
      방식끼리 비교한 결론을 약한 정답만으로 내리지 않는다.
  사람 정답: template 이 방식들의 상위 k 를 모아(풀링) 만든 양식에 사람이 relevant 칸을 1/0 으로 채운 것.
      어느 방식이 찾았는지는 양식에 적지 않는다.

가짜 모드(BEDROCK_MOCK=1)의 임베딩은 글자 조각을 해시한 가짜 벡터라 embedding·hybrid 점수에 뜻이 없다.
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
from pathlib import Path

from pipeline import embed, search

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "outputs" / "eval"
POOL = OUT_DIR / "search_pool.csv"
METHODS = ("keyword", "embedding", "hybrid", "current")
POOL_COLUMNS = ["subskill_id", "subskill", "query", "course_id", "title", "level", "objectives", "relevant"]
RRF_K = 60
_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.-]*|[가-힣]+")


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def queries() -> list[dict]:
    return [{"subskill_id": r["subskill_id"], "subskill": r["subskill"], "query": r["search_text"],
             "aliases": [a.strip() for a in r["aliases"].split("|") if a.strip()]} for r in search._read(search.QUERIES)]


def usable_courses() -> list[dict]:
    return [c for c in search._courses().values() if search._usable(c)]


def weak_labels() -> dict[str, set[str]]:
    usable = {c["course_id"] for c in usable_courses()}
    out: dict[str, set[str]] = {}
    for row in search._read(search.LINKS):
        if row["match"] == "certain" and row["course_id"] in usable:
            out.setdefault(row["subskill_id"], set()).add(row["course_id"])
    return out


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


def current_rank(q: dict, k: int) -> list[str]:
    for alias in q["aliases"]:
        found = search.search_courses(alias, k=k)
        if found:
            return [f["course_id"] for f in found]
    return []


def rank_all(k: int) -> dict[str, dict[str, list[str]]]:
    """{방식: {세부 능력 id: 상위 k 과정 id}}"""
    courses = usable_courses()
    bm25 = BM25({c["course_id"]: " ".join([c["title"], c["objectives"], c["description"]]) for c in courses})
    vectors = dict(zip((c["course_id"] for c in courses),
                       embed.embed_many([f"{c['title']}. {c['objectives']}" for c in courses])))
    out = {m: {} for m in METHODS}
    for q in queries():
        kw = bm25.rank(q["query"])
        qv = embed.embed(q["query"])
        em = sorted(vectors, key=lambda c: (-embed.cosine(qv, vectors[c]), c))
        sid = q["subskill_id"]
        out["keyword"][sid] = kw[:k]
        out["embedding"][sid] = em[:k]
        out["hybrid"][sid] = rrf(kw[:50], em[:50])[:k]
        out["current"][sid] = current_rank(q, k)
    return out


def score(ranked: dict[str, list[str]], labels: dict[str, set[str]], k: int) -> dict:
    """정답이 하나도 없는 질의는 빼고 센다(그 수는 skipped 로 돌려준다)."""
    judged = [sid for sid in ranked if labels.get(sid)]
    hits = recall = mrr = 0.0
    for sid in judged:
        top, gold = ranked[sid][:k], labels[sid]
        found = [i for i, cid in enumerate(top, start=1) if cid in gold]
        hits += bool(found)
        recall += len(found) / len(gold)
        mrr += 1 / found[0] if found else 0
    n = len(judged)
    return {"queries": n, "skipped": len(ranked) - n,
            "hit": round(hits / n, 2) if n else None, "recall": round(recall / n, 2) if n else None,
            "mrr": round(mrr / n, 2) if n else None}


def read_labels(path: Path) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    blank = 0
    with path.open(encoding="utf-8-sig", newline="") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            cell = (row.get("relevant") or "").strip()
            if cell == "":
                blank += 1
            elif cell == "1":
                out.setdefault(row["subskill_id"], set()).add(row["course_id"])
            elif cell != "0":
                raise ValueError(f"{path.name} {line}행 relevant 칸이 {cell!r} 입니다. 1 이나 0 으로 적어 주세요")
            out.setdefault(row["subskill_id"], set())
    if blank:
        raise ValueError(f"{path.name} 에 relevant 칸이 빈 행이 {blank}개 있습니다. 모두 채운 뒤 다시 실행하세요")
    return out


def template(args) -> int:
    ranked = rank_all(args.k)
    courses = search._courses()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = 0
    with POOL.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=POOL_COLUMNS)
        w.writeheader()
        for q in queries():
            pool = sorted({cid for m in METHODS for cid in ranked[m][q["subskill_id"]]})  # 어느 방식이 찾았는지 알 수 없게 id 순
            for cid in pool:
                c = courses[cid]
                w.writerow({"subskill_id": q["subskill_id"], "subskill": q["subskill"], "query": q["query"], "course_id": cid,
                            "title": c["title"], "level": c["level"], "objectives": c["objectives"], "relevant": ""})
                rows += 1
    print(f"양식 저장: {POOL.relative_to(ROOT)} (질의 {len(queries())}개, 행 {rows}개)")
    print("relevant 칸에 그 과정이 세부 능력을 실제로 다루면 1, 아니면 0 을 적습니다. 제목과 학습 목표만 보고 판단합니다.")
    if embed.is_mock():
        print("주의: 가짜 모드라 임베딩 방식의 후보가 엉뚱합니다. 실제 모드(BEDROCK_MOCK=0)에서 만든 양식을 쓰세요.")
    return 0


def run(args) -> int:
    mode = "mock" if embed.is_mock() else "bedrock"
    if args.labels:
        labels, label_name = read_labels(Path(args.labels)), "사람 정답"
    else:
        labels, label_name = weak_labels(), "약한 정답(course_subskill.csv 의 certain)"
    ranked = rank_all(args.k)
    table = {m: score(ranked[m], labels, args.k) for m in METHODS}
    print(f"과정 {len(usable_courses())}개, 질의 {len(queries())}개, k={args.k}, 정답: {label_name}, 임베딩: {mode}")
    print(f"{'방식':10} {'질의':>4} {'hit@k':>7} {'recall@k':>9} {'MRR':>6}")
    for m, row in table.items():
        cells = [("-" if row[x] is None else f"{row[x]:.2f}") for x in ("hit", "recall", "mrr")]
        print(f"{m:10} {row['queries']:>6} {cells[0]:>7} {cells[1]:>9} {cells[2]:>6}")
    skipped = next(iter(table.values()))["skipped"]
    if skipped:
        print(f"정답이 하나도 없는 질의 {skipped}개는 뺐습니다.")
    if not args.labels:
        print("주의: 약한 정답은 낱말 일치로 만든 연결이라 keyword 와 current 에 유리합니다. 방식을 고르는 근거로는 사람 정답을 쓰세요.")
    if mode == "mock":
        print("주의: 가짜 모드의 임베딩은 가짜 벡터입니다. embedding·hybrid 점수에 뜻이 없습니다.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"search_compare_{mode}_{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({
        "run_at": time.strftime("%Y-%m-%d %H:%M:%S"), "embedding_mode": mode, "k": args.k, "labels": label_name,
        "courses": len(usable_courses()), "queries": len(queries()), "table": table, "ranked": ranked,
        "embed_usage": embed.usage(),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"원본 저장: {out.relative_to(ROOT)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="과정 검색 방식 비교")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "template"):
        p = sub.add_parser(name)
        p.add_argument("--k", type=int, default=5)
        if name == "run":
            p.add_argument("--labels")
    args = ap.parse_args(argv)
    return {"run": run, "template": template}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
