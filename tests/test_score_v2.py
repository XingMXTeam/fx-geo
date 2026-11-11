"""geo-optimizer 4.19 rubric v2: maxima, series split, and the panel contract."""
import json
import re
import sqlite3
import subprocess
import unittest
from pathlib import Path

import rubric
import seed
import weekly_report
from db import SCHEMA, ensure_audit_score_version

ROOT = Path(__file__).resolve().parents[1]


class RubricTests(unittest.TestCase):
    def test_default_version_and_category_maxima(self):
        self.assertEqual(rubric.DEFAULT_SCORE_VERSION, 2)
        self.assertEqual(rubric.CATEGORY_MAX_V2, {
            "google_ai": 20,
            "robots": 14,
            "schema": 14,
            "content": 14,
            "brand_entity": 12,
            "meta": 11,
            "llms": 6,
            "signals": 6,
            "ai_discovery": 3,
        })
        self.assertEqual(sum(rubric.CATEGORY_MAX_V2.values()), 100)
        self.assertEqual(sum(rubric.CATEGORY_MAX_V1.values()), 100)
        self.assertNotIn("google_ai", rubric.CATEGORY_MAX_V1)
        self.assertEqual(list(rubric.CATEGORY_MAX_V2), rubric.CATEGORY_ORDER_V2)

    def test_signal_weights_sum_to_the_category_max(self):
        self.assertEqual(sum(rubric.SCORING_V1.values()), 100)
        self.assertEqual(
            sum(rubric.SCORING_V2.values()) + sum(rubric.GOOGLE_AI_POINTS.values()),
            100,
        )
        self.assertNotIn("G-SD-VISIBLE", rubric.GOOGLE_AI_POINTS)
        self.assertEqual(sum(rubric.GOOGLE_AI_POINTS.values()), 20)
        self.assertEqual(rubric.SCORING_V2["llms_depth"], 0)
        self.assertEqual(rubric.SCORING_V2["llms_depth_high"], 0)
        self.assertEqual(rubric.SCORING_V2["ai_discovery_faq"], 0)
        self.assertEqual(rubric.SCORING_V2["ai_discovery_service"], 0)
        self.assertEqual(rubric.SCORING_V2["ai_discovery_markdown"], 1)
        self.assertEqual(rubric.ROBOTS_PARTIAL_SCORE_V2, 8)
        for key, parts in rubric.CATEGORY_SIGNAL_PARTS_V2.items():
            shown = sum(points for _name, points in parts)
            self.assertEqual(shown, rubric.CATEGORY_MAX_V2[key], key)
            self.assertEqual(rubric.CATEGORY_SIGNAL_LINES_V2[key], rubric._line(parts))
        self.assertNotIn("partial", rubric.CATEGORY_SIGNAL_LINES_V2["robots"])
        self.assertIn("visible name match 2", rubric.CATEGORY_SIGNAL_LINES_V2["schema"])
        self.assertIn("markdown negotiation 1", rubric.CATEGORY_SIGNAL_LINES_V2["ai_discovery"])
        self.assertIn("depth 0", rubric.CATEGORY_SIGNAL_LINES_V2["llms"])

    def test_live_check_max_is_v2_and_history_stays_v1(self):
        self.assertEqual(rubric.CHECK_MAX["google_ai"], 20)
        self.assertEqual(rubric.CHECK_MAX["llms_txt"], 6)
        self.assertEqual(rubric.CHECK_MAX["ai_discovery"], 3)
        historical = rubric.check_max(1)
        self.assertEqual(historical["llms_txt"], 18)
        self.assertEqual(historical["robots_txt"], 18)
        self.assertNotIn("google_ai", historical)
        self.assertEqual(seed.HISTORICAL_AUDIT_SCORE_VERSION, 1)
        self.assertEqual(seed.CHECK_MAX["meta_tags"], 11)
        self.assertEqual(seed.CHECK_MAX["content"], 14)

    def test_stored_max_is_not_rewritten_onto_the_other_scale(self):
        raw = {"llms": {"score": 10, "max": 18}, "robots": 15}
        kept = rubric.normalize_breakdown(raw, 2)
        self.assertEqual(kept["llms"], {"score": 10, "max": 18})
        self.assertEqual(kept["robots"], {"score": 15, "max": 14})
        legacy = rubric.normalize_breakdown({"llms": 10, "google_ai": 20}, 1)
        self.assertEqual(legacy["llms"], {"score": 10, "max": 18})
        self.assertNotIn("google_ai", legacy)
        flat_v2 = rubric.normalize_breakdown({"google_ai": 0, "ai_discovery": 1}, 2)
        self.assertEqual(flat_v2["google_ai"]["max"], 20)
        self.assertEqual(flat_v2["ai_discovery"]["max"], 3)

    def test_series_do_not_mix(self):
        rows = [
            {"score": 62, "score_version": 1, "domain": "maoxunxing.com"},
            {"score": 65},
            {"score": 40, "score_version": 2, "domain": "maoxunxing.com"},
        ]
        v1 = rubric.split_series(rows, 1)
        v2 = rubric.split_series(rows, 2)
        self.assertEqual([row["score"] for row in v1], [62, 65])
        self.assertEqual([row["score"] for row in v2], [40])
        self.assertIsNone(rubric.current_v2(rows[:2]))
        self.assertEqual(rubric.current_v2(rows)["score"], 40)
        self.assertEqual(rubric.parse_score_version(None), 1)
        self.assertEqual(rubric.parse_score_version("v2"), 2)


class StorageTests(unittest.TestCase):
    def test_new_schema_defaults_missing_version_to_v1(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO sites(domain, name) VALUES('maoxunxing.com', '主站')")
        conn.execute("INSERT INTO audits(site_id, score) VALUES(1, 62)")
        version = conn.execute("SELECT score_version FROM audits").fetchone()[0]
        self.assertEqual(version, 1)

    def test_legacy_table_gains_v1_without_changing_the_score(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE audits (id INTEGER PRIMARY KEY, site_id INTEGER, score INTEGER)"
        )
        conn.execute("INSERT INTO audits(site_id, score) VALUES(1, 62)")
        self.assertEqual(ensure_audit_score_version(conn), ["audits.+score_version"])
        self.assertEqual(ensure_audit_score_version(conn), [])
        row = conn.execute("SELECT score, score_version FROM audits").fetchone()
        self.assertEqual(row, (62, 1))


class ReportTests(unittest.TestCase):
    def _sites(self):
        return [
            {"domain": "maoxunxing.com", "role": "主站", "name": "毛毛星（主站）"},
            {"domain": "crossagent.maoxunxing.com", "role": "垂直产品站", "name": "CrossAgent Lab"},
        ]

    def test_v1_history_is_labeled_and_v2_is_empty(self):
        grouped = {
            "maoxunxing.com": {
                1: {"score": 62, "score_version": 1, "run_at": "2026-11-01T16:13:15+00:00"},
            },
            "crossagent.maoxunxing.com": {
                1: {"score": 65, "score_version": 1, "run_at": "2026-11-01T16:13:33+00:00"},
            },
        }
        detail = weekly_report.audit_detail_text(self._sites(), grouped)
        score = weekly_report.audit_score_text(self._sites(), grouped)
        asof = weekly_report.audit_asof_text(self._sites(), grouped)
        self.assertIn("score_version=v1", detail)
        self.assertIn("62", detail)
        self.assertIn("65", detail)
        self.assertIn("score_version=v2：尚无采样", detail)
        self.assertIn("score_version=v2 尚无采样", score)
        self.assertIn("2026-11-02", asof)
        self.assertNotIn("→", detail)
        self.assertNotIn("67", detail)
        self.assertNotIn("差额", detail)

    def test_both_versions_are_stated_separately(self):
        grouped = {
            "maoxunxing.com": {
                1: {"score": 62, "score_version": 1, "run_at": "2026-11-01T16:13:15+00:00"},
                2: {"score": 40, "score_version": 2, "run_at": "2026-11-11T01:00:00+00:00"},
            },
            "crossagent.maoxunxing.com": {},
        }
        detail = weekly_report.audit_detail_text(self._sites(), grouped)
        self.assertIn("score_version=v1：", detail)
        self.assertIn("score_version=v2：", detail)
        self.assertLess(detail.index("score_version=v1"), detail.index("score_version=v2"))
        self.assertNotIn("62-40", detail)
        self.assertNotIn("较", detail)


class PanelContractTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "panel.html").read_text(encoding="utf-8")

    def test_embedded_rubric_matches_upstream_table(self):
        match = re.search(
            r'<script type="application/json" id="fx-score-rubric">\s*(.*?)\s*</script>',
            self.html,
            re.S,
        )
        self.assertIsNotNone(match)
        embedded = json.loads(match.group(1))
        self.assertEqual(embedded, rubric.panel_rubric())
        self.assertEqual(embedded["default_score_version"], 2)
        self.assertEqual(embedded["v2"]["max"]["google_ai"], 20)
        self.assertNotIn("google_ai", embedded["v1"]["max"])

    def test_panel_keeps_the_series_apart(self):
        self.assertIn("score_version=v2", self.html)
        self.assertIn("score_version=v1", self.html)
        self.assertIn("v1 历史不画在这张图上。", self.html)
        self.assertIn("卫生分不是 AI 引用率、提及率或发现率。", self.html)
        self.assertIn("v1 无此分类", self.html)
        self.assertNotIn("const BD_MAX", self.html)
        self.assertIn("a.score_version === version", self.html)
        self.assertNotIn("发现率：", self.html)
        self.assertNotIn("discovery rate", self.html.lower())

    def test_seed_sql_keeps_historical_v1_scores(self):
        sql = (ROOT / "supabase" / "seed.sql").read_text(encoding="utf-8")
        self.assertIn("62, 1, 'foundation'", sql)
        self.assertIn("65, 1, 'foundation'", sql)
        self.assertIn('"llms": {"score": 10, "max": 18}', sql)
        self.assertIn('"ai_discovery": {"score": 0, "max": 6}', sql)
        self.assertNotIn('"google_ai"', sql)
        self.assertIn("score_version=v1，两站均 10/18", sql)
        self.assertIn("score_version=v1，当前 15/18", sql)

    def test_scripts_parse(self):
        scripts = re.findall(r"<script>(.*?)</script>", self.html, re.S)
        self.assertGreaterEqual(len(scripts), 2)
        for index, script in enumerate(scripts):
            path = ROOT / "tests" / f"_panel_{index}.js"
            path.write_text(script, encoding="utf-8")
            try:
                subprocess.run(
                    ["node", "--check", str(path)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            finally:
                path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
