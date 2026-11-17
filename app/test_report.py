"""진단 보고서 확인(가짜 모드). 실행: python -m app.test_report"""
import os
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

MAIN = str(Path(__file__).resolve().parent / "main.py")


class ReportTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"BEDROCK_MOCK": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_report_matches_screen_and_escapes_text(self):
        """보고서의 숫자는 화면이 받은 값 그대로이고, 글자는 HTML 로 해석되지 않는다."""
        from datetime import date

        from app.report import build_report, file_name
        from backend import api

        owned = ["Python", "Linux", "Git"]
        demand, gap = api.get_demand("cloud_engineer"), api.get_gap("cloud_engineer", owned)
        missing = [r for r in gap if not r["owned"]]
        recs = api.get_recommendations("cloud_engineer", [r["skill"] for r in missing])
        html = build_report(job_title="클라우드 엔지니어", demand=demand, gap_rows=gap,
                            area_rows=api.get_area_gap("cloud_engineer", owned), recommendations=recs, owned=owned,
                            mock=True, today=date(2026, 11, 17))
        self.assertIn(f"부족<b>{len(missing)}개</b>", html)
        self.assertIn(f"채용공고 {demand['total_postings']}건", html)
        for r in missing:
            self.assertIn(f"{r['postings']} / {r['of']}", html)
        for rec in recs:
            for c in rec["courses"]:
                self.assertIn(c["url"], html)
        self.assertIn("가짜 데이터 모드", html)
        self.assertEqual(file_name(date(2026, 11, 17)), "skillpath-report-20261117.html")
        recs[0]["courses"][0].update(title="<script>alert(1)</script>", url="javascript:alert(1)")
        bad = build_report(job_title="<b>x</b>", demand=demand, gap_rows=gap, area_rows=[], recommendations=recs, owned=owned)
        self.assertNotIn("<script>alert(1)</script>", bad)
        self.assertNotIn("javascript:alert(1)", bad)
        self.assertNotIn("<b>x</b>", bad)

    def test_report_says_why_recommendations_are_missing_or_partial(self):
        from app.report import build_report

        demand = {"total_postings": 40, "skills": [], "sources": []}
        gap = [{"skill": s, "owned": False, "area": "A", "postings": 10, "of": 40, "ratio": 0.25, "required_ratio": 0.5} for s in ("X", "Y")]
        rec = {"gap_skill": "X", "demand": {"of": 40, "postings": 10, "required_ratio": 0.5}, "courses": [
            {"title": "T", "url": "https://example.com", "level": "기초", "prerequisites": "없음", "reason": "이유", "match": "uncertain",
             "evidence": {"text": "OTHER SKILL SENTENCE", "field": "objectives", "about": "subskill", "subskill": "S"}},
            {"title": "T2", "url": "https://example.com", "level": "기초", "prerequisites": "없음", "reason": "이유", "match": "certain",
             "evidence": {"text": "REAL SENTENCE", "field": "objectives", "about": "skill", "subskill": None}}]}
        build = lambda **kw: build_report(job_title="직무", demand=demand, gap_rows=gap, area_rows=[], owned=[], **kw)  # noqa: E731
        failed = build(recommendations=[], recommend_failed=True)
        self.assertIn("추천을 불러오지 못해", failed)
        self.assertNotIn("부족한 기술이 없어", failed)
        partial = build(recommendations=[rec])
        self.assertIn("이번에 추천하지 않은 기술: Y", partial)
        self.assertIn("REAL SENTENCE", partial)
        self.assertNotIn("OTHER SKILL SENTENCE", partial)   # 같은 영역일 뿐인 문장은 인용하지 않는다(화면과 같은 기준)

    def test_report_tab_has_download_button(self):
        self.assertTrue([b for b in AppTest.from_file(MAIN, default_timeout=60).run().get("download_button") if b.key == "report_btn"])



if __name__ == "__main__":
    unittest.main()
