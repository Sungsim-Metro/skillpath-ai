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

    def test_renders_without_owned_skills(self):
        at = self.at.sidebar.button_group[0].set_value([]).run()
        self.assertFalse(at.exception)

    def test_usage_tab_only_with_admin_param(self):
        """운영 현황 탭은 ?admin=1 일 때만 보이고, 기록이 있으면 호출 수가 나온다."""
        import json
        import tempfile

        self.assertNotIn("운영 현황", [t.label for t in self.at.tabs])
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8", delete=False) as f:
            f.write(json.dumps({"ts": "2026-11-17T10:00:00", "stage": "recommend", "attempt": 1, "inputTokens": 1200,
                                "outputTokens": 300, "model": "some-model", "mock": False}) + "\n")
        with mock.patch.dict(os.environ, {"USAGE_LOG": f.name}):
            at = AppTest.from_file(MAIN, default_timeout=60)
            at.query_params["admin"] = "1"
            at.run()
        os.unlink(f.name)
        self.assertFalse(at.exception)
        self.assertEqual(at.tabs[-1].label, "운영 현황")
        self.assertIn("1번", [m.value for m in at.metric])
        self.assertIn("1,200", [m.value for m in at.metric])
        self.assertTrue(any("단가가 없는 모델" in w.value for w in at.warning))


if __name__ == "__main__":
    unittest.main()
