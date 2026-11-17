"""화면이 부르는 함수 확인(가짜 모드). 실행: BEDROCK_MOCK=1 python -m backend.test_api"""
import os

os.environ["BEDROCK_MOCK"] = "1"

from backend import api  # noqa: E402

JOB = "cloud_engineer"
OWNED = ["Python", "Linux", "Git"]


def demo():
    # 영역별 Gap: 영역의 수요는 그 영역 기술들의 요구 공고 수 합과 같다
    demand = {s["skill"]: s["postings"] for s in api.get_demand(JOB)["skills"]}
    areas = {r["area"]: r for r in api.get_area_gap(JOB, OWNED)}
    assert sum(r["demand"] for r in areas.values()) == sum(demand.values())
    compute = areas["컴퓨팅·서버"]
    assert compute["demand"] == demand["Linux"] + demand["Docker"] + demand["Kubernetes"]
    assert compute["owned"] == demand["Linux"] and compute["missing_skills"] == ["Docker", "Kubernetes"]
    assert "AWS" in areas["공통"]["skills"]                      # 포괄어는 공통
    assert "Python" in areas["배포 자동화(DevOps)"]["skills"]    # 언어는 스크립트·자동화
    assert areas["보안"]["demand"] == 0 and areas["보안"]["coverage"] == 0   # 수요가 없어도 0으로 나눔 없이
    assert api._area_of("Rust") == ("UNCLASSIFIED", "미분류")    # 사전에 없으면 미분류
    assert all("area" in r for r in api.get_gap(JOB, OWNED))

    # 보유 수준(2026-11-16): 이름 목록은 모두 "써봄"이라 예전 결과와 같다
    as_levels = {s: "used" for s in OWNED}
    assert api.get_gap(JOB, OWNED) == api.get_gap(JOB, as_levels)
    assert api.get_area_gap(JOB, OWNED) == api.get_area_gap(JOB, as_levels)
    # 배워봄은 절반만 치고, 부족 기술에 남는다
    learned = api.get_area_gap(JOB, {**as_levels, "Docker": "learned"})
    compute2 = next(r for r in learned if r["area"] == "컴퓨팅·서버")
    assert compute2["owned"] == demand["Linux"] + demand["Docker"] * 0.5
    assert compute2["partial_skills"] == ["Docker"] and compute2["missing_skills"] == ["Kubernetes"]
    docker_row = next(r for r in api.get_gap(JOB, {**as_levels, "Docker": "learned"}) if r["skill"] == "Docker")
    assert docker_row["level"] == "learned" and docker_row["owned"] is False
    assert next(r for r in api.get_gap(JOB, OWNED) if r["skill"] == "Docker")["level"] == "none"
    # "none" 은 고르지 않은 것과 같고, 모르는 수준 값은 오류다
    assert api.get_gap(JOB, {**as_levels, "Docker": "none"}) == api.get_gap(JOB, OWNED)
    try:
        api.get_gap(JOB, {"Docker": "expert"})
        raise AssertionError("모르는 수준 값이 통과했다")
    except ValueError:
        pass
    # 추천: 수준을 주지 않으면 전과 같은 순서, 배워봄이면 중급 과정이 앞으로 온다. 과정은 더하거나 빼지 않는다
    base = api.get_recommendations(JOB, ["AWS"])[0]
    up = api.get_recommendations(JOB, ["AWS"], {"AWS": "learned"})[0]
    assert base["user_level"] == "none" and up["user_level"] == "learned"
    assert [c["title"] for c in base["courses"]] == [c["title"] for c in api._load("recommendations.json")[0]["courses"]]
    assert up["courses"][0]["level"] == "중급" and base["courses"][0]["level"] == "기초"
    assert sorted(c["title"] for c in up["courses"]) == sorted(c["title"] for c in base["courses"])
    # 수준이 없으면 순서를 건드리지 않는다(확실한 중급이 불확실한 기초보다 앞에 있던 순서 그대로). 배워봄이어도 불확실은 맨 뒤다
    mixed = {"gap_skill": "X", "demand": {}, "courses": [
        {"title": "a", "level": "기초", "match": "certain"}, {"title": "b", "level": "중급", "match": "certain"},
        {"title": "c", "level": "기초", "match": "uncertain"}, {"title": "d", "level": "중급", "match": "uncertain"}]}
    assert [c["title"] for c in api._with_level(mixed, "none")["courses"]] == ["a", "b", "c", "d"]
    assert [c["title"] for c in api._with_level(mixed, "used")["courses"]] == ["a", "b", "c", "d"]
    assert [c["title"] for c in api._with_level(mixed, "learned")["courses"]] == ["b", "a", "d", "c"]
    assert [c["title"] for c in mixed["courses"]] == ["a", "b", "c", "d"]   # 받은 목록은 바꾸지 않는다

    # 시장 Gap: 비중은 각각 합이 100, Gap 은 그 차이
    market = api.get_market_gap(JOB)
    from ai.sections import SECTION_WEIGHT, TYPE_WEIGHT
    assert market["weights"] == {"section": SECTION_WEIGHT, "type": TYPE_WEIGHT, "applied": "type"}  # 가중치 표는 한 곳
    rows = {r["skill"]: r for r in market["rows"]}
    assert abs(sum(r["demand_pct"] for r in rows.values()) - 100) < 1
    assert abs(sum(r["supply_pct"] for r in rows.values()) - 100) < 1
    for r in rows.values():
        assert abs(r["gap_pp"] - (r["demand_pct"] - r["supply_pct"])) <= 0.11, r
    assert rows["AWS"]["gap_pp"] > 0        # 공고는 많이 원하는데 교과목은 적다
    assert rows["Python"]["gap_pp"] < 0     # 수요가 많아도 교과목이 더 많이 다루면 -
    assert rows["SQL"]["demand_pct"] == 0   # 공급에만 있는 기술도 표에 나온다
    assert [r["gap_pp"] for r in market["rows"]] == sorted((r["gap_pp"] for r in market["rows"]), reverse=True)

    # 실제 모드 추천: 수요 숫자는 코드가 만들어 넘기고, 과정과 이유는 ai.recommend 가 만든다(여기서는 가짜로 바꿔 확인)
    import ai.recommend as recommend
    calls, old = [], (api.is_mock, api.get_demand, recommend.build_recommendation)
    api.is_mock = lambda: False
    api.get_demand = lambda job: api._load("demand.json")
    recommend.build_recommendation = lambda skill, d: (calls.append((skill, d)) or {"gap_skill": skill, "demand": d, "courses": []}, None)
    try:
        recs = api.get_recommendations(JOB, ["Docker", "Rust"])
    finally:
        api.is_mock, api.get_demand, recommend.build_recommendation = old
    docker = next(s for s in api._load("demand.json")["skills"] if s["skill"] == "Docker")
    total = api._load("demand.json")["total_postings"]
    assert [r["gap_skill"] for r in recs] == ["Docker", "Rust"]
    assert calls[0][1] == {"postings": docker["postings"], "of": total,
                           "required_ratio": round(docker["required"] / docker["postings"], 2)}
    assert calls[1][1] == {"postings": 0, "of": total, "required_ratio": 0}   # 수요에 없는 기술은 0 으로 넘긴다

    # 가짜가 아닌 실제 build_recommendation 이 ③ 형식(courses[] 의 필드와 반환 튜플)을 돌려주는지: 연결이 가짜 모양에만 맞지 않게
    rec, _ = recommend.build_recommendation("Docker", {"postings": 20, "of": 40, "required_ratio": 0.45})
    assert rec["gap_skill"] == "Docker" and rec["courses"]
    assert all(set(c) == {"title", "url", "level", "prerequisites", "reason", "match"} for c in rec["courses"])
    print("backend.api 확인 통과")


if __name__ == "__main__":
    demo()
