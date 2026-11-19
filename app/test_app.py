"""화면이 가짜 모드에서 오류 없이 뜨는지 확인한다. 화면 내용의 옳고 그름은 보지 않는다.

실행: 저장소 루트에서 `python -m app.test_app`
"""
import json
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
        self.assertEqual([t.label for t in self.at.tabs], ["시장 수요", "부족 역량", "학습 추천", "공고 직접 분석"])

    def test_extract_button_shows_result(self):
        at = self.at.button(key="extract_btn").click().run()
        self.assertFalse(at.exception)
        self.assertIn("추출 결과", [h.value for h in at.subheader])

    def test_level_dialog_requires_every_answer(self):
        from backend.levels import level_guide

        subskills = list(level_guide()["subskills"])

        def reopen(at, button=None):
            # AppTest 는 모달 안 클릭 뒤 모달을 다시 그리지 않아, 같은 실행에서 모달 열기도 누른다
            at.sidebar.button(key="open_levels").click()
            if button:
                at.button(key=button).click()
            return at.run()

        at = reopen(self.at)
        self.assertTrue(at.get("progress")[0].proto.text.startswith(f"0 / {len(subskills)}개 응답 · 남은 시간 약"))
        self.assertNotIn("save_levels", [b.key for b in at.button])  # 저장은 마지막 영역에만
        at = reopen(at, "lvb_C1-4_4")  # 카드를 누르면 그 단계를 고른다
        self.assertEqual(at.session_state["lv_C1-4"], 4)
        at = reopen(at, "lvnav_next")
        self.assertIn("2/8", at.subheader[-1].value)
        for sid in subskills:
            if sid != "C1-4":
                at.session_state[f"lv_{sid}"] = None if sid == "C8-3" else 0
        at.session_state["lv_page"] = 7
        at = reopen(at)
        self.assertTrue(at.button(key="save_levels").disabled)
        at = reopen(at, "lvb_C8-3_0")
        self.assertFalse(at.button(key="save_levels").disabled)
        at = reopen(at, "save_levels")
        self.assertFalse(at.exception)
        self.assertEqual({k: v for k, v in at.session_state["levels"].items() if v}, {"C1-4": 4})
        self.assertFalse(at.session_state["levels_example"])
        self.assertNotIn("lv_page", at.session_state)

    def test_renders_without_owned_skills(self):
        self.at.session_state["levels"] = {}
        self.at.session_state["levels_example"] = False
        at = self.at.run()
        self.assertFalse(at.exception)


def _market_without_personal_demand():
    from app.common import Ctx
    from app.tabs.gap import render

    render(Ctx(job="cloud_engineer", demand=None, demand_err="수요 미연결", owned=[], levels={},
               skill_options=[], gap_rows=None, gap_err="수요 미연결"))


class MarketGapScreenTest(unittest.TestCase):
    def test_market_gap_shows_owned_skills_without_changing_market_values(self):
        rows = [{"industry": "유통", "skill": "AWS", "demand_pct": 60.0, "supply_pct": 40.0, "gap_pp": 20.0},
                {"industry": "유통", "skill": "SQL", "demand_pct": 40.0, "supply_pct": 60.0, "gap_pp": -20.0}]
        with mock.patch.dict(os.environ, {"BEDROCK_MOCK": "1"}), \
             mock.patch("backend.api.owned_skill_names", return_value=["AWS"]), \
             mock.patch("backend.api.get_market_gap", return_value={"rows": rows, "source": "검산 자료"}):
            at = AppTest.from_file(MAIN, default_timeout=60).run()
        self.assertFalse(at.exception)
        table = next(frame.value for frame in at.dataframe if "산업" in frame.value.columns)
        self.assertEqual(table["내 보유"].tolist(), ["보유", "-"])
        self.assertEqual(table["Gap"].tolist(), [20.0, -20.0])

    def test_empty_job_demand_keeps_industry_analysis_available(self):
        demand = {"total_postings": 0, "skills": []}
        rows = [{"industry": "유통", "skill": "AWS", "demand_pct": 100.0, "supply_pct": 100.0, "gap_pp": 0.0}]
        with mock.patch.dict(os.environ, {"BEDROCK_MOCK": "1"}), \
             mock.patch("backend.api.get_demand", return_value=demand), \
             mock.patch("backend.api.get_market_gap", return_value={"rows": rows, "source": "예시 입력"}):
            at = AppTest.from_file(MAIN, default_timeout=60).run()
        self.assertFalse(at.exception)
        self.assertEqual(at.selectbox(key="market_industry").value, "유통")

    def test_industry_selection_and_heatmap_without_personal_demand(self):
        rows = [
            {"industry": industry, "skill": skill, "demand_pct": demand,
             "supply_pct": supply, "gap_pp": gap}
            for industry, skill, demand, supply, gap in [
                ("유통", "AWS", 60., 80., -20.), ("유통", "SQL", 40., 20., 20.),
                ("금융", "AWS", 25., 80., -55.), ("금융", "SQL", 75., 20., 55.),
            ]
        ]
        with mock.patch("backend.api.get_market_gap", return_value={"rows": rows, "source": "예시 입력"}) as get_market:
            at = AppTest.from_function(_market_without_personal_demand).run()
            self.assertFalse(at.exception)
            selector = at.selectbox(key="market_industry")
            self.assertEqual(selector.options, ["유통", "금융"])
            self.assertTrue(any("학습 프로그램의 기술 공급 비중" in caption.value for caption in at.caption))
            charts = [json.loads(c.proto.spec) for c in at.get("vega_lite_chart")]
            self.assertEqual(charts[0]["encoding"]["y"]["sort"], ["AWS", "SQL"])
            self.assertEqual(charts[1]["encoding"]["y"]["sort"], ["SQL", "AWS"])
            at = selector.set_value("금융").run()
            self.assertFalse(at.exception)
            bar = json.loads(at.get("vega_lite_chart")[0].proto.spec)
            self.assertEqual(bar["encoding"]["y"]["sort"], ["SQL", "AWS"])
            self.assertEqual(len(at.dataframe[0].value), len(rows))
            self.assertTrue(at.get("download_button"))
            get_market.assert_called_with()

    def test_empty_table_and_missing_files_explain_absence(self):
        with mock.patch("backend.api.get_market_gap", return_value={"rows": [], "source": "예시 입력"}):
            at = AppTest.from_function(_market_without_personal_demand).run()
            self.assertFalse(at.exception)
            self.assertIn("매칭된 기술", at.info[-1].value)
            self.assertFalse(at.selectbox)
        with mock.patch("backend.api.get_market_gap", side_effect=FileNotFoundError):
            at = AppTest.from_function(_market_without_personal_demand).run()
            self.assertFalse(at.exception)
            self.assertIn("data/courses/courses.csv", at.info[-1].value)
            self.assertIn("outputs/learning_program_gap_table.csv", at.info[-1].value)


if __name__ == "__main__":
    unittest.main()
