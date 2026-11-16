"""검색 방식 비교 스크립트 확인(가짜 모드). 실행: python -m pipeline.test_eval_search"""
import csv
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import eval_search as es


class EvalSearchTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"BEDROCK_MOCK": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_bm25_ranks_matching_document_first(self):
        bm25 = es.BM25({"a": "Amazon EC2 instance families", "b": "Amazon S3 storage classes", "c": "billing and budgets"})
        self.assertEqual(bm25.rank("EC2 instance")[0], "a")
        self.assertEqual(bm25.rank("없는낱말"), [])

    def test_rrf_prefers_items_ranked_high_in_both(self):
        self.assertEqual(es.rrf(["a", "b", "c"], ["b", "a", "d"])[:2], ["a", "b"])
        self.assertEqual(es.rrf(["a", "b"], ["b", "c"])[0], "b")

    def test_score_is_computed_by_code(self):
        ranked = {"q1": ["x", "a", "y"], "q2": ["z"], "q3": ["a"]}
        labels = {"q1": {"a", "b"}, "q2": {"k"}, "q3": set()}
        s = es.score(ranked, labels, k=3)
        self.assertEqual(s, {"queries": 2, "skipped": 1, "hit": 0.5, "recall": 0.25, "mrr": 0.25})

    def test_rank_all_covers_every_query_and_method(self):
        ranked = es.rank_all(5)
        self.assertEqual(set(ranked), set(es.METHODS))
        ids = {q["subskill_id"] for q in es.queries()}
        usable = {c["course_id"] for c in es.usable_courses()}
        for m in es.METHODS:
            self.assertEqual(set(ranked[m]), ids)
            self.assertTrue(all(len(v) <= 5 and set(v) <= usable for v in ranked[m].values()), m)

    def test_template_hides_method_and_labels_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(es, "OUT_DIR", Path(tmp)), \
                mock.patch.object(es, "POOL", Path(tmp) / "pool.csv"), mock.patch.object(es, "ROOT", Path(tmp)):
            self.assertEqual(es.main(["template", "--k", "3"]), 0)
            rows = list(csv.DictReader((Path(tmp) / "pool.csv").open(encoding="utf-8-sig")))
            self.assertEqual(set(rows[0]), set(es.POOL_COLUMNS))            # 어느 방식이 찾았는지는 양식에 없다
            with self.assertRaises(ValueError):                             # 빈 칸이 있으면 채점하지 않는다
                es.read_labels(Path(tmp) / "pool.csv")
            for i, r in enumerate(rows):
                r["relevant"] = "1" if i % 2 == 0 else "0"
            with (Path(tmp) / "pool.csv").open("w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=es.POOL_COLUMNS)
                w.writeheader()
                w.writerows(rows)
            labels = es.read_labels(Path(tmp) / "pool.csv")
            self.assertEqual(sum(len(v) for v in labels.values()), (len(rows) + 1) // 2)
            self.assertEqual(es.main(["run", "--k", "3", "--labels", str(Path(tmp) / "pool.csv")]), 0)

    def test_weak_labels_only_use_usable_certain_links(self):
        usable = {c["course_id"] for c in es.usable_courses()}
        labels = es.weak_labels()
        self.assertTrue(labels and all(v <= usable for v in labels.values()))


if __name__ == "__main__":
    unittest.main()
