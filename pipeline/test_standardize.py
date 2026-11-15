"""standardize 확인. 실행: python -m pipeline.test_standardize"""
import copy
import json
from pathlib import Path

from pipeline.aliases import normalize_skill
from pipeline.standardize import standardize

GOLD = Path(__file__).resolve().parent.parent / "ai" / "eval" / "gold_extraction.json"


def skill(raw, normalized, type="required", confidence="high"):
    return {"raw": raw, "normalized": normalized, "type": type, "evidence": f"{raw} 경험",
            "confidence": confidence, "ncs_unit": None}


def demo():
    # 사전에 있으면 대표 이름으로, 없으면 그대로 두고 uncertain, 목록에 모은다
    src = {"posting_id": "x", "skills": [skill("k8s", "k8s"), skill("Rust", "Rust")]}
    before = copy.deepcopy(src)
    out, unknown = standardize(src)
    assert src == before  # 입력은 고치지 않는다
    assert out["posting_id"] == "x"
    assert [s["normalized"] for s in out["skills"]] == ["Kubernetes", "Rust"]
    assert [s["confidence"] for s in out["skills"]] == ["high", "uncertain"]
    assert unknown == ["Rust"]
    assert {s["raw"] for s in out["skills"]} == {"k8s", "Rust"}  # raw 는 그대로

    # NCS 단위: 확신 있는 연결(S3)만 채우고, 없는 기술(Docker)과 모르는 표현(Rust)은 None
    out, _ = standardize({"posting_id": "x", "skills": [skill("S3", "S3"), skill("도커", "도커"), skill("Rust", "Rust")]})
    assert [s["ncs_unit"] for s in out["skills"]] == ["2001021507", None, None]

    # 합쳐져 같은 기술이 되면 required 를 남긴다, 같은 모르는 표현은 한 번만
    out, unknown = standardize({"posting_id": "x", "skills": [
        skill("Docker", "Docker", "preferred"), skill("도커", "도커", "required"),
        skill("Rust", "Rust"), skill("Rust", "Rust")]})
    assert [(s["normalized"], s["type"]) for s in out["skills"]] == [("Docker", "required"), ("Rust", "required")]
    assert unknown == ["Rust"]

    # 성진의 정답지: LLM 이름이 엉망이어도(normalized = raw)
    # ① 사전에 있는 이름은 정답지의 normalized 로 맞춰지고
    # ② 사전에 없는 이름(정답지 규칙 7번, 예: 공고 표기 그대로 넣은 기술)은 unknown 목록에 빠짐없이, 더하지도 않고 들어간다.
    # 어느 쪽인지는 data/aliases.json 을 보고 나눈다(정답지가 늘어도 이 테스트는 고치지 않는다). 종훈 확인 2026-11-16
    for posting in json.loads(GOLD.read_text(encoding="utf-8")):
        pid = posting["posting_id"]
        skills = [skill(s["raw"], s["raw"], s["type"]) for s in posting["skills"]]
        out, unknown = standardize({"posting_id": pid, "skills": skills})
        known = [s for s in posting["skills"] if normalize_skill(s["raw"])]
        not_known = [s for s in posting["skills"] if not normalize_skill(s["raw"])]
        known_raws = {s["raw"] for s in known}
        got = {(s["normalized"], s["type"]) for s in out["skills"] if s["raw"] in known_raws}
        want = {(s["normalized"], s["type"]) for s in known}
        assert got == want, (pid, got ^ want)
        assert sorted(unknown) == sorted(s["raw"] for s in not_known), (pid, unknown, [s["raw"] for s in not_known])


if __name__ == "__main__":
    demo()
    print("통과")
