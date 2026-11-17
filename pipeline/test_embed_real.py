"""Titan 임베딩의 실제 모드(BEDROCK_MOCK=0) 분기를 가짜 bedrock-runtime 으로 실행한다.

실행: 저장소 루트에서 `python -m pipeline.test_embed_real`
"""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from botocore.exceptions import ClientError

from pipeline import embed


class FakeRuntime:
    """invoke_model 응답 형태를 흉내 낸다: body 는 읽을 수 있는 스트림, 안에 embedding 과 inputTextTokenCount."""

    def __init__(self, fail_at=None):
        self.requests = []
        self.fail_at = fail_at

    def invoke_model(self, **kwargs):
        self.requests.append(kwargs)
        if self.fail_at is not None and len(self.requests) >= self.fail_at:
            raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "Too many requests"}}, "InvokeModel")
        text = json.loads(kwargs["body"])["inputText"]
        payload = {"embedding": [3.0, 4.0, float(len(text))], "inputTextTokenCount": 2}
        return {"body": io.BytesIO(json.dumps(payload).encode("utf-8")), "contentType": "application/json"}


class EmbedRealModeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name) / "raw" / "embed_cache.json"
        embed._setup()  # .env 를 먼저 읽게 해 아래에서 덮어쓴 값이 바뀌지 않게 한다
        for patcher in (
            mock.patch.dict(os.environ, {"BEDROCK_MOCK": "0", "EMBED_MODEL_ID": "amazon.titan-embed-text-v2:0"}),
            mock.patch.object(embed, "CACHE_FILE", self.cache),
            mock.patch.dict(embed._usage, {"calls": 0, "tokens": 0}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def use(self, runtime):
        patcher = mock.patch.object(embed, "_client", return_value=runtime)
        patcher.start()
        self.addCleanup(patcher.stop)
        return runtime

    def test_calls_titan_once_per_new_sentence_and_caches(self):
        runtime = self.use(FakeRuntime())
        first = embed.embed_many(["Docker", "Kubernetes", "Docker"])
        self.assertEqual(len(runtime.requests), 2)
        self.assertEqual(json.loads(runtime.requests[0]["body"]), {"inputText": "Docker", "normalize": True})
        self.assertEqual(runtime.requests[0]["modelId"], "amazon.titan-embed-text-v2:0")
        for vector in first:
            self.assertAlmostEqual(sum(x * x for x in vector), 1.0, places=4)
        self.assertEqual(embed.usage(), {"calls": 2, "tokens": 4})
        self.assertEqual(embed.embed_many(["Kubernetes", "Docker"]), [first[1], first[0]])
        self.assertEqual(len(runtime.requests), 2)  # 캐시 파일에서 읽어 다시 부르지 않는다

    def test_g1_text_model_gets_input_text_only(self):
        runtime = self.use(FakeRuntime())
        with mock.patch.dict(os.environ, {"EMBED_MODEL_ID": "amazon.titan-embed-text-v1"}):
            embed.embed("Docker")
        self.assertEqual(json.loads(runtime.requests[0]["body"]), {"inputText": "Docker"})

    def test_vectors_received_before_a_failure_are_kept(self):
        runtime = self.use(FakeRuntime(fail_at=3))
        with self.assertRaises(ClientError):
            embed.embed_many(["a", "b", "c", "d"])
        self.assertEqual(len(json.loads(self.cache.read_text(encoding="utf-8"))), 2)
        runtime.fail_at = None
        embed.embed_many(["a", "b", "c", "d"])
        self.assertEqual(len(runtime.requests), 5)  # 실패 전 2 + 실패 1 + 다시 돌릴 때 남은 2

    def test_missing_model_id_fails_before_calling_aws(self):
        runtime = self.use(FakeRuntime())
        with mock.patch.dict(os.environ, {"EMBED_MODEL_ID": ""}):
            with self.assertRaises(RuntimeError):
                embed.embed("Docker")
        self.assertEqual(runtime.requests, [])


if __name__ == "__main__":
    unittest.main()
