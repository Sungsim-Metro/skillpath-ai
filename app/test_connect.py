"""현직자 연결 카드 화면 확인(가짜 모드). 실행: python -m app.test_connect"""
import os
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

MAIN = str(Path(__file__).resolve().parent / "main.py")


class ConnectScreenTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"BEDROCK_MOCK": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.at = AppTest.from_file(MAIN, default_timeout=60).run()

    def test_coffeechat_draft_appears_after_button(self):
        """메시지 초안은 버튼을 눌렀을 때만 만들어진다."""
        self.assertFalse([t for t in self.at.text_area if t.key == "coffeechat_text"])
        at = self.at.button(key="coffeechat_btn").click().run()
        self.assertFalse(at.exception)
        self.assertIn("[내 이름]", at.text_area(key="coffeechat_text").value)


if __name__ == "__main__":
    unittest.main()
