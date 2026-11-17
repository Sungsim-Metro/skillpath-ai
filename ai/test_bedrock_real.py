"""converse_json 의 실제 모드(BEDROCK_MOCK=0) 분기를 가짜 bedrock-runtime 으로 실행한다.

실제 Converse 응답 형태(output.message.content, stopReason, usage)를 흉내 낸다.
실행: 저장소 루트에서 `python -m ai.test_bedrock_real`
"""
import json
import logging
import os
import tempfile
import unittest
from unittest import mock

from botocore.exceptions import ClientError

from ai import bedrock


def response(text, stop="end_turn", tokens=(100, 20), extra_blocks=()):
    return {
        "ResponseMetadata": {"HTTPStatusCode": 200},
        "output": {"message": {"role": "assistant", "content": [*extra_blocks, {"text": text}]}},
        "stopReason": stop,
        "usage": {"inputTokens": tokens[0], "outputTokens": tokens[1], "totalTokens": sum(tokens)},
        "metrics": {"latencyMs": 900},
    }


class FakeRuntime:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def converse(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs)))  # 호출 시점의 값을 남긴다
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def need_ok(data):
    if data.get("ok") is not True:
        raise ValueError('"ok" 가 true 가 아닙니다')


class ConverseRealModeTest(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = mock.patch.dict(os.environ, {
            "BEDROCK_MOCK": "0", "BEDROCK_MODEL_ID": "test.model-v1:0",
            "USAGE_LOG": os.path.join(tmp.name, "usage.jsonl"),  # 호출 기록을 남기는 코드가 있어도 테스트 호출이 섞이지 않게
        })
        env.start()
        self.addCleanup(env.stop)

    def run_with(self, *replies, **kwargs):
        runtime = FakeRuntime(*replies)
        with mock.patch.object(bedrock, "_client", return_value=runtime):
            try:
                return runtime, bedrock.converse_json("시스템", "질문", mock_file="x.json", mock_key="k", **kwargs)
            except Exception as e:  # noqa: BLE001 - 호출 기록과 함께 돌려줘 아래에서 검사한다
                return runtime, e

    def test_request_shape_and_usage(self):
        runtime, result = self.run_with(response('```json\n{"ok": true}\n```'), validate=need_ok, max_tokens=512)
        self.assertEqual(result.data, {"ok": True})
        self.assertEqual((result.attempts, result.usage), (1, {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120}))
        self.assertEqual(runtime.requests[0], {
            "modelId": "test.model-v1:0",
            "system": [{"text": "시스템"}],
            "messages": [{"role": "user", "content": [{"text": "질문"}]}],
            "inferenceConfig": {"maxTokens": 512, "temperature": 0.0},
        })

    def test_non_text_blocks_are_skipped(self):
        thinking = {"reasoningContent": {"reasoningText": {"text": "생각"}}}
        _, result = self.run_with(response('{"ok": true}', extra_blocks=(thinking,)))
        self.assertEqual(result.data, {"ok": True})

    def test_bad_json_is_retried_once_with_the_previous_answer(self):
        runtime, result = self.run_with(response("죄송합니다", tokens=(100, 5)), response('{"ok": true}', tokens=(130, 6)),
                                        validate=need_ok)
        self.assertEqual((result.attempts, result.usage["totalTokens"]), (2, 241))
        roles = [m["role"] for m in runtime.requests[1]["messages"]]
        self.assertEqual(roles, ["user", "assistant", "user"])  # Converse 는 역할이 번갈아 와야 한다
        self.assertEqual(runtime.requests[1]["messages"][1]["content"], [{"text": "죄송합니다"}])

    def test_empty_answer_is_retried_with_a_placeholder(self):
        runtime, result = self.run_with(response("", stop="max_tokens"), response('{"ok": true}'))
        self.assertEqual(result.attempts, 2)
        self.assertTrue(runtime.requests[1]["messages"][1]["content"][0]["text"])  # 빈 text 블록은 Converse 가 거부한다

    def test_two_failures_raise_with_spent_tokens(self):
        runtime, error = self.run_with(response("{}"), response('{"ok": false}'), validate=need_ok)
        self.assertIsInstance(error, bedrock.BedrockJSONError)
        self.assertEqual(error.usage["totalTokens"], 240)
        self.assertEqual(len(runtime.requests), 2)

    def test_aws_errors_pass_through_without_retry(self):
        throttled = ClientError({"Error": {"Code": "ThrottlingException", "Message": "Too many requests"}}, "Converse")
        runtime, error = self.run_with(throttled)
        self.assertIs(error, throttled)
        self.assertEqual(len(runtime.requests), 1)  # 재시도는 boto3 가 한다. 여기서 한 번 더 부르지 않는다

    def test_missing_model_id_fails_before_calling_aws(self):
        with mock.patch.dict(os.environ, {"BEDROCK_MODEL_ID": ""}):
            runtime, error = self.run_with(response('{"ok": true}'))
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(runtime.requests, [])


if __name__ == "__main__":
    unittest.main()
