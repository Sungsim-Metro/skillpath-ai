"""운영 현황 탭 확인(가짜 모드). 실행: python -m app.test_usage_tab"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

MAIN = str(Path(__file__).resolve().parent / "main.py")


class UsageTabTest(unittest.TestCase):
    def test_usage_tab_only_with_admin_param(self):
        """운영 현황 탭은 ?admin=<ADMIN_KEY> 일 때만 보이고, 기록이 있으면 호출 수가 나온다."""
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8", delete=False) as f:
            f.write(json.dumps({"ts": "2026-11-17T10:00:00", "stage": "recommend", "attempt": 1, "inputTokens": 1200,
                                "outputTokens": 300, "model": "some-model", "mock": False}) + "\n")
        self.addCleanup(os.unlink, f.name)
        with mock.patch.dict(os.environ, {"BEDROCK_MOCK": "1", "USAGE_LOG": f.name, "ADMIN_KEY": "열쇠-k1"}):
            plain = AppTest.from_file(MAIN, default_timeout=60).run()
            self.assertNotIn("운영 현황", [t.label for t in plain.tabs])
            for wrong in ("1", "열쇠", ""):
                guess = AppTest.from_file(MAIN, default_timeout=60)
                guess.query_params["admin"] = wrong
                self.assertNotIn("운영 현황", [t.label for t in guess.run().tabs], wrong)
            at = AppTest.from_file(MAIN, default_timeout=60)
            at.query_params["admin"] = "열쇠-k1"
            at.run()
            with mock.patch.dict(os.environ, {"ADMIN_KEY": ""}):  # 열쇠를 정하지 않았으면 어떤 값으로도 열리지 않는다
                unset = AppTest.from_file(MAIN, default_timeout=60)
                unset.query_params["admin"] = ""
                self.assertNotIn("운영 현황", [t.label for t in unset.run().tabs])
        self.assertFalse(at.exception)
        self.assertEqual(at.tabs[-1].label, "운영 현황")
        self.assertIn("1번", [m.value for m in at.metric])
        self.assertIn("1,200", [m.value for m in at.metric])
        self.assertTrue(any("단가가 없는 모델" in w.value for w in at.warning))


if __name__ == "__main__":
    unittest.main()
