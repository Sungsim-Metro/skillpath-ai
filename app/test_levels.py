"""보유 수준 입력 화면 확인(가짜 모드). 실행: python -m app.test_levels"""
import os
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

MAIN = str(Path(__file__).resolve().parent / "main.py")


class LevelsScreenTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"BEDROCK_MOCK": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.at = AppTest.from_file(MAIN, default_timeout=60).run()

    def test_learned_skill_changes_gap_and_recommendation(self):
        """배워봄으로 고르면 부족 기술에 '보강'으로 남고 추천 안내가 붙는다."""
        at = self.at.sidebar.button_group(key="learned").set_value(["AWS"]).run()
        self.assertFalse(at.exception)
        self.assertTrue(any("중급 과정을 먼저" in c.value for c in at.caption))

    def test_skill_moves_from_learned_to_used(self):
        """배워봄으로 고른 기술을 써봄으로 옮겨도 오류가 없고 배워봄에서 빠진다."""
        at = self.at.sidebar.button_group(key="learned").set_value(["AWS", "Docker"]).run()
        at = at.sidebar.button_group(key="owned").set_value(["Python", "AWS"]).run()
        self.assertFalse(at.exception)
        self.assertEqual(at.sidebar.button_group(key="learned").value, ["Docker"])


if __name__ == "__main__":
    unittest.main()
