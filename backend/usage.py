"""토큰·비용 집계 (2026-11-16 결정). ai/usage.py 가 남긴 호출 기록을 읽어 단계별로 더한다. 전부 코드로 계산한다.

비용 = 입력 토큰 ÷ 1000 × 입력 단가 + 출력 토큰 ÷ 1000 × 출력 단가. 단가는 data/pricing.json 에 사람이 적는다.
단가가 없는 모델의 호출은 토큰만 세고 비용에는 넣지 않으며, 그런 호출이 몇 건인지 함께 돌려준다(비용을 낮게 보이게 하지 않으려고).
가짜 모드 호출은 토큰이 0 이라 따로 센다.
"""
from __future__ import annotations

import json
from pathlib import Path

from ai.usage import log_path

PRICING = Path(__file__).resolve().parent.parent / "data" / "pricing.json"
STAGE_LABEL = {"extract": "기술 추출", "recommend": "추천 이유", "review": "추천 검증", "judge": "평가 채점",
               "coffeechat": "커피챗 초안"}


def read_rows(path: Path | None = None) -> list[dict]:
    path = path or log_path()
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # 쓰다 끊긴 줄은 건너뛴다
        if _valid(row):
            rows.append(row)
    return rows


def _valid(row) -> bool:
    """집계에 쓸 수 있는 줄인가. 칸이 빠졌거나 형식이 다른 줄은 세지 않는다(화면이 한 줄 때문에 멈추지 않게)."""
    return (isinstance(row, dict) and isinstance(row.get("ts"), str) and isinstance(row.get("stage"), str)
            and all(type(row.get(k)) is int for k in ("inputTokens", "outputTokens")))


def load_pricing() -> dict:
    return json.loads(PRICING.read_text(encoding="utf-8"))


def cost_of(row: dict, pricing: dict) -> float | None:
    """호출 1건의 비용. 그 모델의 단가가 없으면 None."""
    price = pricing["models"].get(row.get("model", ""))
    if not price:
        return None
    return row["inputTokens"] / 1000 * price["input_per_1k"] + row["outputTokens"] / 1000 * price["output_per_1k"]


def summarize(rows: list[dict] | None = None, pricing: dict | None = None) -> dict:
    rows = read_rows() if rows is None else rows
    pricing = load_pricing() if pricing is None else pricing
    real = [r for r in rows if not r.get("mock")]

    def total(group: list[dict]) -> dict:
        costs = [cost_of(r, pricing) for r in group]
        return {
            "calls": len(group),
            "retries": sum(r.get("attempt", 1) > 1 for r in group),
            "input_tokens": sum(r["inputTokens"] for r in group),
            "output_tokens": sum(r["outputTokens"] for r in group),
            "cost": round(sum(c for c in costs if c is not None), 4),
            "unpriced_calls": sum(c is None for c in costs),
        }

    stages = sorted({r["stage"] for r in real})
    days = sorted({r["ts"][:10] for r in real})
    return {
        "total": total(real),
        "by_stage": [{"stage": s, "label": STAGE_LABEL.get(s, s), **total([r for r in real if r["stage"] == s])} for s in stages],
        "by_day": [{"day": d, **total([r for r in real if r["ts"][:10] == d])} for d in days],
        "mock_calls": len(rows) - len(real),
        "models": sorted({r.get("model", "") for r in real}),
        "first": real[0]["ts"] if real else None,
        "last": real[-1]["ts"] if real else None,
        "pricing": {k: pricing.get(k) for k in ("source", "checked", "currency")},
        "priced_models": sorted(pricing["models"]),
    }
