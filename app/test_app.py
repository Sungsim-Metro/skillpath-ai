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
        self.assertEqual([t.label for t in self.at.tabs], ["시장 수요", "부족 역량", "학습 추천", "공고 직접 분석"])

    def test_extract_button_shows_result(self):
        at = self.at.button(key="extract_btn").click().run()
        self.assertFalse(at.exception)
        self.assertIn("추출 결과", [h.value for h in at.subheader])

    def test_level_dialog_requires_every_answer(self):
        from backend.levels import level_guide

        subskills = list(level_guide()["subskills"])
        at = self.at.sidebar.button(key="open_levels").click().run()
        self.assertEqual(at.get("progress")[0].proto.text, f"0 / {len(subskills)}개 응답")
        self.assertTrue(at.button(key="save_levels").disabled)
        for sid in subskills:
            at.session_state[f"lv_{sid}"] = 0
        at.session_state["lv_C1-4"] = 4
        at.sidebar.button(key="open_levels").click().run()
        self.assertFalse(at.button(key="save_levels").disabled)
        at.sidebar.button(key="open_levels").click()
        at = at.button(key="save_levels").click().run()
        self.assertFalse(at.exception)
        self.assertEqual({k: v for k, v in at.session_state["levels"].items() if v}, {"C1-4": 4})
        self.assertFalse(at.session_state["levels_example"])

    def test_renders_without_owned_skills(self):
        self.at.session_state["levels"] = {}
        self.at.session_state["levels_example"] = False
        at = self.at.run()
        self.assertFalse(at.exception)


if __name__ == "__main__":
    unittest.main()
