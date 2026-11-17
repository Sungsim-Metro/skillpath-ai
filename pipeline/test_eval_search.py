"""검색 방식 비교 스크립트 확인(가짜 모드). 실행: python -m unittest pipeline.test_eval_search"""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import eval_search as es


def _write(rows: list[tuple[str, str, str]], encoding: str = "utf-8-sig") -> Path:
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding=encoding, newline="")
    f.write("skill,course_id,title,level,objectives,relevant\n")
    for skill, cid, cell in rows:
        f.write(f"{skill},{cid},제목,기초,목표,{cell}\n")
    f.close()
    return Path(f.name)


class EvalSearchTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"BEDROCK_MOCK": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ids = sorted(c["course_id"] for c in es.usable_courses())

    def test_bm25_ranks_matching_document_first(self):
        bm25 = es.BM25({"a": "Amazon EC2 instance families", "b": "Amazon S3 storage classes", "c": "billing and budgets"})
        self.assertEqual(bm25.rank("EC2 instance")[0], "a")
        self.assertEqual(bm25.rank("없는낱말"), [])

    def test_tokens_drop_trailing_punctuation(self):
        self.assertEqual(es.tokens("Launch Amazon EC2. Use CI/CD and C++."), ["launch", "amazon", "ec2", "use", "ci", "cd", "and", "c++"])

    def test_rrf_prefers_items_ranked_high_in_both(self):
        self.assertEqual(es.rrf(["a", "b", "c"], ["b", "a", "d"])[:2], ["a", "b"])
        self.assertEqual(es.rrf(["a", "b"], ["b", "c"])[0], "b")

    def test_score_counts(self):
        ranked = {"q1": ["x", "a", "y"], "q2": ["z"], "q3": ["a"], "q4": [], "q5": ["a"]}
        labels = {"q1": {"a", "b"}, "q2": {"k"}, "q3": set(), "q4": set()}  # q5 는 판정이 없어 세지 않는다
        s = es.score(ranked, labels, k=3)
        self.assertEqual((s["answerable"], s["hit"]), (2, 1))
        self.assertEqual((s["shown"], s["shown_relevant"]), (5, 1))
        self.assertEqual((s["empty"], s["wrongly_filled"]), (2, 1))
        self.assertEqual(s["hit_skills"], ["q1"])
        self.assertEqual(es.score(ranked, labels, k=1)["hit"], 0)

    def test_pairwise_lists_skills_only_one_method_hit(self):
        table = {"keyword": {"hit_skills": ["A", "B"]}, "embedding": {"hit_skills": ["B", "C"]}, "baseline": {"hit_skills": ["A"]}}
        self.assertEqual(es.pairwise(table), [{"a": "keyword", "b": "embedding", "only_a": ["A"], "only_b": ["C"]}])

    def test_every_method_gets_the_same_query_and_k(self):
        skills = es.service_skills()
        ranked = es.rank_all(skills, k=es.DEFAULT_K)
        self.assertEqual(set(ranked), {"keyword", es.BASELINE})  # 가짜 모드에서는 임베딩·혼합을 계산하지 않는다
        for m in ranked:
            self.assertEqual(list(ranked[m]), skills)
            self.assertTrue(all(len(v) <= es.DEFAULT_K for v in ranked[m].values()))

    def test_baseline_is_not_a_compared_method(self):
        self.assertNotIn(es.BASELINE, es.COMPARED)

    def test_read_labels_keeps_skills_judged_all_zero(self):
        a, b = self.ids[:2]
        labels = es.read_labels(_write([("Docker", a, "1"), ("Docker", b, "0"), ("Linux", a, "0"), ("Linux", b, "0.0")]))
        self.assertEqual(labels, {"Docker": {a}, "Linux": set()})

    def test_read_labels_reads_korean_excel_csv(self):
        a = self.ids[0]
        self.assertEqual(es.read_labels(_write([("정보보안", a, "1")], encoding="cp949")), {"정보보안": {a}})

    def test_read_labels_rejects_sloppy_sheets(self):
        a, b = self.ids[:2]
        for rows in ([("Docker", a, "")], [("Docker", a, "y")], [("Docker", "NOPE", "1")], [("Docker", a, "1"), ("Docker", a, "0")]):
            with self.assertRaises(ValueError):
                es.read_labels(_write(rows))
        with self.assertRaises(ValueError):  # 다른 k 나 다른 모드로 만든 양식
            es.read_labels(_write([("Docker", a, "1")]), expected={("Docker", a), ("Docker", b)})

    def test_run_refuses_without_labels(self):
        with self.assertRaises(SystemExit):
            es.main(["run"])

    def test_template_refuses_in_mock_mode(self):
        with self.assertRaises(SystemExit):
            es.main(["template"])

    def test_template_then_run_round_trip(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(es, "OUT_DIR", Path(d)), \
                mock.patch.object(es, "POOL", Path(d) / "search_pool.csv"), \
                mock.patch.object(es, "ROOT", Path(d)), contextlib.redirect_stdout(io.StringIO()) as out:
            es.main(["template", "--allow-mock", "--skills", "Docker", "Linux"])
            pool = Path(d) / "search_pool.csv"
            text = pool.read_text(encoding="utf-8-sig")
            self.assertTrue(text.splitlines()[0].endswith("relevant"))
            with self.assertRaises(ValueError):  # 빈 양식은 채점하지 않는다
                es.main(["run", "--labels", str(pool), "--skills", "Docker", "Linux"])
            pool.write_text("\n".join([text.splitlines()[0]] + [line + "0" for line in text.splitlines()[1:]]) + "\n", encoding="utf-8-sig")
            self.assertEqual(es.main(["run", "--labels", str(pool), "--skills", "Docker", "Linux"]), 0)
            self.assertIn("기준선", out.getvalue())

    def test_weak_run_leaves_out_the_baseline(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(es, "OUT_DIR", Path(d)), \
                mock.patch.object(es, "ROOT", Path(d)), contextlib.redirect_stdout(io.StringIO()) as out:
            es.main(["run", "--weak"])
            self.assertNotIn("기준선(지금 서비스)", out.getvalue().split("주의")[0])


if __name__ == "__main__":
    unittest.main()
