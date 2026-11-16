"""현직자 연결: 소모임 짝짓기와 검색 링크, 메시지 초안 검사. 실행: python -m backend.test_communities"""
import os
import unittest
from unittest import mock
from urllib.parse import unquote

from ai import coffeechat
from backend import api, communities

JOB = "cloud_engineer"


class CommunitiesTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"BEDROCK_MOCK": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_data_file_has_no_people_and_valid_areas(self):
        data = communities.load()
        areas = set(api._skill_areas()["areas"])
        self.assertTrue(data["checked"] and data["source"] and data["limits"])
        for c in data["communities"]:
            self.assertEqual(set(c), {"id", "name", "areas", "kind", "place", "link", "last_seen", "note"})
            self.assertLessEqual(set(c["areas"]), areas, c["id"])
            self.assertIn(c["kind"], ("topic", "general", "region"))
            self.assertTrue(c["link"].startswith("https://"))
            self.assertEqual(bool(c["areas"]), c["kind"] == "topic", c["id"])

    def test_suggest_follows_gap(self):
        found = communities.suggest(api.get_area_gap(JOB, ["Python", "Linux", "Git"]))
        ids = [t["community"]["id"] for t in found["topic"]]
        self.assertIn("container", ids)            # 컴퓨팅·서버가 부족하다
        self.assertIn("네트워크", found["unmatched"])  # 맞는 소모임이 없는 영역은 없다고 알린다
        self.assertLessEqual(len(ids), communities.MAX_TOPIC)
        owned_all = [s["skill"] for s in api.get_demand(JOB)["skills"]]
        full = communities.suggest(api.get_area_gap(JOB, owned_all))
        self.assertEqual(full["topic"], [])
        self.assertEqual(full["unmatched"], [])
        self.assertTrue(full["general"])           # 입문·대학생 모임은 늘 있다

    def test_bigger_gap_comes_first(self):
        rows = [
            {"area_id": "C4", "area": "보안", "demand": 10, "owned": 9},
            {"area_id": "C7", "area": "아키텍처 설계", "demand": 10, "owned": 0},
        ]
        found = communities.suggest(rows)
        self.assertEqual(found["topic"][0]["areas"], ["아키텍처 설계"])

    def test_people_links_only_build_urls(self):
        links = communities.people_search_links("클라우드 엔지니어", ["AWS", "Docker", "Kubernetes", "Terraform"])
        self.assertEqual(len(links), 3)
        self.assertTrue(all(link["url"].startswith(communities.LINKEDIN_PEOPLE_SEARCH) for link in links))
        self.assertIn("클라우드 엔지니어 AWS", unquote(links[0]["url"]))

    def test_draft_keeps_blanks_and_three_questions(self):
        draft, result = coffeechat.draft("클라우드 엔지니어", ["AWS", "Docker"], ["Python"])
        self.assertTrue(all(b in draft["message"] for b in coffeechat.prompt.BLANKS))
        self.assertEqual(len(draft["questions"]), 3)
        self.assertEqual(result.attempts, 1)
        with self.assertRaises(ValueError):
            coffeechat.draft("클라우드 엔지니어", [], ["Python"])

    def test_validate_draft_rejects_made_up_details(self):
        llm_input = coffeechat.llm_input_of("클라우드 엔지니어", ["Docker"], ["Python"])
        ok = {"message": "[받는 분 이름]님, [내 이름]입니다. [내 소개 한 줄] Docker 공부 방법을 여쭙고 싶습니다. 20분만 부탁드립니다.",
              "questions": ["Docker는 실무에서 어떻게 쓰나요?", "Python은 어디에 쓰나요?", "공부 순서는요?"]}
        coffeechat.validate_draft(ok, llm_input)
        bad = [
            {**ok, "message": ok["message"].replace("[내 이름]", "김철수")},                    # 이름을 지어냄
            {**ok, "message": ok["message"] + " 저는 3년 동안 공부했습니다."},                  # 입력에 없는 숫자
            {**ok, "questions": [*ok["questions"][:2], "Kubernetes도 해야 하나요?"]},           # 입력에 없는 기술
            {**ok, "questions": ok["questions"][:2]},
            {**ok, "questions": [*ok["questions"][:2], "Dock 은 무엇인가요?"]},                 # 입력 이름의 조각은 통과하지 못한다
        ]
        for data in bad:
            with self.assertRaises(ValueError, msg=data):
                coffeechat.validate_draft(data, llm_input)


if __name__ == "__main__":
    unittest.main()
