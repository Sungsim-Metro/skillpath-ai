"""추천 대 검증 에이전트 흐름 확인(가짜 모드). 실행: python -m ai.test_debate"""
import json
import logging
import os
import unittest
from unittest import mock

import ai.debate as debate
import ai.recommend as rec
from ai.bedrock import BedrockJSONError

DEMAND = {s["skill"]: s for s in json.loads((rec.SAMPLE_DIR / "demand.json").read_text(encoding="utf-8"))["skills"]}


def demand_of(skill: str) -> dict:
    d = DEMAND[skill]
    return {"postings": d["postings"], "of": 40, "required_ratio": round(d["required"] / d["postings"], 2)}


class DebateTest(unittest.TestCase):
    def setUp(self):
        debate._recent.clear()
        logging.disable(logging.CRITICAL)  # 일부러 낸 실패의 로그는 출력하지 않는다
        self.addCleanup(logging.disable, logging.NOTSET)
        patcher = mock.patch.dict(os.environ, {"BEDROCK_MOCK": "1", "RECOMMEND_DEBATE": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def build(self, skill, **kwargs):
        return debate.build_recommendation(skill, demand_of(skill), **kwargs)

    def test_off_is_identical_to_single_recommendation(self):
        with mock.patch.dict(os.environ, {"RECOMMEND_DEBATE": "0"}):
            self.assertEqual(self.build("Docker"), rec.build_recommendation("Docker", demand_of("Docker")))

    def test_all_pass(self):
        recommendation, result = self.build("Docker")
        self.assertEqual([c["review"]["status"] for c in recommendation["courses"]], ["passed"] * 3)
        self.assertEqual(recommendation["courses"], [
            {**c, "review": c2["review"]} for c, c2 in
            zip(rec.build_recommendation("Docker", demand_of("Docker"))[0]["courses"], recommendation["courses"])
        ])  # 통과면 이유와 match 는 그대로다
        self.assertEqual([c["stage"] for c in result.calls], ["recommend", "review"])

    def test_reason_objection_is_revised_once(self):
        recommendation, result = self.build("Kubernetes")
        second = recommendation["courses"][1]
        self.assertEqual(second["review"]["status"], "revised")
        self.assertNotIn("NetworkPolicies", second["reason"])
        self.assertEqual([c["review"]["status"] for c in recommendation["courses"]], ["passed", "revised", "passed"])
        self.assertEqual([c["stage"] for c in result.calls].count("revise"), 1)

    def test_coverage_objection_is_overruled_when_name_is_in_course(self):
        course = self.build("AWS")[0]["courses"][0]
        self.assertEqual(course["review"]["status"], "overruled")  # 통과와 구분해 표시한다
        self.assertEqual(course["match"], rec.build_recommendation("AWS", demand_of("AWS"))[0]["courses"][0]["match"])  # 기각이면 그대로

    def test_coverage_objection_lowers_match_when_name_is_absent(self):
        courses = self.build("Terraform")[0]["courses"]
        self.assertEqual(courses[0]["review"]["status"], "uncertain")
        self.assertEqual(courses[0]["match"], "uncertain")
        self.assertEqual([c["review"]["status"] for c in courses[1:]], ["passed", "passed"])

    def test_coverage_objection_lowers_a_certain_match(self):
        """학습 목표 열 개 중 한 줄에만 이름이 나오는 과정: 검색은 certain 으로 줬지만 반박을 받아들여 낮춘다."""
        before = rec.build_recommendation("CI/CD", demand_of("CI/CD"))[0]["courses"]
        after = self.build("CI/CD")[0]["courses"]
        self.assertEqual((before[0]["match"], after[0]["match"]), ("certain", "uncertain"))
        self.assertEqual(after[0]["review"]["status"], "uncertain")
        self.assertEqual([c["match"] for c in after[1:]], [c["match"] for c in before[1:]])

    def test_rewording_the_claim_is_not_a_revision(self):
        course = {"title": "Amazon EKS Networking", "objectives": ["Describe EKS networking"], "match": "certain"}
        r = {"verdict": "objection", "issue": "reason", "claim": "서비스 메시 운영", "comment": "없습니다.", "quote": None}
        old = "공고 40건 중 17건이 Kubernetes를 요구합니다. 이 과정은 서비스 메시 운영을 다룹니다."
        decide = lambda new: debate._decide("Kubernetes", course, r, old, new, frozenset({40.0, 17.0}))[0]["status"]  # noqa: E731
        self.assertEqual(decide("공고 40건 중 17건이 Kubernetes를 요구합니다. 이 과정은 서비스 메시의 운영을 다룹니다."), "uncertain")
        self.assertEqual(decide("이 과정은 EKS 네트워킹을 설명합니다."), "uncertain")  # 수요 숫자를 잃었다
        self.assertEqual(decide(None), "uncertain")
        self.assertEqual(decide("공고 40건 중 17건이 Kubernetes를 요구합니다. 이 과정은 EKS 네트워킹을 설명합니다."), "revised")

    def test_common_words_do_not_block_a_real_revision(self):
        course = {"title": "Amazon EKS Networking", "objectives": ["Describe EKS networking"], "match": "certain"}
        self.assertFalse(debate._claim_remains("Kubernetes", course, "이 과정은 컨테이너 격리와 서비스 메시 운영을 다룹니다.",
                                               "이 과정은 EKS 네트워킹 구성을 다룹니다."))
        self.assertTrue(debate._claim_remains("Kubernetes", course, "서비스 메시 운영", "이 과정은 서비스 메시의 운영을 다룹니다."))

    def test_coverage_is_overruled_only_when_objectives_name_the_skill(self):
        def course(title, objectives):
            return {"title": title, "objectives": objectives}
        self.assertFalse(debate._overrules_coverage("Docker", course("Docker Basics", ["Run containers"])))     # 제목에만 있다
        self.assertTrue(debate._overrules_coverage("Docker", course("Docker Basics", ["Build a Docker image"])))
        self.assertTrue(debate._overrules_coverage("Docker", course("Containers", ["Use Docker", "Tag Docker images", "a", "b", "c"])))
        self.assertFalse(debate._overrules_coverage("Docker", course("Data", ["Use Docker", "a", "b", "c", "d"])))

    def test_unreviewed_result_is_reused_briefly(self):
        with mock.patch.object(debate, "review", side_effect=BedrockJSONError("가짜 실패")) as failing:
            first, _ = self.build("Docker")
            second, _ = self.build("Docker")
        self.assertEqual(failing.call_count, 1)   # 잠깐은 다시 부르지 않는다
        self.assertEqual(first, second)
        with mock.patch.object(debate.time, "monotonic", return_value=debate.time.monotonic() + debate.RETRY_AFTER + 1):
            self.assertEqual(self.build("Docker")[0]["courses"][0]["review"]["status"], "passed")  # 시간이 지나면 다시 검증한다

    def test_failed_calls_are_recorded(self):
        with mock.patch.object(debate, "review", side_effect=BedrockJSONError("가짜 실패", {"inputTokens": 7, "outputTokens": 3, "totalTokens": 10})):
            _, result = self.build("Docker")
        self.assertEqual(result.calls[-1], {"stage": "review", "failed": True, "inputTokens": 7, "outputTokens": 3, "totalTokens": 10})
        self.assertEqual(result.usage["totalTokens"], sum(c["totalTokens"] for c in result.calls))

    def test_unreviewed_result_is_not_served_from_cache(self):
        from backend import api
        calls = []

        def fake(skill, demand):
            calls.append(skill)
            status = "unreviewed" if len(calls) == 1 else "passed"
            return {"gap_skill": skill, "demand": demand, "courses": [{"review": {"status": status}}]}, None

        demand = {"total_postings": 40, "skills": [{"skill": "Docker", "postings": 20, "required": 9}]}
        with mock.patch.object(api, "is_mock", return_value=False), mock.patch.object(api, "get_demand", return_value=demand), \
                mock.patch.object(debate, "build_recommendation", side_effect=fake), \
                mock.patch.object(api, "_recommend_cache", type(api._recommend_cache)()):
            job = "cloud_engineer"
            first = api.get_recommendations(job, ["Docker"])
            second = api.get_recommendations(job, ["Docker"])
            third = api.get_recommendations(job, ["Docker"])
            with mock.patch.dict(os.environ, {"RECOMMEND_DEBATE": "0"}):
                api.get_recommendations(job, ["Docker"])
        self.assertEqual(first[0]["courses"][0]["review"]["status"], "unreviewed")
        self.assertEqual(second, third)          # 통과한 결과는 캐시에서 온다
        self.assertEqual(len(calls), 3)          # 실패 1 + 다시 검증 1 + 끈 상태 1(켠 결과를 돌려주지 않는다)

    def test_match_is_never_raised(self):
        before = {c["title"]: c["match"] for s in ("Docker", "Kubernetes", "AWS", "Terraform", "CI/CD")
                  for c in rec.build_recommendation(s, demand_of(s))[0]["courses"]}
        for skill in ("Docker", "Kubernetes", "AWS", "Terraform", "CI/CD"):
            for c in self.build(skill)[0]["courses"]:
                self.assertFalse(before[c["title"]] == "uncertain" and c["match"] == "certain")

    def test_review_failure_keeps_recommendation(self):
        with mock.patch.object(debate, "review", side_effect=BedrockJSONError("가짜 실패")):
            recommendation, _ = self.build("Docker")
        self.assertEqual([c["review"]["status"] for c in recommendation["courses"]], ["unreviewed"] * 3)
        self.assertEqual([c["reason"] for c in recommendation["courses"]],
                         [c["reason"] for c in rec.build_recommendation("Docker", demand_of("Docker"))[0]["courses"]])

    def test_any_review_error_keeps_recommendation(self):
        """호출 제한·시간 초과 같은 오류도 추천을 막지 않는다."""
        with mock.patch.object(debate, "review", side_effect=RuntimeError("ThrottlingException")):
            recommendation, _ = self.build("Docker")
        self.assertEqual([c["review"]["status"] for c in recommendation["courses"]], ["unreviewed"] * 3)
        with mock.patch.object(debate, "_revise", side_effect=TimeoutError()):
            self.assertEqual(self.build("Kubernetes")[0]["courses"][1]["review"]["status"], "uncertain")

    def test_failed_revision_stays_uncertain(self):
        with mock.patch.object(debate, "_revise", side_effect=BedrockJSONError("가짜 실패")):
            second = self.build("Kubernetes")[0]["courses"][1]
        self.assertEqual(second["review"]["status"], "uncertain")
        self.assertIn("NetworkPolicies", second["reason"])  # 고치지 못했으면 원래 이유를 그대로 둔다

    def test_validate_reviews_rejects_made_up_grounds(self):
        courses = rec.candidate_courses("Docker")
        reasons = {c["course_id"]: "이 과정은 컨테이너를 다룹니다." for c in courses}
        review_input = debate.review_input_of("Docker", demand_of("Docker"), courses, reasons, None)
        ok = {"course_id": None, "verdict": "pass", "issue": None, "claim": None, "quote": None, "comment": None}

        def reviews(first):
            return {"reviews": [first, *[{**ok, "course_id": c["course_id"]} for c in courses[1:]]]}

        cid = courses[0]["course_id"]
        bad = [
            {**ok, "course_id": cid, "verdict": "objection", "issue": "coverage", "quote": "원문에 없는 문장", "comment": "다루지 않습니다."},
            {**ok, "course_id": cid, "verdict": "objection", "issue": "reason", "claim": "이유에 없는 말", "comment": "근거가 없습니다."},
            {**ok, "course_id": cid, "verdict": "objection", "issue": "level", "comment": "어렵습니다."},  # user_level 이 없다
            {**ok, "course_id": cid, "verdict": "objection", "issue": "coverage", "comment": "Azure Functions 과정이 낫습니다."},
            {**ok, "course_id": cid, "verdict": "maybe"},
            {**ok, "course_id": cid, "verdict": "objection", "issue": "reason", "claim": "다", "comment": "근거가 없습니다."},  # 너무 짧다
            {**ok, "course_id": cid, "verdict": "objection", "issue": "coverage", "quote": courses[0]["title"][:5], "comment": "다루지 않습니다."},  # 제목의 조각
            {**ok, "course_id": cid, "verdict": "objection", "issue": "coverage", "comment": "다루지 않습니다. " * 20},  # 너무 길다
        ]
        for first in bad:
            with self.assertRaises(ValueError, msg=first):
                debate.validate_reviews(reviews(first), review_input)
        with self.assertRaises(ValueError):
            debate.validate_reviews({"reviews": [{**ok, "course_id": cid}]}, review_input)  # 과정이 빠졌다
        debate.validate_reviews(reviews({**ok, "course_id": cid}), review_input)
        # 수요 문장은 코드가 계산한 값이라 반박 대상이 아니다
        reasons[cid] = "공고 40건 중 20건이 Docker를 요구합니다. 이 과정은 컨테이너를 다룹니다."
        review_input = debate.review_input_of("Docker", demand_of("Docker"), courses, reasons, None)
        with self.assertRaises(ValueError):
            debate.validate_reviews(reviews({**ok, "course_id": cid, "verdict": "objection", "issue": "reason",
                                             "claim": "공고 40건 중 20건이 Docker를 요구합니다", "comment": "근거가 없습니다."}), review_input)
        self.assertIn("code_check", review_input["courses"][0])
        self.assertEqual(review_input["demand"]["postings"], 20)

    def test_prompt_example_passes_its_own_checks(self):
        from ai.prompts import review_v1
        debate.validate_reviews(review_v1._EXAMPLE_ANSWER, review_v1._EXAMPLE_INPUT)


if __name__ == "__main__":
    unittest.main()
