"""회원 대화 기록 확인: 마스킹, 비회원 미저장, 회원별 분리, 저장 실패가 상담을 막지 않음. 실행: python -m unittest backend.test_chat_history"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend import chat_history

S1, S2 = "a" * 32, "b" * 32
COURSE = {"course_id": "c1", "title": "AWS 기초"}


class MaskTest(unittest.TestCase):
    def test_masks_contact_like_text_but_keeps_skills(self) -> None:
        text = "메일은 jh.kim+1@test.co.kr, 폰 010-1234-5678, 02-123-4567, 주민 900101-1234567입니다. Docker 3년, 포트 8080"
        self.assertEqual(
            chat_history.mask(text),
            "메일은 [이메일], 폰 [전화번호], [전화번호], 주민 [주민번호]입니다. Docker 3년, 포트 8080")
        self.assertEqual(chat_history.mask("번호는01012345678입니다"), "번호는[전화번호]입니다")


class LocalHistoryTest(unittest.TestCase):
    def setUp(self) -> None:
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.path = Path(work.name) / "chat.sqlite3"
        self.enterContext(patch.dict(os.environ, {"BEDROCK_MOCK": "1", "SKILLPATH_MOCK_CHAT_DB": str(self.path)}))
        self.resource = self.enterContext(patch.object(chat_history, "_resource"))

    def tearDown(self) -> None:
        self.resource.assert_not_called()

    def test_guest_is_never_stored(self) -> None:
        for guest in (None, "", "   "):
            self.assertFalse(chat_history.append_turn(guest, S1, "질문", "답"))
            self.assertEqual(chat_history.list_sessions(guest), [])
            self.assertEqual(chat_history.load_session(guest, S1), [])
        self.assertFalse(self.path.exists())

    def test_members_get_their_own_sessions_in_order(self) -> None:
        self.assertTrue(chat_history.append_turn("kim", S1, "Docker 써봤어요 010-1234-5678", "알겠습니다", [COURSE]))
        self.assertTrue(chat_history.append_turn("kim", S1, "부족한 기술은?", "Linux입니다"))
        self.assertTrue(chat_history.append_turn("kim", S2, "새 대화" + "가" * 50, "답"))
        chat_history.append_turn("lee", S1, "남의 대화", "답")
        self.assertEqual(
            chat_history.load_session("kim", S1),
            [("Docker 써봤어요 [전화번호]", "알겠습니다", [COURSE]), ("부족한 기술은?", "Linux입니다", [])])
        sessions = chat_history.list_sessions("kim")
        self.assertEqual([s["session_id"] for s in sessions], [S2, S1])  # 최근 대화가 위
        self.assertEqual(sessions[0]["title"], "새 대화" + "가" * 26 + "…")
        self.assertEqual(sessions[1]["title"], "Docker 써봤어요 [전화번호]")  # 제목은 첫 질문, 가린 뒤
        self.assertEqual(chat_history.load_session("lee", S2), [])  # 다른 회원의 세션은 열리지 않는다

    def test_bad_session_id_is_rejected_and_save_failure_does_not_raise(self) -> None:
        with self.assertRaises(ValueError):
            chat_history.append_turn("kim", "S#x", "질문", "답")
        with patch.object(chat_history, "_connect", side_effect=OSError("secret 닉네임 kim")), \
                self.assertLogs(chat_history.logger, "WARNING") as logs:
            self.assertFalse(chat_history.append_turn("kim", S1, "질문", "답"))
        self.assertNotIn("kim", "".join(logs.output))
        self.assertIn("OSError", "".join(logs.output))


class DynamoHistoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(patch.dict(os.environ, {"BEDROCK_MOCK": "0", "DYNAMODB_CHAT_TABLE": "chat-test"}))
        self.table = self.enterContext(patch.object(chat_history, "_resource")).return_value.Table.return_value

    def test_append_writes_a_turn_item_and_a_session_item(self) -> None:
        self.assertTrue(chat_history.append_turn("kim", S1, "메일 a@b.com", "답", [COURSE]))
        turn = self.table.put_item.call_args.kwargs["Item"]
        self.assertEqual((turn["nickname"], turn["prompt"]), ("kim", "메일 [이메일]"))
        self.assertTrue(turn["sk"].startswith(f"T#{S1}#"))
        self.assertIsInstance(turn["expires_at"], int)
        update = self.table.update_item.call_args.kwargs
        self.assertEqual(update["Key"], {"nickname": "kim", "sk": f"S#{S1}"})
        self.assertIn("if_not_exists(title", update["UpdateExpression"])

    def test_list_and_load_read_back_what_was_written(self) -> None:
        self.table.query.side_effect = [
            {"Items": [{"sk": f"S#{S1}", "title": "첫", "updated_at": "2026-11-20T01"},
                       {"sk": f"S#{S2}", "title": "둘", "updated_at": "2026-11-20T02"}]},
            {"Items": [{"sk": f"T#{S1}#2", "prompt": "q2", "answer": "a2", "courses": "[]"},
                       {"sk": f"T#{S1}#1", "prompt": "q1", "answer": "a1", "courses": '[{"course_id": "c1"}]'}]},
        ]
        self.assertEqual([s["title"] for s in chat_history.list_sessions("kim")], ["둘", "첫"])
        self.assertEqual(chat_history.load_session("kim", S1),
                         [("q1", "a1", [{"course_id": "c1"}]), ("q2", "a2", [])])

    def test_missing_table_name_is_a_logged_failure_for_append_and_an_error_for_reads(self) -> None:
        with patch.dict(os.environ, {"DYNAMODB_CHAT_TABLE": ""}):
            with self.assertLogs(chat_history.logger, "WARNING"):
                self.assertFalse(chat_history.append_turn("kim", S1, "q", "a"))
            with self.assertRaises(ValueError):
                chat_history.list_sessions("kim")


if __name__ == "__main__":
    unittest.main()
