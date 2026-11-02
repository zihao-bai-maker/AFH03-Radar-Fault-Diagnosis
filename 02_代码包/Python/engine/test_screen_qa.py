#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_screen_qa.py —— 屏幕状态问答（15 项）单元测试。

运行：
    python test_screen_qa.py -v
    python -m unittest test_screen_qa -v

覆盖：
* 题库：15 项 / SQ001..SQ015 / 与 vision_bindings 的 field-part-route 对齐
* 选项来源：判据库精确命中 / 同名值复用 / vision_rules 取值域 / 口述词 / 跳过
* 证据：evidence/v1 八字段、modality=qa、value 映射、feature_id、confidence=1.0
* 冲突：一致 / 不一致（问答优先）/ 不可比 / 未知 / 跳过 / 字段不匹配
* 辅助：答案别名、summary/evidence 批量、steps_screen_patch、screen_hint 降级
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import screen_qa as SQ  
import screen_hint as SH  

ITEMS = HERE / "qa_items_screen.json"
PATCH = HERE / "steps_screen_patch.json"
BINDINGS = HERE / "vision_bindings.json"
STEPS = HERE / "steps.json"
FAULT = HERE.parent / "判据库_故障.csv"

TASK_KEYS = ["part", "route", "modality", "field", "value", "confidence", "note"]
CONTRACT_KEYS = TASK_KEYS + ["evidence", "ts"]
TS_RE = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$"

def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def assert_contract(test, e):
    test.assertEqual(list(e.keys())[:7], TASK_KEYS)
    for k in CONTRACT_KEYS:
        test.assertIn(k, e)
    test.assertTrue(e["evidence"], "evidence 不能为空")
    test.assertRegex(e["ts"], TS_RE)
    test.assertEqual(e["modality"], "qa")
    test.assertIn(e["route"], ("", "I", "II"))
    test.assertTrue(e["field"])
    test.assertGreaterEqual(float(e["confidence"]), 0.0)
    test.assertLessEqual(float(e["confidence"]), 1.0)
    test.assertEqual(e["decided_by"], "qa")
    test.assertEqual(e["value_source"], "qa")
    test.assertIs(e["vision_reliable"], False)

class TestCatalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = SQ.load_items(ITEMS)
        cls.items = {it["qa_id"]: it for it in cls.data["items"]}
        cls.bindings = [b for b in load(BINDINGS)["items"] if b.get("binding") == "screen"]

    def test_count_and_ids(self):
        self.assertEqual(len(self.data["items"]), 15)
        self.assertEqual([it["qa_id"] for it in self.data["items"]],
                         ["SQ%03d" % i for i in range(1, 16)])

    def test_matches_vision_bindings(self):
        keys = {it["screen_key"] for it in self.data["items"]}
        self.assertEqual(keys, {b["key"] for b in self.bindings})
        by_key = {b["key"]: b for b in self.bindings}
        for it in self.data["items"]:
            b = by_key[it["screen_key"]]
            self.assertEqual(it["part"], b["part"])
            self.assertEqual(it["route"], b["route"])
            self.assertEqual(it["evidence_field"], b["field"])
            self.assertEqual(it["binding_ref"], b["binding_ref"])

    def test_questions_and_normal(self):
        for it in self.data["items"]:
            self.assertIn("现在屏幕", it["question"])
            self.assertTrue(it["normal"])
            self.assertIn(it["screen_kind"], ("screen", "line", "scan", "noise", "echo"))

    def test_options_have_normal_and_skip(self):
        for it in self.data["items"]:
            values = [o["value"] for o in it["options"]]
            self.assertEqual(values.count("normal"), 1, it["qa_id"])
            self.assertEqual(values.count("skipped"), 1, it["qa_id"])
            for o in it["options"]:
                self.assertIn(o["origin"], self.data["option_origin_legend"])
                if o["abnormal"]:
                    self.assertTrue(o["feature_id"], "%s/%s 缺 feature_id" % (it["qa_id"], o["value"]))
                else:
                    self.assertIsNone(o["feature_id"])

    def test_build_is_reproducible(self):
        rebuilt = SQ.build_items()
        self.assertEqual(rebuilt, self.data)

    def test_screen_item_count_is_15(self):
        self.assertEqual(len(self.bindings), 15)

        all_bindings = load(BINDINGS)["items"]
        self.assertEqual(sum(1 for b in all_bindings if b.get("binding") == "dynamic"), 4)

class TestProvenance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = {it["qa_id"]: it for it in SQ.load_items(ITEMS)["items"]}

    @staticmethod
    def opt(qa_id, value):
        return next(o for o in TestProvenance.items[qa_id]["options"] if o["value"] == value)

    def test_display_screen_db_backed(self):
        black = self.opt("SQ001", "black_screen")
        yellow = self.opt("SQ001", "yellow_screen")
        self.assertTrue(black["db_backed"])
        self.assertEqual(black["feature_id"],
                         "F_(image)(operator_display)_display_screen_black_screen")
        self.assertTrue(yellow["db_backed"])
        self.assertEqual(yellow["feature_id"],
                         "F_(image)(operator_display)_display_screen_yellow_screen")

    def test_garbled_is_extension_not_fault_value(self):
        g = self.opt("SQ001", "garbled")
        self.assertEqual(g["origin"], "vision_state")
        self.assertFalse(g["db_backed"])
        self.assertEqual(g["feature_source"], "synthesized")
        self.assertTrue(g["author_confirm"])
        self.assertTrue(g["db_phenomenon_seen"])
        self.assertIn("花屏", g["note"])

    def test_leader_display_reuses_value(self):
        black = self.opt("SQ004", "black_screen")
        self.assertEqual(black["origin"], "fault_db_value")
        self.assertFalse(black["db_backed"])
        self.assertTrue(black["db_value_seen"])
        self.assertTrue(black["author_confirm"])
        self.assertEqual(black["feature_source"], "synthesized")

    def test_noise_terms_are_user_dictated(self):
        normal = self.opt("SQ010", "normal")
        self.assertEqual(normal["value"], "normal")
        self.assertEqual(normal["label_origin"], "user_dictated")
        self.assertTrue(normal["author_confirm"])
        self.assertIn("有底噪", normal["label_plain"])
        self.assertIn("不是判据库 abnormal_value", normal["note"])

        no_noise = self.opt("SQ010", "no_noise")
        self.assertTrue(no_noise["db_backed"])
        self.assertEqual(no_noise["feature_id"],
                         "F_(image)(operator_display)_course_noise_no_noise")
        self.assertEqual(no_noise["label_origin"], "user_dictated")
        self.assertIn("无噪声", no_noise["note"])

    def test_scan_no_has_phenomenon_only(self):
        no = self.opt("SQ008", "no")
        self.assertEqual(no["origin"], "vision_state")
        self.assertFalse(no["db_backed"])
        self.assertTrue(no["db_phenomenon_seen"])
        self.assertIn("不扫描", no["db_phenomenon"])
        self.assertTrue(no["author_confirm"])

    def test_line_abnormal_from_vision_state(self):
        ab = self.opt("SQ002", "abnormal")
        self.assertEqual(ab["origin"], "vision_state")
        self.assertEqual(ab["screen_state"], "line_abnormal")

    def test_echo_db_backed(self):
        no = self.opt("SQ012", "no")
        weak = self.opt("SQ012", "weak")
        self.assertTrue(no["db_backed"])
        self.assertTrue(weak["db_backed"])
        self.assertEqual(no["feature_id"], "F_(image)(operator_display)_course_echo_no")
        self.assertEqual(weak["feature_id"], "F_(image)(operator_display)_course_echo_weak")

    def test_glide_noise_feature_id_keeps_db_typo(self):

        no_noise = self.opt("SQ011", "no_noise")
        self.assertEqual(no_noise["feature_id"],
                         "F_(image)(operator_display)_course_glide_no_noise")

    def test_author_confirm_list_mentions_bottom_noise(self):
        text = json.dumps(SQ.load_items(ITEMS)["author_confirm"], ensure_ascii=False)
        self.assertIn("有底噪", text)
        self.assertIn("无底噪", text)

class TestEvidence(unittest.TestCase):
    def setUp(self):
        self.qa = SQ.ScreenQA()

    def test_normal(self):
        rec = self.qa.answer("SQ001", "正常")
        e = rec["evidence"]
        assert_contract(self, e)
        self.assertEqual(e["value"], "normal")
        self.assertEqual(e["confidence"], 1.0)
        self.assertNotIn("feature_id", e)
        self.assertFalse(e["conflict"])

    def test_black_screen(self):
        e = self.qa.answer("SQ001", "黑屏")["evidence"]
        assert_contract(self, e)
        self.assertEqual(e["value"], "black_screen")
        self.assertEqual(e["field"], "(image)(operator_display)_display_screen")
        self.assertEqual(e["feature_id"],
                         "F_(image)(operator_display)_display_screen_black_screen")
        self.assertEqual(e["confidence"], 1.0)
        self.assertIn("人工确认", e["note"])

    def test_yellow_screen(self):
        e = self.qa.answer("SQ001", "黄屏")["evidence"]
        self.assertEqual(e["value"], "yellow_screen")
        self.assertEqual(e["feature_id"],
                         "F_(image)(operator_display)_display_screen_yellow_screen")

    def test_garbled(self):
        e = self.qa.answer("SQ001", "花屏")["evidence"]
        self.assertEqual(e["value"], "garbled")
        self.assertEqual(e["feature_source"], "synthesized")
        self.assertFalse(e.get("db_backed", False))

    def test_echo_no(self):
        e = self.qa.answer("SQ012", "无回波")["evidence"]
        self.assertEqual(e["value"], "no")
        self.assertEqual(e["field"], "(image)(operator_display)_course_echo")
        self.assertEqual(e["route"], "I")
        self.assertEqual(e["feature_id"], "F_(image)(operator_display)_course_echo_no")

    def test_echo_weak(self):
        e = self.qa.answer("SQ013", "回波弱")["evidence"]
        self.assertEqual(e["value"], "weak")
        self.assertEqual(e["feature_id"], "F_(image)(operator_display)_glide_echo_weak")

    def test_no_noise(self):
        e = self.qa.answer("SQ010", "无底噪")["evidence"]
        self.assertEqual(e["value"], "no_noise")
        self.assertEqual(e["part"], "z14")
        self.assertEqual(e["feature_id"],
                         "F_(image)(operator_display)_course_noise_no_noise")

    def test_skip(self):
        e = self.qa.answer("SQ001", "看不清")["evidence"]
        self.assertEqual(e["value"], "skipped")
        self.assertEqual(e["confidence"], 0.0)
        self.assertTrue(e["skipped"])
        self.assertNotIn("feature_id", e)
        self.assertFalse(e["conflict"])
        assert_contract(self, e)

    def test_line_direction_error(self):
        e = self.qa.answer("SQ007", "方向错误")["evidence"]
        self.assertEqual(e["value"], "abnormal")
        self.assertEqual(e["screen_state"], "line_abnormal")

    def test_scan_no(self):
        e = self.qa.answer("SQ008", "不扫描")["evidence"]
        self.assertEqual(e["value"], "no")
        self.assertEqual(e["screen_state"], "no_scan")
        self.assertEqual(e["feature_source"], "synthesized")

class TestConflict(unittest.TestCase):
    def setUp(self):
        self.qa = SQ.ScreenQA()

    def test_agree(self):
        e = self.qa.answer("SQ001", "黄屏", vision_hint="yellow_screen")["evidence"]
        self.assertFalse(e["conflict"])
        self.assertEqual(e["hint_match"], "agree")
        self.assertEqual(e["value"], "yellow_screen")
        self.assertIs(e["vision_reliable"], False)

    def test_disagree_qa_wins(self):
        e = self.qa.answer("SQ001", "正常", vision_hint="yellow_screen")["evidence"]
        self.assertTrue(e["conflict"])
        self.assertEqual(e["hint_match"], "disagree")
        self.assertEqual(e["value"], "normal")          
        self.assertEqual(e["vision_value"], "yellow_screen")
        self.assertIn("以人工确认为准", e["note"])

    def test_hint_dict_from_screen_hint(self):
        hint = SH.hint_from_vision("yellow_screen", 0.72)
        e = self.qa.answer("SQ001", "正常", vision_hint=hint)["evidence"]
        self.assertTrue(e["conflict"])
        self.assertEqual(e["vision_hint"], "画面偏黄")
        self.assertIs(e["vision_reliable"], False)

    def test_unknown_hint(self):
        e = self.qa.answer("SQ001", "正常", vision_hint="undetermined")["evidence"]
        self.assertFalse(e["conflict"])
        self.assertEqual(e["hint_match"], "unknown")

    def test_not_comparable_screen_vs_echo(self):
        e = self.qa.answer("SQ012", "无回波", vision_hint="black_screen")["evidence"]
        self.assertFalse(e["conflict"])
        self.assertEqual(e["hint_match"], "not_comparable")
        self.assertEqual(e["value"], "no")

    def test_skip_with_hint(self):
        e = self.qa.answer("SQ001", "看不清", vision_hint="yellow_screen")["evidence"]
        self.assertEqual(e["value"], "skipped")
        self.assertFalse(e["conflict"])
        self.assertEqual(e["hint_match"], "not_comparable")

    def test_field_mismatch_not_comparable(self):
        hint = {"vision_hint": "画面偏黄", "vision_value": "yellow_screen",
                "field": "(image)(leader_display)_display_screen", "available": True}
        e = self.qa.answer("SQ001", "正常", vision_hint=hint)["evidence"]
        self.assertEqual(e["hint_match"], "not_comparable")
        self.assertFalse(e["conflict"])

    def test_reliable_true_is_ignored(self):
        hint = {"vision_hint": "画面偏黄", "vision_value": "yellow_screen",
                "reliable": True, "available": True}
        e = self.qa.answer("SQ001", "正常", vision_hint=hint)["evidence"]
        self.assertIs(e["vision_reliable"], False)
        self.assertTrue(e["conflict"])

    def test_no_hint(self):
        e = self.qa.answer("SQ001", "正常")["evidence"]
        self.assertFalse(e["conflict"])
        self.assertEqual(e["hint_match"], "none")
        self.assertEqual(e["vision_hint"], "")

    def test_noise_hint_is_ignored(self):

        e = self.qa.answer("SQ010", "有底噪", vision_hint="no_noise")["evidence"]
        self.assertFalse(e["conflict"])
        self.assertTrue(e["hint_ignored"])
        self.assertEqual(e["hint_match"], "none")
        self.assertEqual(e["vision_hint"], "")
        self.assertEqual(e["value"], "normal")

class TestResolutionAndBatch(unittest.TestCase):
    def setUp(self):
        self.qa = SQ.ScreenQA()

    def test_label_and_alias_resolution(self):
        self.assertEqual(self.qa.answer("SQ001", "黄屏")["value"], "yellow_screen")
        self.assertEqual(self.qa.answer("SQ010", "无底噪")["value"], "no_noise")
        self.assertEqual(self.qa.answer("SQ010", "有底噪")["value"], "normal")
        self.assertEqual(self.qa.answer("SQ001", "看不清")["value"], "skipped")

    def test_case_insensitive_id(self):
        self.assertEqual(self.qa.answer("sq001", "正常")["qa_id"], "SQ001")

    def test_invalid_answer(self):
        with self.assertRaises(ValueError):
            self.qa.answer("SQ001", "紫色")

    def test_summary_and_batch(self):
        for it in self.qa.items:
            self.qa.answer(it["qa_id"], "正常")
        s = self.qa.summary()
        self.assertEqual(s["total"], 15)
        self.assertEqual(s["answered"], 15)
        self.assertEqual(s["normal"], 15)
        self.assertEqual(s["abnormal"], 0)
        self.assertEqual(len(s["evidence"]), 15)
        for e in s["evidence"]:
            assert_contract(self, e)

    def test_include_skipped(self):
        self.qa.answer("SQ001", "看不清")
        self.assertEqual(len(self.qa.evidence(include_skipped=True)), 1)
        self.assertEqual(len(self.qa.evidence(include_skipped=False)), 0)

class TestPatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patch = load(PATCH)
        cls.items = {it["qa_id"]: it for it in SQ.load_items(ITEMS)["items"]}
        cls.steps = {s["step_id"]: s for s in load(STEPS)["steps"]}

    def test_counts(self):
        self.assertEqual(self.patch["schema"], "steps_patch/v1")
        self.assertEqual(self.patch["counts"]["screen_items"], 15)
        self.assertEqual(self.patch["counts"]["steps_patched"], 13)
        self.assertEqual(sorted(self.patch["counts"]["steps_with_two_screen_items"]),
                         ["21", "26"])

    def test_step_ids_exist_and_every_item_once(self):
        seen = []
        for p in self.patch["patches"]:
            self.assertIn(p["step_id"], self.steps)
            self.assertEqual(p["append_to"], "step.qa_items")
            for q in p["qa_items_append"]:
                self.assertIn(q["qa_id"], self.items)
                seen.append(q["qa_id"])
        self.assertEqual(sorted(seen), sorted(self.items))

    def test_21_and_26_have_two(self):
        by_id = {p["step_id"]: p for p in self.patch["patches"]}
        self.assertEqual([q["qa_id"] for q in by_id["21"]["qa_items_append"]],
                         ["SQ012", "SQ013"])
        self.assertEqual([q["qa_id"] for q in by_id["26"]["qa_items_append"]],
                         ["SQ014", "SQ015"])
        self.assertEqual(by_id["21"]["existing_qa_ids"],
                         ["QA048", "QA049", "QA050", "QA051", "QA052"])

    def test_result_row(self):
        row = self.patch["result_row"]
        self.assertIn("视觉提示", row["template"])
        self.assertIn("人工确认", row["template"])
        self.assertIn("参考", row["template"])

    def test_patch_is_reproducible(self):
        rebuilt = SQ.build_patch(SQ.load_items(ITEMS))
        self.assertEqual(rebuilt, self.patch)

class TestScreenHint(unittest.TestCase):
    def test_yellow_hint(self):
        h = SH.hint_from_vision("yellow_screen", 0.7)
        self.assertTrue(h["available"])
        self.assertEqual(h["vision_hint"], "画面偏黄")
        self.assertIs(h["reliable"], False)
        self.assertIs(h["hint_only"], True)
        self.assertEqual(h["decided_by"], "qa")
        self.assertIn("不作判定依据", h["note"])

    def test_noise_is_never_judged(self):
        h = SH.hint_from_vision("no_noise", binding_ref="course_noise")
        self.assertFalse(h["available"])
        self.assertTrue(h["suppressed"])
        self.assertIn("参考样本", h["reason"])
        h2 = SH.hint_from_vision("ok", binding_ref="glide_noise")
        self.assertFalse(h2["available"])

    def test_context_mapping(self):
        self.assertEqual(SH.hint_from_vision("no", binding_ref="course_scan")["vision_hint"],
                         "不扫描")
        self.assertEqual(SH.hint_from_vision("no", binding_ref="course_echo")["vision_hint"],
                         "无回波")
        self.assertEqual(SH.hint_from_vision("ok", binding_ref="course_echo")["vision_hint"],
                         "有回波（视觉粗判）")

    def test_undetermined(self):
        h = SH.hint_from_vision("undetermined")
        self.assertFalse(h["available"])
        self.assertEqual(h["vision_hint"], "")

    def test_selftest(self):
        report = SH.selftest()
        self.assertTrue(report["ok"], report["failures"])

class TestSelfcheck(unittest.TestCase):
    def test_selfcheck_ok(self):
        ok, report = SQ.selfcheck()
        self.assertTrue(ok, report["errors"])
        self.assertEqual(report["items"], 15)
        self.assertEqual(report["steps_patched"], 13)

if __name__ == "__main__":
    unittest.main(verbosity=2)
