"""사전 점검 스크립트를 가짜 boto3 로 실행한다(BEDROCK_MOCK=0 분기).

실행: 저장소 루트에서 `python -m deploy.test_check_aws`
"""
import logging
import os
import tempfile
import unittest
from decimal import Decimal
from unittest import mock

from botocore.exceptions import ClientError

from ai import bedrock
from backend import api
from deploy import check_aws

SNAPSHOT = {"job_category": "cloud_engineer", "demand": {
    "job_category": "cloud_engineer", "job_title": "클라우드 엔지니어", "total_postings": Decimal(4),
    "sources": ["rocketpunch"], "collected": "2026-11-15",
    "skills": [{"skill": "Docker", "postings": Decimal(3), "required": Decimal(2), "preferred": Decimal(1),
                "evidence_samples": [{"posting_id": "rp-1", "url": "https://example.com/1", "evidence": "Docker 운영 경험"}]}],
}}


def converse_ok(**_):
    return {"output": {"message": {"role": "assistant", "content": [{"text": '{"ok": true}'}]}},
            "stopReason": "end_turn", "usage": {"inputTokens": 30, "outputTokens": 6, "totalTokens": 36}}


def aws_error(code, operation):
    return ClientError({"Error": {"Code": code, "Message": "arn:aws:iam::ACCOUNT-ID:role/secret-role"}}, operation)


class CheckAwsTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env = {"BEDROCK_MOCK": "0", "BEDROCK_MODEL_ID": "test.model-v1:0", "DYNAMODB_DEMAND_TABLE": "test-demand",
                    "USAGE_LOG": os.path.join(tmp.name, "usage.jsonl")}
        self.table = mock.Mock()
        self.table.get_item.return_value = {"Item": SNAPSHOT}
        self.runtime = mock.Mock()
        self.runtime.converse.side_effect = converse_ok
        resource = mock.Mock()
        resource.Table.return_value = self.table
        for patcher in (mock.patch("backend.dynamodb._resource", return_value=resource),
                        mock.patch.object(bedrock, "_client", return_value=self.runtime)):
            patcher.start()
            self.addCleanup(patcher.stop)
        api._demand_cache.clear()
        self.addCleanup(api._demand_cache.clear)
        self.lines = []

    def run_check(self, env=None, **kwargs):
        with mock.patch.dict(os.environ, self.env if env is None else env, clear=True):
            return check_aws.run(out=self.lines.append, **kwargs)

    def test_all_steps_pass_with_one_call_each(self):
        self.assertEqual(self.run_check(), 0)
        self.assertEqual([line[:4] for line in self.lines[:3]], ["[통과]"] * 3)
        self.assertIn("공고 4건, 기술 1개", self.lines[1])
        self.assertEqual((self.table.get_item.call_count, self.runtime.converse.call_count), (1, 1))

    def test_mock_mode_or_missing_env_stops_before_aws(self):
        for env in ({**self.env, "BEDROCK_MOCK": "1"}, {"BEDROCK_MOCK": "0"}):
            self.lines.clear()
            self.assertEqual(self.run_check(env), 1)
            self.assertTrue(self.lines[0].startswith("[실패] 환경 변수"))
        self.table.get_item.assert_not_called()
        self.runtime.converse.assert_not_called()

    def test_aws_errors_show_code_only(self):
        self.table.get_item.side_effect = aws_error("AccessDeniedException", "GetItem")
        self.runtime.converse.side_effect = aws_error("ThrottlingException", "Converse")
        self.assertEqual(self.run_check(), 1)
        self.assertEqual(self.lines[1], "[실패] DynamoDB 수요 집계: AccessDeniedException")
        self.assertEqual(self.lines[2], "[실패] Bedrock 호출: ThrottlingException")
        self.assertNotIn("secret-role", " ".join(self.lines))

    def test_missing_snapshot_is_reported(self):
        self.table.get_item.return_value = {}
        self.assertEqual(self.run_check(), 1)
        self.assertIn("완성된 직무 수요 집계가 없습니다", self.lines[1])

    def test_recommend_step_calls_bedrock_for_one_skill(self):
        api._recommend_cache.clear()
        self.addCleanup(api._recommend_cache.clear)

        def converse(**kwargs):
            user = kwargs["messages"][0]["content"][0]["text"]
            if "<input>" not in user:
                return converse_ok()
            import json

            data = json.loads(user[user.index("<input>") + 7: user.index("</input>")])
            reasons = [{"course_id": c["course_id"], "reason": "이 과정은 필요한 내용을 다룹니다."} for c in data["courses"]]
            return {"output": {"message": {"role": "assistant", "content": [{"text": json.dumps({"reasons": reasons})}]}},
                    "stopReason": "end_turn", "usage": {"inputTokens": 900, "outputTokens": 120, "totalTokens": 1020}}

        self.runtime.converse.side_effect = converse
        self.assertEqual(self.run_check(recommend=True), 0)
        self.assertIn("[통과] 추천 1건: Docker: 과정 ", self.lines[3])
        self.assertEqual(self.runtime.converse.call_count, 2)


if __name__ == "__main__":
    unittest.main()
