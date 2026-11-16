"""화면이 가짜 모드에서 오류 없이 뜨는지 확인한다. 화면 내용의 옳고 그름은 보지 않는다.

실행: 저장소 루트에서 `python -m app.test_app`
"""
import os
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

MAIN = str(Path(__file__).resolve().parent / "main.py")


class AppSmokeTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"BEDROCK_MOCK": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.at = AppTest.from_file(MAIN, default_timeout=60).run()

    def test_all_tabs_render_in_mock_mode(self):
        self.assertFalse(self.at.exception)
        self.assertEqual([t.label for t in self.at.tabs], ["시장 수요", "부족 역량", "학습 추천", "공고 직접 분석", "진단 보고서"])

    def test_extract_button_shows_result(self):
        at = self.at.button(key="extract_btn").click().run()
        self.assertFalse(at.exception)
        self.assertIn("추출 결과", [h.value for h in at.subheader])

    def test_renders_without_owned_skills(self):
        at = self.at.sidebar.button_group[0].set_value([]).run()
        self.assertFalse(at.exception)

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

    def test_report_tab_has_download_button(self):
        self.assertTrue([b for b in self.at.get("download_button") if b.key == "report_btn"])


if __name__ == "__main__":
    unittest.main()
