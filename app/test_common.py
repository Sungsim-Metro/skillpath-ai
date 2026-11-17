"""화면 도우미 load 가 실제 모드(AWS) 오류를 어떻게 안내하는지 확인한다.

실행: 저장소 루트에서 `python -m app.test_common`
"""
import logging
import os
import unittest
from pathlib import Path
from unittest import mock

from botocore.exceptions import ClientError, ProfileNotFound
from streamlit.testing.v1 import AppTest

from app.common import Pending, error_kind, load

MAIN = str(Path(__file__).resolve().parent / "main.py")
SECRET = "arn:aws:sts::ACCOUNT-ID:assumed-role/app-role/i-0abc"  # 오류 메시지에 섞여 오는 값의 예


def aws_error(code: str, operation: str = "Converse") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": f"User: {SECRET} is not authorized"}}, operation)


def raising(e: Exception):
    def fn(*_):
        raise e
    return fn


class LoadErrorTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def test_throttling_tells_user_to_retry(self):
        result, err = load(raising(aws_error("ThrottlingException")))
        self.assertIsNone(result)
        self.assertIn("ThrottlingException", err)
        self.assertIn("다시 시도", err)
        self.assertNotIn("터미널", err)

    def test_access_denied_and_missing_profile_point_to_operator(self):
        for e, kind in [(aws_error("AccessDeniedException", "GetItem"), "AccessDeniedException"),
                        (ProfileNotFound(profile="kosa"), "ProfileNotFound")]:
            _, err = load(raising(e))
            self.assertIn(kind, err)
            self.assertIn("운영자", err)

    def test_message_with_account_id_is_never_shown(self):
        for code in ("ThrottlingException", "AccessDeniedException", "SomethingNew"):
            _, err = load(raising(aws_error(code)))
            self.assertNotIn("ACCOUNT-ID", err)
            self.assertNotIn("app-role", err)

    def test_unknown_errors_keep_the_old_message(self):
        _, err = load(raising(KeyError("x")))
        self.assertEqual(err, "불러오지 못했습니다(KeyError). 실행한 터미널의 로그를 확인하세요.")
        self.assertEqual(error_kind(aws_error("not a code; drop")), "ClientError")

    def test_not_implemented_is_still_pending(self):
        _, err = load(raising(NotImplementedError("준비 중")))
        self.assertIsInstance(err, Pending)


class RealModeScreenTest(unittest.TestCase):
    """BEDROCK_MOCK=0 분기를 가짜 boto3 로 실행한다. DynamoDB 가 권한 오류를 내도 화면은 뜨고 안내가 나온다."""

    def test_dynamodb_access_denied_shows_operator_hint(self):
        from backend import api

        table = mock.Mock()
        table.get_item.side_effect = aws_error("AccessDeniedException", "GetItem")
        resource = mock.Mock()
        resource.Table.return_value = table
        env = {"BEDROCK_MOCK": "0", "DYNAMODB_DEMAND_TABLE": "test-demand", "AWS_REGION": "ap-northeast-2"}
        api._demand_cache.clear()
        self.addCleanup(api._demand_cache.clear)
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        with mock.patch.dict(os.environ, env), mock.patch("backend.dynamodb._resource", return_value=resource):
            at = AppTest.from_file(MAIN, default_timeout=60).run()
        self.assertFalse(at.exception)
        shown = " ".join(str(x.value) for x in at.info)
        self.assertIn("불러오지 못했습니다(AccessDeniedException). 서버의 AWS 설정 문제입니다", shown)
        self.assertNotIn("ACCOUNT-ID", shown)
        table.get_item.assert_called_once()


if __name__ == "__main__":
    unittest.main()
