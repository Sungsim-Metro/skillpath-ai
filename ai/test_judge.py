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
        g = table["grounded"]
        self.assertEqual((g["n"], g["exact"], g["mean_diff"]), (2, 0.5, -1.0))
        self.assertNotIn("within_1", g)                                   # 점수가 셋뿐이라 뜻이 없는 숫자는 내지 않는다
        self.assertEqual(g["confusion"]["2"], {"0": 1, "1": 0, "2": 1})   # 사람이 2점 준 두 항목에 LLM 은 0점과 2점
        r = table["relevant"]
        self.assertEqual((r["human_low"], r["human_low_caught"]), (1, 0))  # 사람이 낮게 준 항목을 LLM 은 2점으로 놓쳤다
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
        self.assertIn("일치율 저장", out)
        saved = json.loads(next(Path(self.tmp.name).glob("*_agreement.json")).read_text(encoding="utf-8"))
        self.assertEqual((saved["human_items"], saved["agreement"]["grounded"]["exact"]), (3, 1.0))
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
        """채점 호출이 실패하면 그 항목은 점수 없이 남고, 평균에 넣지 않으며, 종료 코드가 1 이다."""
        from ai.bedrock import BedrockJSONError

        real = judge.judge

        def flaky(skill, items):
            if skill == "Docker":
                raise BedrockJSONError("가짜 실패")
            return real(skill, items)

        with mock.patch.object(judge, "judge", side_effect=flaky):
            code, _ = self.run_cli("run", "--skills", "Docker", "Kubernetes", "--modes", "single")
        result = json.loads(next(Path(self.tmp.name).glob("judge_mock_*[0-9].json")).read_text(encoding="utf-8"))
        self.assertEqual(code, 1)
        self.assertEqual(result["errors"][0]["stage"], "judge")
        docker = [it for it in result["items"] if it["skill"] == "Docker"]
        self.assertTrue(docker and all("scores" not in it for it in docker))
        self.assertEqual(result["counts"], {"items": 6, "scored": 3})
        self.assertEqual(result["summary"]["single"]["n"], 3)

    def test_unknown_skill_gives_clear_error(self):
        with self.assertRaises(SystemExit):
            self.run_cli("run", "--skills", "없는기술")

    def test_paired_change_separates_noise_from_effect(self):
        def item(title, mode, total, reason="같은 이유"):
            return {"skill": "S", "title": title, "mode": mode, "match": "certain", "reason": reason,
                    "scores": {"grounded": total, "relevant": 0, "clear": 0}}
        change = judge.paired_change([
            item("A", "single", 1), item("A", "debate", 2),                      # 글이 같은데 점수가 다르다: 잡음
            item("B", "single", 1), item("B", "debate", 2, reason="고친 이유"),   # 글이 바뀌었다: 효과
            item("C", "single", 2), item("C", "debate", 2),
        ])
        self.assertEqual((change["pairs"], change["noise"]), (3, 1))
        self.assertEqual(change["changed"], {"pairs": 1, "higher": 1, "same": 0, "lower": 0})
        self.assertEqual(change["identical"]["pairs"], 2)
        self.assertIsNone(judge.paired_change([item("A", "single", 1)]))

    def test_human_sample_always_includes_suspect_items(self):
        def item(i, low=False, review=None, match="certain", reason=None):
            return {"item_id": f"i{i}", "skill": "S", "title": f"T{i}", "reason": reason or f"이유 {i}", "match": match,
                    "review_status": review, "scores": {"grounded": 1 if low else 2, "relevant": 2, "clear": 2}}
        items = [item(i) for i in range(10)] + [item(10, low=True), item(11, review="revised"), item(12, match="uncertain")]
        items.append({**item(13), "title": "T0", "reason": "이유 0"})  # 0번과 글자까지 같다
        picked = {it["item_id"] for it in judge.pick_for_human(items, 5, seed=1)}
        self.assertTrue({"i10", "i11", "i12"} <= picked)
        self.assertEqual(len(picked), 5)
        self.assertEqual(len(judge.pick_for_human(items, 0, seed=1)), 13)  # 0 이면 서로 다른 이유 전부

    def test_rubric_in_doc_matches_prompt(self):
        doc = (Path(judge.__file__).parent / "JUDGE.md").read_text(encoding="utf-8")
        for key, name, two, one, zero in judge.judge_v1.RUBRIC:
            self.assertIn(f"| {name} (`{key}`) | {two} | {one} | {zero} |", doc)

    def test_human_sheet_is_read_strictly(self):
        def sheet(text, encoding="utf-8-sig"):
            p = Path(self.tmp.name) / "h.csv"
            p.write_bytes(("item_id,skill,grounded,relevant,clear,memo\n" + text).encode(encoding))
            return p
        self.assertEqual(judge.read_human_sheet(sheet("a,도커,2.0,1,,메모\n,,,,,\n", "cp949")),
                         {"a": {"grounded": 2, "relevant": 1, "clear": None}})
        with self.assertRaises(ValueError):
            judge.read_human_sheet(sheet("a,S,2,1,0,\na,S,0,0,0,\n"))  # 같은 항목이 두 번
        with self.assertRaises(ValueError):
            judge.read_human_sheet(sheet(",S,2,1,0,\n"))                # 번호가 지워진 줄

    def test_any_failure_is_recorded(self):
        """호출 제한 같은 오류도 실행 전체를 멈추지 않고 errors 에 남는다."""
        with mock.patch.object(judge, "judge", side_effect=RuntimeError("ThrottlingException")):
            code, _ = self.run_cli("run", "--skills", "Docker", "--modes", "single")
        result = json.loads(next(Path(self.tmp.name).glob("judge_mock_*[0-9].json")).read_text(encoding="utf-8"))
        self.assertEqual((code, result["errors"][0]["stage"]), (1, "judge"))
        self.assertIn("ThrottlingException", result["errors"][0]["error"])


if __name__ == "__main__":
    unittest.main()
