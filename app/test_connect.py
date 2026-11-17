"""현직자 연결 카드 화면 확인(가짜 모드). 실행: python -m app.test_connect"""
import logging
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


    def test_second_draft_replaces_the_first_in_the_text_box(self):
        """다시 만들면 입력창도 새 초안으로 바뀐다(예전에는 처음 초안이 남았다)."""
        from ai import coffeechat

        drafts = iter([{"message": f"[받는 분 이름] [내 이름] [내 소개 한 줄] 초안 {n}번", "questions": ["가", "나", "다"]} for n in (1, 2)])
        with mock.patch.object(coffeechat, "draft", lambda *a: (next(drafts), None)):
            at = self.at.button(key="coffeechat_btn").click().run()
            self.assertIn("초안 1번", at.text_area(key="coffeechat_text").value)
            at = at.button(key="coffeechat_btn").click().run()
        self.assertIn("초안 2번", at.text_area(key="coffeechat_text").value)

    def test_fixed_draft_when_ai_fails(self):
        from ai import coffeechat
        from ai.bedrock import BedrockJSONError

        def failing(*args):
            raise BedrockJSONError("가짜 실패")

        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        with mock.patch.object(coffeechat, "draft", failing):
            at = self.at.button(key="coffeechat_btn").click().run()
        self.assertFalse(at.exception)
        self.assertIn("[내 이름]", at.text_area(key="coffeechat_text").value)
        self.assertTrue(any("기본 문안" in c.value for c in at.caption))


if __name__ == "__main__":
    unittest.main()
