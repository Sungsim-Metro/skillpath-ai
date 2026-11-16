"""추천 이유 채점 스크립트 확인(가짜 모드). 실행: python -m ai.test_judge"""
import csv
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import ai.eval.judge as judge


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.dict(os.environ, {"BEDROCK_MOCK": "1"}), mock.patch.object(judge, "OUT_DIR", Path(self.tmp.name))):
            p.start()
            self.addCleanup(p.stop)

    def run_cli(self, *argv):
        with redirect_stdout(io.StringIO()) as out, mock.patch.object(judge, "ROOT", Path(self.tmp.name).parent):
            code = judge.main(list(argv))
        return code, out.getvalue()

    def test_run_writes_result_and_blind_human_sheet(self):
        code, _ = self.run_cli("run", "--skills", "Docker", "Kubernetes", "--modes", "single", "--human", "4")
        self.assertEqual(code, 0)
        result = json.loads(next(Path(self.tmp.name).glob("judge_mock_*[0-9].json")).read_text(encoding="utf-8"))
        self.assertEqual(result["counts"], {"items": 6, "scored": 6})
        self.assertEqual(result["summary"]["single"]["n"], 6)
        self.assertEqual(result["mode"], "mock")
        sheet = next(Path(self.tmp.name).glob("*_human.csv"))
        rows = list(csv.DictReader(sheet.open(encoding="utf-8-sig")))
        self.assertEqual(len(rows), 4)
        self.assertEqual(set(rows[0]), set(judge.HUMAN_COLUMNS))          # 모드와 LLM 점수는 양식에 없다
        self.assertTrue(all(r[k] == "" for r in rows for k in judge.CRITERIA))
        self.assertEqual({r["item_id"] for r in rows}, set(result["human_item_ids"]))

    def test_agreement_is_computed_by_code(self):
        llm = {"a": {"grounded": 2, "relevant": 2, "clear": 1}, "b": {"grounded": 0, "relevant": 2, "clear": 2},
               "c": {"grounded": 2, "relevant": 1, "clear": 2}}
        human = {"a": {"grounded": 2, "relevant": 1, "clear": 1}, "b": {"grounded": 2, "relevant": 2, "clear": None}}
        table = judge.agreement(llm, human)
        self.assertEqual(table["grounded"], {"n": 2, "exact": 0.5, "within_1": 0.5, "mean_diff": -1.0})
        self.assertEqual(table["relevant"], {"n": 2, "exact": 0.5, "within_1": 1.0, "mean_diff": 0.5})
        self.assertEqual(table["clear"]["n"], 1)                          # 사람이 비운 칸은 세지 않는다

    def test_agree_command_and_bad_cell(self):
        self.run_cli("run", "--skills", "Docker", "--modes", "single", "--human", "3")
        result = next(Path(self.tmp.name).glob("judge_mock_*[0-9].json"))
        sheet = next(Path(self.tmp.name).glob("*_human.csv"))
        rows = list(csv.DictReader(sheet.open(encoding="utf-8-sig")))
        for r in rows:
            r.update(grounded="2", relevant="1", clear="2")
        with sheet.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=judge.HUMAN_COLUMNS)
            w.writeheader()
            w.writerows(rows)
        code, out = self.run_cli("agree", str(result), str(sheet))
        self.assertEqual(code, 0)
        self.assertIn("100%", out)
        rows[0]["grounded"] = "좋음"
        with sheet.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=judge.HUMAN_COLUMNS)
            w.writeheader()
            w.writerows(rows)
        with self.assertRaises(ValueError):
            judge.read_human_sheet(sheet)

    def test_validate_scores(self):
        ok = {"item_id": "a", "grounded": 2, "relevant": 1, "clear": 0, "note": None}
        judge.validate_scores({"scores": [ok]}, ["a"])
        for bad in ({**ok, "grounded": 3}, {**ok, "clear": "2"}, {**ok, "relevant": True}, {**ok, "item_id": "b"}):
            with self.assertRaises(ValueError, msg=bad):
                judge.validate_scores({"scores": [bad]}, ["a"])
        with self.assertRaises(ValueError):
            judge.validate_scores({"scores": []}, ["a"])

    def test_failed_judge_call_is_recorded_not_scored(self):
        """채점 응답이 두 번 다 형식 검사에서 떨어지면 그 항목은 점수 없이 남고 평균에 넣지 않는다."""
        code, _ = self.run_cli("run", "--skills", "Go", "Docker", "--modes", "single")
        result = json.loads(next(Path(self.tmp.name).glob("judge_mock_*[0-9].json")).read_text(encoding="utf-8"))
        go_items = [it for it in result["items"] if it["skill"] == "Go"]
        if go_items:  # Go 에 과정이 붙어 있을 때만 채점 호출이 일어난다
            self.assertEqual(code, 1)
            self.assertTrue(all("scores" not in it for it in go_items))
            self.assertEqual(result["errors"][0]["stage"], "judge")
        self.assertEqual(result["summary"]["single"]["n"], result["counts"]["scored"])

    def test_paired_change(self):
        def item(mode, total):
            return {"skill": "S", "title": "T", "mode": mode, "match": "certain",
                    "scores": {"grounded": total, "relevant": 0, "clear": 0}}
        self.assertEqual(judge.paired_change([item("single", 1), item("debate", 2)]),
                         {"pairs": 1, "higher": 1, "same": 0, "lower": 0})
        self.assertIsNone(judge.paired_change([item("single", 1)]))


if __name__ == "__main__":
    unittest.main()
