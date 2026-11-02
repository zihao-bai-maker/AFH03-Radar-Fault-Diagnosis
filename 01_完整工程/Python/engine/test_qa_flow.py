#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_qa_flow.py —— 60 项问答引擎单元测试（纯标准库 unittest，无 pytest 依赖）。

运行：
    python3 test_qa_flow.py -v
    python3 -m unittest test_qa_flow -v

覆盖：
* 清单：60 项 / 21 个 flow / SOP 顺序 / method 过滤 / part 映射 / UI rect
* 判据：正常判据、异常枚举、feature_id 对齐（真值库 25 条 + 合成标记）
* 引擎：start/current/answer/next/skip/summary、证据 6 键格式、电压数值、
  skip_if 建议与级联自动跳过、jump/abort、strict、confidence 校验
* 生成：--build 可复现（与 qa_items.json 完全一致）、源文件 sha256
* CLI：--selfcheck / --demo / --list（进程内调用，不启子进程）
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import qa_flow  

ITEMS = HERE / "qa_items.json"
CANVAS_W, CANVAS_H = 1024, 600

TASK_KEYS = ["part", "route", "modality", "field", "value", "confidence", "note"]
CONTRACT_KEYS = TASK_KEYS + ["evidence", "ts"]
TS_RE = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$"

def assert_evidence_contract(test, e):
    test.assertEqual(list(e.keys())[:7], TASK_KEYS)
    for k in CONTRACT_KEYS:
        test.assertIn(k, e)
    test.assertTrue(e["evidence"], "evidence 不能为空")
    test.assertRegex(e["ts"], TS_RE)
    test.assertEqual(e["modality"], "qa")
    test.assertIn(e["route"], ("", "I", "II"))

EXPECTED_FLOW_COUNTS = {
    "2": 1, "3": 3, "4": 1, "5(5-I)": 1, "6(5-II)": 2, "7": 2,
    "9(7-I)": 1, "10(7-II)": 1, "11(8-I)": 1, "12(8-II)": 1,
    "13(9-I)": 1, "14(9-II)": 1, "15(10-I)": 11, "16（10-II）": 11,
    "17": 4, "19": 2, "20": 2, "21": 6, "24": 1, "25": 1, "26": 6,
}

EXPECTED_REAL_FEATURES = {
    "QA002": ("under_voltage", "F_(manual_action)_z18_phase_a_voltage_under_voltage"),
    "QA019": ("no_move", "F_(manual_action)_internal_control_glide_left_no_move"),
    "QA024": ("no_move", "F_(manual_action)(operator_display)_external_control_glide_left_no_move"),
    "QA038": ("no_move", "F_(manual_action)(pilot_display)_external_control_course_up_no_move"),
    "QA043": ("not_done", "F_(manual_action)_z20_antenna_start_power_on_not_done"),
    "QA044": ("start_fail", "F_(manual_action)_antenna_main_motion_start_fail"),
    "QA046": ("not_done", "F_(manual_action)_switch_to_route_one_not_done"),
    "QA047": ("not_done", "F_(manual_action)_z20_transmit_control_power_on_not_done"),
}

def _load():
    with open(ITEMS, "r", encoding="utf-8") as f:
        return json.load(f)

class TestCatalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = _load()
        cls.items = cls.data["items"]
        cls.by_id = {it["qa_id"]: it for it in cls.items}

    def test_schema_and_count(self):
        self.assertEqual(self.data["schema"], "qa_items/v1")
        self.assertEqual(len(self.items), 60)

    def test_unique_ids_and_seq(self):
        ids = [it["qa_id"] for it in self.items]
        self.assertEqual(ids, ["QA%03d" % i for i in range(1, 61)])
        self.assertEqual([it["seq"] for it in self.items], list(range(1, 61)))

    def test_method_filter(self):
        for it in self.items:
            self.assertEqual(it["method"], "交互问答确认", it["qa_id"])
            self.assertNotEqual(it["method"], "摄像头拍摄")

    def test_flow_order(self):
        idx = [it["flow_index"] for it in self.items]
        self.assertEqual(idx, sorted(idx))
        self.assertEqual(self.data["flow_order"], list(EXPECTED_FLOW_COUNTS.keys()))

    def test_flow_coverage_exact(self):
        counts = {}
        for it in self.items:
            counts[it["flow_no"]] = counts.get(it["flow_no"], 0) + 1
        self.assertEqual(counts, EXPECTED_FLOW_COUNTS)
        self.assertEqual(len(counts), 21)
        self.assertEqual(sum(counts.values()), 60)

    def test_part_and_route(self):
        for it in self.items:
            self.assertRegex(it["part"], r"^z\d{1,2}$", it["qa_id"])
            self.assertIn(it["route"], ("", "I", "II"), it["qa_id"])
            self.assertEqual(it["part_origin"] != "fallback", True, it["qa_id"])
            self.assertTrue(it["evidence_field"].startswith("(manual_action)"), it["qa_id"])

    def test_part_spot_checks(self):
        cases = {
            "QA001": ("z31", ""),   
            "QA002": ("z18", ""),   
            "QA006": ("z12", "I"),  
            "QA007": ("z12", "II"), 
            "QA009": ("z5", "I"),   
            "QA010": ("z20", "I"),  
            "QA017": ("z16", "I"),  
            "QA019": ("z4", "I"),   
            "QA024": ("z4", "I"),   
            "QA030": ("z4", "II"),  
            "QA041": ("z15", "I"),  
            "QA044": ("z4", ""),    
            "QA048": ("z11", "I"),  
            "QA056": ("z11", "II"), 
            "QA055": ("z20", "II"), 
        }
        for qid, (part, route) in cases.items():
            self.assertEqual((self.by_id[qid]["part"], self.by_id[qid]["route"]),
                             (part, route), qid)

    def test_required_text(self):
        for it in self.items:
            self.assertTrue(it["question"], it["qa_id"])
            self.assertTrue(it["normal"], it["qa_id"])
            self.assertTrue(it["ui"]["question"], it["qa_id"])
            self.assertIn("正常判据", it["ui"]["normal"])
            self.assertTrue(it["phenomenon"], it["qa_id"])
            self.assertTrue(it["evidence_subject"], it["qa_id"])
            self.assertIn(it["category"], ("人工动作", "性能指标"))

    def test_abnormalities_and_features(self):
        total = 0
        real = 0
        for it in self.items:
            self.assertGreaterEqual(len(it["abnormalities"]), 2, it["qa_id"])
            self.assertEqual(it["abnormalities"][0]["value"],
                             it["options"][1]["value"], it["qa_id"])
            for ab in it["abnormalities"]:
                total += 1
                self.assertTrue(ab["feature_id"].startswith("F_"), it["qa_id"])
                self.assertIn(ab["source"], ("fault_library", "synthesized"))
                if ab["source"] == "fault_library":
                    real += 1
            self.assertEqual(it["primary_feature_id"], it["options"][1]["feature_id"])
        self.assertGreaterEqual(total, 100)
        self.assertGreaterEqual(real, 20)   

    def test_real_feature_alignment(self):
        for qid, (value, fid) in EXPECTED_REAL_FEATURES.items():
            opt = next(o for o in self.by_id[qid]["options"] if o["value"] == value)
            self.assertEqual(opt["feature_id"], fid, qid)
            self.assertEqual(opt["feature_source"], "fault_library", qid)

    def test_ui_buttons(self):
        for it in self.items:
            opts = it["options"]
            self.assertGreaterEqual(len(opts), 2, it["qa_id"])
            self.assertLessEqual(len(opts), 4, it["qa_id"])
            self.assertEqual(opts[0]["value"], "done", it["qa_id"])
            for o in opts:
                self.assertTrue(o["label"].endswith(("✔", "✗")), o["label"])
                self.assertNotIn("✔", o["label_plain"])
                self.assertNotIn("✗", o["label_plain"])
                self.assertTrue(o["action"].startswith("qa:"), o["action"])
                x0, y0, x1, y1 = o["rect"]
                self.assertTrue(0 <= x0 < x1 <= CANVAS_W)
                self.assertTrue(0 <= y0 < y1 <= CANVAS_H)
                self.assertGreaterEqual(x1 - x0, 200, "按钮不够大（触摸）")
                self.assertGreaterEqual(y1 - y0, 80, "按钮不够高（触摸）")

            rects = [o["rect"] for o in opts] + [it["ui"]["skip_button"]["rect"],
                                                 it["ui"]["back_button"]["rect"]]
            for i in range(len(rects)):
                for j in range(i + 1, len(rects)):
                    a, b = rects[i], rects[j]
                    self.assertTrue(a[2] <= b[0] or b[2] <= a[0]
                                    or a[3] <= b[1] or b[3] <= a[1],
                                    "%s rect 重叠 %r %r" % (it["qa_id"], a, b))
            self.assertEqual(it["ui"]["skip_button"]["action"], "qa:skip")
            self.assertEqual(it["ui"]["skip_button"]["value"], "skipped")
            self.assertEqual(it["ui"]["back_button"]["action"], "qa:back")
            self.assertEqual(it["ui"]["screen"], {"w": 1024, "h": 600})

    def test_skip_if_rules_valid(self):
        with_deps = 0
        for it in self.items:
            si = it["skip_if"]
            if not si:
                continue
            with_deps += 1
            self.assertEqual(si["mode"], "any")
            for rule in si["rules"]:
                self.assertIn(rule["qa_id"], self.by_id)
                self.assertNotEqual(rule["qa_id"], it["qa_id"], "不能依赖自己")
                src_values = {o["value"] for o in self.by_id[rule["qa_id"]]["options"]}
                self.assertTrue(set(rule["values"]) <= src_values,
                                "%s -> %s 的值不在源题选项" % (it["qa_id"], rule["qa_id"]))
        self.assertGreaterEqual(with_deps, 40)

    def test_skip_if_spot_checks(self):
        def deps(qid):
            return [r["qa_id"] for r in self.by_id[qid]["skip_if"]["rules"]]
        self.assertIn("QA001", deps("QA002"))   
        self.assertIn("QA018", deps("QA019"))   
        self.assertIn("QA047", deps("QA048"))   
        self.assertIn("QA054", deps("QA055"))   
        self.assertIn("QA007", deps("QA055"))

    def test_build_reproducible(self):
        if not (qa_flow.SOP_CSV.is_file() and qa_flow.FAULT_CSV.is_file()):
            self.skipTest("判据库不在本机（板端只跑运行时）")
        built = qa_flow.build_items()
        self.assertEqual(built, self.data)

    def test_source_hashes(self):
        if not (qa_flow.SOP_CSV.is_file() and qa_flow.FAULT_CSV.is_file()):
            self.skipTest("判据库不在本机")
        self.assertEqual(self.data["source"]["sop_sha256"],
                         qa_flow._sha256(qa_flow.SOP_CSV))
        self.assertEqual(self.data["source"]["faults_sha256"],
                         qa_flow._sha256(qa_flow.FAULT_CSV))

class TestEngine(unittest.TestCase):
    def setUp(self):
        self.flow = qa_flow.QAFlow()

    def test_start_current(self):
        cur = self.flow.start()
        self.assertEqual(cur["qa_id"], "QA001")
        self.assertEqual(cur["progress"], "1/60")
        self.assertEqual(self.flow.progress()["index"], 1)
        self.assertEqual(self.flow.progress()["total"], 60)
        self.assertFalse(cur["answered"])
        self.assertFalse(cur["skip_suggested"])

    def test_answer_done_evidence_exact(self):
        self.flow.start()
        rec = self.flow.answer("done")
        self.assertFalse(rec["abnormal"])
        self.assertIsNone(rec["feature_id"])
        e = rec["evidence"]
        assert_evidence_contract(self, e)
        self.assertEqual((e["part"], e["route"], e["modality"]), ("z31", "", "qa"))
        self.assertEqual(e["field"], "(manual_action)_z31_control_power_on")
        self.assertEqual(e["value"], "done")
        self.assertEqual(e["confidence"], 1.0)
        self.assertEqual(e["note"], "操作员确认")
        self.assertEqual(e["evidence"], "操作员确认：Z31 控制电源 正常")
        self.assertEqual(e["source"], "qa_flow.QAFlow")
        self.assertEqual(e["item_id"], "QA001")
        self.assertEqual(e["flow_no"], "2")
        self.assertEqual(self.flow.summary()["evidence"], [e])

    def test_answer_no_reaction(self):
        self.flow.start()
        rec = self.flow.answer("no_reaction")
        self.assertTrue(rec["abnormal"])
        self.assertEqual(rec["value"], "no_reaction")
        self.assertEqual(rec["feature_id"],
                         "F_(manual_action)_z31_control_power_on_no_reaction")
        self.assertIn("无反应", rec["evidence"]["note"])
        self.assertEqual(rec["evidence"]["value"], "no_reaction")

    def test_answer_aliases(self):
        self.flow.start()
        self.assertEqual(self.flow.answer("正常")["value"], "done")
        self.flow.start()
        self.assertEqual(self.flow.answer("无反应")["value"], "no_reaction")
        self.flow.start()
        rec = self.flow.answer("跳过")
        self.assertTrue(rec["skipped"])
        self.assertIsNone(rec["evidence"])

    def test_invalid_answer(self):
        self.flow.start()
        self.flow.answer("done")
        with self.assertRaises(ValueError):
            self.flow.answer("banana")
        self.assertEqual(self.flow.summary()["answered"], 1)

    def test_answer_confidence(self):
        self.flow.start()
        rec = self.flow.answer("done", confidence=0.5)
        self.assertEqual(rec["evidence"]["confidence"], 0.5)
        with self.assertRaises(ValueError):
            self.flow.answer("done", confidence=1.5)

    def test_full_flow_done(self):
        self.flow.start()
        n = 0
        while self.flow.current() is not None:
            self.flow.answer("done")
            self.flow.next()
            n += 1
        self.assertEqual(n, 60)
        self.assertIsNone(self.flow.current())
        s = self.flow.summary()
        self.assertTrue(s["complete"])
        self.assertTrue(s["finished"])
        self.assertEqual((s["answered"], s["verified"], s["abnormal"], s["skipped"], s["pending"]),
                         (60, 60, 0, 0, 0))
        self.assertEqual(len(s["evidence"]), 60)
        self.assertEqual(s["by_value"], {"done": 60})
        for e in s["evidence"]:
            assert_evidence_contract(self, e)

    def test_skip_manual(self):
        self.flow.start()
        self.flow.skip()
        self.assertEqual(self.flow.current()["qa_id"], "QA002")
        s = self.flow.summary()
        self.assertEqual((s["answered"], s["skipped"], s["verified"]), (1, 1, 0))
        self.assertEqual(s["evidence"], [])
        inc = self.flow.summary(include_skipped_evidence=True)["evidence"]
        self.assertEqual(len(inc), 1)
        self.assertEqual(inc[0]["value"], "skipped")
        self.assertEqual(inc[0]["confidence"], 0.0)
        assert_evidence_contract(self, inc[0])

    def test_skip_if_suggestion_not_blocking(self):
        self.flow.start()
        self.flow.answer("not_done")
        cur = self.flow.next()
        self.assertEqual(cur["qa_id"], "QA002")
        self.assertTrue(cur["skip_suggested"])
        self.assertIn("QA001", cur["skip_reason"])

        rec = self.flow.answer("done")
        self.assertEqual(rec["value"], "done")

    def test_skip_if_auto_cascade(self):
        self.flow.start()
        self.flow.answer("not_done")
        cur = self.flow.next(auto_skip=True)
        self.assertEqual(cur["qa_id"], "QA009")       
        s = self.flow.summary()
        self.assertEqual(s["skipped"], 7)
        self.assertEqual([x["qa_id"] for x in s["skipped_items"]],
                         ["QA002", "QA003", "QA004", "QA005", "QA006", "QA007", "QA008"])
        self.assertTrue(all(x["auto"] for x in s["skipped_items"]))

        self.assertEqual(len(s["evidence"]), 1)
        self.assertEqual(s["evidence"][0]["value"], "not_done")
        self.assertEqual(len(self.flow.evidence(include_skipped=True)), 8)

    def test_good_answer_no_suggestion(self):
        self.flow.start()
        self.flow.answer("done")
        cur = self.flow.next()
        self.assertEqual(cur["qa_id"], "QA002")
        self.assertFalse(cur["skip_suggested"])

    def test_evidence_subject_fixes_library_typo(self):

        self.flow.start("QA043")
        rec = self.flow.answer("not_done")
        self.assertIn("天线启动", rec["evidence"]["evidence"])
        self.assertNotIn("雷达工频通", rec["evidence"]["evidence"])

    def test_voltage_numeric(self):
        cur = self.flow.start("QA002")
        self.assertEqual(cur["kind"], "voltage")
        rec = self.flow.answer("185")
        self.assertEqual(rec["value"], "under_voltage")
        self.assertEqual(rec["measured"], 185.0)
        self.assertIn("实测 185V", rec["evidence"]["note"])
        self.assertIn("实测 185V", rec["evidence"]["evidence"])
        self.assertEqual(rec["feature_id"],
                         "F_(manual_action)_z18_phase_a_voltage_under_voltage")
        assert_evidence_contract(self, rec["evidence"])

        self.flow.start("QA002")
        rec = self.flow.answer("250V")
        self.assertEqual(rec["value"], "over_voltage")
        self.assertEqual(rec["measured"], 250.0)
        self.assertEqual(rec["feature_source"], "synthesized")
        self.assertIn("过压", rec["evidence"]["evidence"])

        self.flow.start("QA002")
        rec = self.flow.answer(220)
        self.assertEqual(rec["value"], "done")
        self.assertEqual(rec["evidence"]["note"], "操作员确认")
        self.assertIn("正常", rec["evidence"]["evidence"])

        with self.assertRaises(ValueError):
            self.flow.answer("abc")

    def test_schema_values_mode(self):

        f = qa_flow.QAFlow()
        f.start()
        self.assertEqual(f.answer("done")["evidence"]["value"], "done")
        f.start()
        self.assertEqual(f.answer("no_reaction")["evidence"]["value"], "no_reaction")
        f.start("QA002")
        self.assertEqual(f.answer("250")["evidence"]["value"], "over_voltage")

        f = qa_flow.QAFlow(schema_values=True)
        f.start()
        e = f.answer("done")["evidence"]
        self.assertEqual(e["value"], "normal")
        f.start()
        rec = f.answer("no_reaction")
        self.assertEqual(rec["evidence"]["value"], "not_done")
        self.assertEqual(rec["evidence"]["qa_value"], "no_reaction")
        self.assertEqual(rec["feature_id"],
                         "F_(manual_action)_z31_control_power_on_no_reaction")
        f.start("QA002")
        rec = f.answer("250")
        self.assertEqual(rec["evidence"]["value"], "abnormal")
        self.assertEqual(rec["evidence"]["qa_value"], "over_voltage")
        assert_evidence_contract(self, rec["evidence"])

    def test_fusion_accepts_contract_evidence(self):
        try:
            import fusion  
        except Exception:  
            self.skipTest("fusion.py 不在本机")
        f = qa_flow.QAFlow()
        f.start("QA002")
        rec = f.answer("under_voltage")
        fr = fusion.FusionEngine().fuse([rec["evidence"]])
        ev = fr.evidence[0]
        self.assertEqual(ev.category, "abnormal")
        self.assertFalse(ev.ts_filled, "QA 必须自带 ts，不能由融合层补记")
        self.assertEqual(ev.evidence, rec["evidence"]["evidence"])

        f2 = qa_flow.QAFlow(schema_values=True)
        f2.start()
        rec2 = f2.answer("no_reaction")
        fr2 = fusion.FusionEngine().fuse([rec2["evidence"]])
        self.assertEqual(fr2.evidence[0].category, "abnormal")

    def test_summary_by_part_and_route(self):
        self.flow.start()
        self.flow.answer("not_done")          
        self.flow.jump("QA009")
        self.flow.answer("done")              
        self.flow.jump("QA019")
        self.flow.answer("no_move")           
        s = self.flow.summary()
        self.assertEqual(s["by_part"]["z31"], {"total": 1, "done": 0, "abnormal": 1,
                                               "skipped": 0, "pending": 0})
        self.assertEqual(s["by_part"]["z5"]["done"], 1)
        self.assertEqual(s["by_part"]["z4"]["abnormal"], 1)
        self.assertEqual(s["by_route"]["I"]["abnormal"], 1)
        self.assertEqual(s["by_route"]["I"]["total"], 28)   
        self.assertEqual(s["by_route"]["II"]["total"], 23)
        self.assertEqual(s["by_route"]["-"]["total"], 9)

    def test_jump_and_abort(self):
        self.flow.start()
        cur = self.flow.jump("QA047")
        self.assertEqual(cur["qa_id"], "QA047")
        self.flow.answer("done")
        s = self.flow.summary()
        self.assertEqual(s["answered"], 1)
        self.assertFalse(s["finished"])
        s = self.flow.abort()
        self.assertTrue(s["finished"])
        self.assertFalse(s["complete"])
        self.assertEqual(s["pending"], 59)

    def test_strict_next(self):
        f = qa_flow.QAFlow(strict=True)
        f.start()
        with self.assertRaises(RuntimeError):
            f.next()
        f.answer("done")
        self.assertEqual(f.next()["qa_id"], "QA002")

    def test_reanswer_overwrites(self):
        self.flow.start()
        self.flow.answer("not_done")
        self.flow.answer("done")
        s = self.flow.summary()
        self.assertEqual(s["answered"], 1)
        self.assertEqual(s["evidence"][0]["value"], "done")

    def test_skip_advance_false(self):
        self.flow.start()
        self.flow.skip(advance=False)
        self.assertEqual(self.flow.current()["qa_id"], "QA001")
        self.assertTrue(self.flow.current()["answer"]["skipped"])

    def test_unknown_qa_id(self):
        with self.assertRaises(KeyError):
            self.flow.start("QA999")
        with self.assertRaises(KeyError):
            self.flow.jump("QA000")

    def test_progress(self):
        self.flow.start()
        self.flow.answer("done")
        p = self.flow.progress()
        self.assertEqual((p["index"], p["total"], p["answered"], p["verified"], p["pending"]),
                         (1, 60, 1, 1, 59))
        self.assertEqual(p["percent"], round(100.0 / 60, 1))

    def test_evidence_jsonl(self):
        self.flow.start()
        self.flow.answer("done")
        lines = self.flow.evidence_jsonl().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), self.flow.summary()["evidence"][0])

    def test_evidence_batch(self):
        self.flow.start()
        self.flow.answer("done")
        batch = self.flow.evidence_batch()
        self.assertEqual(batch["schema"], "evidence/v1")
        self.assertEqual(batch["producer"], "qa_flow.py")
        self.assertEqual(len(batch["evidence"]), 1)
        assert_evidence_contract(self, batch["evidence"][0])
        try:
            import fusion
        except Exception:  
            return
        fr = fusion.FusionEngine().fuse(batch)
        self.assertEqual(len(fr.evidence), 1)
        self.assertEqual(fr.evidence[0].category, "normal")

class TestLoaderAndCli(unittest.TestCase):
    def test_bad_schema_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            p.write_text(json.dumps({"schema": "nope", "items": []}), encoding="utf-8")
            with self.assertRaises(ValueError):
                qa_flow.load_items(p)

    def test_cli_selfcheck(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = qa_flow.main(["--selfcheck"])
        self.assertEqual(rc, 0)
        self.assertIn("PASS", out.getvalue())

    def test_cli_demo(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = qa_flow.main(["--demo"])
        self.assertEqual(rc, 0)
        self.assertIn('"verified": 60', out.getvalue())
        self.assertIn("evidence[0]", out.getvalue())

    def test_cli_list(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = qa_flow.main(["--list"])
        self.assertEqual(rc, 0)
        self.assertIn("共 60 项", out.getvalue())
        self.assertIn("15(10-I)", out.getvalue())

if __name__ == "__main__":
    unittest.main(verbosity=2)
