"""추천 카드의 과정 쪽 근거 문장 확인(가짜 모드). 실행: python -m backend.test_evidence"""
import os

os.environ["BEDROCK_MOCK"] = "1"

import ai.recommend as recommend  # noqa: E402
from backend import api  # noqa: E402
from pipeline.search import _courses, evidence_in_course, skill_evidence  # noqa: E402


def test_course_evidence():
    rec, _ = recommend.build_recommendation("Docker", {"postings": 20, "of": 40, "required_ratio": 0.45})
    by_title = {c["title"]: cid for cid, c in _courses().items()}
    # 과정 원문에서 골라 온 것이고, 있으면 그 과정의 그 칸에 실제로 있다
    assert rec["courses"][0]["evidence"]["about"] == "skill" and "Docker" in rec["courses"][0]["evidence"]["text"]
    for c in rec["courses"]:
        if c["evidence"]:
            assert evidence_in_course(c["evidence"], by_title[c["title"]]), c
    some_id = by_title[rec["courses"][0]["title"]]
    assert skill_evidence("없는기술이름", some_id) is None                       # 이름도 세부 능력도 안 맞으면 없다
    assert not evidence_in_course({"text": "지어낸 문장", "field": "objectives"}, some_id)
    assert not evidence_in_course({"text": "x", "field": "description"}, some_id)   # 설명 칸은 근거로 쓰지 않는다
    # 가짜 추천 예시에도 evidence 가 있다(없음을 뜻하는 null 포함)
    assert all("evidence" in c for r in api._load("recommendations.json") for c in r["courses"])


if __name__ == "__main__":
    test_course_evidence()
    print("과정 쪽 근거 문장 확인 통과")
