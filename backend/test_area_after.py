"""추천 과정을 마친 뒤의 영역별 Gap(예상) 확인(가짜 모드). 실행: python -m backend.test_area_after"""
import os

os.environ["BEDROCK_MOCK"] = "1"

from backend import api  # noqa: E402

JOB = "cloud_engineer"
OWNED = ["Python", "Linux", "Git"]


def test_area_gap_after():
    demand = {s["skill"]: s["postings"] for s in api.get_demand(JOB)["skills"]}
    # 추천 과정을 마친 뒤(예상): 과정이 붙은 기술만큼 보유가 늘고, 수요와 다른 영역은 그대로다
    before = {r["area"]: r for r in api.get_area_gap(JOB, OWNED)}
    after = {r["area"]: r for r in api.get_area_gap_after(JOB, OWNED, ["Docker"])}
    assert after["컴퓨팅·서버"]["demand"] == before["컴퓨팅·서버"]["demand"]
    assert before["컴퓨팅·서버"]["owned"] < after["컴퓨팅·서버"]["owned"] <= before["컴퓨팅·서버"]["owned"] + demand["Docker"]
    assert after["공통"] == before["공통"]
    assert api.get_area_gap_after(JOB, OWNED, []) == api.get_area_gap(JOB, OWNED)
    assert api.get_area_gap_after(JOB, OWNED, ["Python"]) == api.get_area_gap(JOB, OWNED)   # 이미 가진 기술은 그대로


if __name__ == "__main__":
    test_area_gap_after()
    print("backend.api.get_area_gap_after 확인 통과")
