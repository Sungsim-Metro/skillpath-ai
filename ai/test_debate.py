"""추천 대 검증 에이전트 흐름 확인(가짜 모드). 실행: python -m ai.test_debate"""
import json
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
        self.assertEqual(course["review"]["status"], "passed")
        self.assertTrue(course["review"]["overruled"])

    def test_coverage_objection_lowers_match_when_name_is_absent(self):
        courses = self.build("Terraform")[0]["courses"]
        self.assertEqual(courses[0]["review"]["status"], "uncertain")
        self.assertEqual(courses[0]["match"], "uncertain")
        self.assertEqual([c["review"]["status"] for c in courses[1:]], ["passed", "passed"])

    def test_match_is_never_raised(self):
        before = {c["title"]: c["match"] for s in ("Docker", "Kubernetes", "AWS", "Terraform")
                  for c in rec.build_recommendation(s, demand_of(s))[0]["courses"]}
        for skill in ("Docker", "Kubernetes", "AWS", "Terraform"):
            for c in self.build(skill)[0]["courses"]:
                self.assertFalse(before[c["title"]] == "uncertain" and c["match"] == "certain")

    def test_review_failure_keeps_recommendation(self):
        with mock.patch.object(debate, "review", side_effect=BedrockJSONError("가짜 실패")):
            recommendation, _ = self.build("Docker")
        self.assertEqual([c["review"]["status"] for c in recommendation["courses"]], ["unreviewed"] * 3)
        self.assertEqual([c["reason"] for c in recommendation["courses"]],
                         [c["reason"] for c in rec.build_recommendation("Docker", demand_of("Docker"))[0]["courses"]])

    def test_failed_revision_stays_uncertain(self):
        with mock.patch.object(debate, "_revise", side_effect=BedrockJSONError("가짜 실패")):
            second = self.build("Kubernetes")[0]["courses"][1]
        self.assertEqual(second["review"]["status"], "uncertain")
        self.assertIn("NetworkPolicies", second["reason"])  # 고치지 못했으면 원래 이유를 그대로 둔다

    def test_validate_reviews_rejects_made_up_grounds(self):
        courses = rec.candidate_courses("Docker")
        reasons = {c["course_id"]: "이 과정은 컨테이너를 다룹니다." for c in courses}
        review_input = debate.review_input_of("Docker", courses, reasons, None)
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
        ]
        for first in bad:
            with self.assertRaises(ValueError, msg=first):
                debate.validate_reviews(reviews(first), review_input)
        with self.assertRaises(ValueError):
            debate.validate_reviews({"reviews": [{**ok, "course_id": cid}]}, review_input)  # 과정이 빠졌다
        debate.validate_reviews(reviews({**ok, "course_id": cid}), review_input)


if __name__ == "__main__":
    unittest.main()
