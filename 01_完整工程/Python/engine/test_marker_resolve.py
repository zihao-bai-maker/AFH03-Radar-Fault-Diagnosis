# -*- coding: utf-8 -*-
"""test_marker_resolve.py —— 二维码代替方案解析模块的单元测试。

运行：
    cd 雷达判据/engine
    python test_marker_resolve.py
或：
    python -m unittest test_marker_resolve -v

★ 2026-10-25 更新（现场口述，权威）：现场有两块 Z14 板 —— Z14（信处）与
  Z14-CLK（时钟板），**Z14-CLK 这块现在当 Z14 使用** ⇒ `z14 + I` 与 `z14 + II`
  **都返回 `z14`**（原 z14-信处 / z14-CLK 是同一块 Z14 板的同义词）。

★ 用例隔离：解析/文案类用例跑**固定权威映射**（FIXTURE）+ 临时 JSON，
  不吃 `markers_v2/markers_v2_plus_G.json` 的现场改动 —— 多 agent 并行时数据文件
  在变，跟着它断言会让用例无故变红。真实数据文件的结构/别名由 TestDataLayer 覆盖。
"""

import copy
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import marker_resolve as mr                                             

ROOT = os.path.dirname(HERE)                                            
MARKERS = os.path.join(ROOT, "markers_v2", "markers_v2_plus_G.json")
LED = os.path.abspath(os.path.join(ROOT, "..", "afh03_board_setup",
                                  "config", "led_rules.json"))

FIXTURE = {
    "version": 2,
    "modules": {
        "Z11": {"label": "Z11", "part": "z11",
                "module_by_route": {"I": "z11-收发", "II": "z11-1"}},
        "Z12": {"label": "Z12", "part": "z12",
                "module_by_route": {"I": "z12-电源", "II": "z12-GL"}},
        "Z14": {"label": "Z14", "part": "z14",
                "module_by_route": {"I": "z14", "II": "z14"}},
        "Z15": {"label": "Z15", "part": "z15",
                "module_by_display": {"操显": "z15-显示电路", "领显": "z15-IF"}},
    },
    "markers": [],
}

class TestResolveMapping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls.fixture_path = tempfile.mkstemp(suffix=".json", prefix="markers_fixture_")
        os.close(fd)
        cls.write_doc(cls.fixture_path, FIXTURE)
        cls._old_env = os.environ.get("AFH03_MARKERS_JSON")
        os.environ["AFH03_MARKERS_JSON"] = cls.fixture_path
        mr.reload()

    @classmethod
    def tearDownClass(cls):
        if cls._old_env is None:
            os.environ.pop("AFH03_MARKERS_JSON", None)
        else:
            os.environ["AFH03_MARKERS_JSON"] = cls._old_env
        mr.reload()
        try:
            os.unlink(cls.fixture_path)
        except OSError:
            pass

    @staticmethod
    def write_doc(path, doc):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)

    def test_z11_route_I(self):
        self.assertEqual(mr.resolve("z11", route="I"), "z11-收发")

    def test_z11_route_II(self):
        self.assertEqual(mr.resolve("z11", route="II"), "z11-1")

    def test_z12_route_I(self):
        self.assertEqual(mr.resolve("z12", route="I"), "z12-电源")

    def test_z12_route_II(self):
        self.assertEqual(mr.resolve("z12", route="II"), "z12-GL")

    def test_z14_route_I(self):

        self.assertEqual(mr.resolve("z14", route="I"), "z14")

    def test_z14_route_II(self):

        self.assertEqual(mr.resolve("z14", route="II"), "z14")

    def test_z14_both_routes_same_part(self):
        self.assertEqual(mr.resolve("z14", route="I"),
                         mr.resolve("z14", route="II"))
        for route in ("i", "1", "一路", "I", "ii", "2", "二路", "II"):
            self.assertEqual(mr.resolve("z14", route=route), "z14", route)

    def test_z14_module_canon(self):

        self.assertEqual(mr._canon("z14-信处"), "z14")
        self.assertEqual(mr._canon("z14-CLK"), "z14")
        self.assertEqual(mr._canon("z14"), "z14")

        self.assertEqual(mr._canon("z11-收发"), "z11-收发")
        self.assertEqual(mr._canon("z12-GL"), "z12-GL")

    def test_z15_display_caoxian(self):
        self.assertEqual(mr.resolve("z15", display_kind="操显"), "z15-显示电路")

    def test_z15_display_lingxian(self):
        self.assertEqual(mr.resolve("z15", display_kind="领显"), "z15-IF")

    def test_route_aliases(self):
        for route in ("i", "1", "01", "一", "一路", "1路", "Ⅰ", "I路"):
            self.assertEqual(mr.resolve("z11", route=route), "z11-收发", route)
        for route in ("ii", "2", "二", "二路", "2路", "Ⅱ", "II路"):
            self.assertEqual(mr.resolve("z11", route=route), "z11-1", route)

    def test_display_aliases(self):
        for disp in ("操显", "操显屏", "操作显示"):
            self.assertEqual(mr.resolve("z15", display_kind=disp), "z15-显示电路", disp)
        for disp in ("领显", "领显屏"):
            self.assertEqual(mr.resolve("z15", display_kind=disp), "z15-IF", disp)

    def test_part_case_insensitive(self):
        self.assertEqual(mr.resolve("Z11", route="I"), "z11-收发")
        self.assertEqual(mr.resolve(" Z12 ", route="ii"), "z12-GL")
        self.assertEqual(mr.resolve(" Z14 ", route="ii"), "z14")

    def test_missing_route_returns_part(self):
        self.assertEqual(mr.resolve("z11"), "z11")
        self.assertEqual(mr.resolve("z12", display_kind="操显"), "z12")

    def test_invalid_route_returns_part(self):
        self.assertEqual(mr.resolve("z11", route="III"), "z11")
        self.assertEqual(mr.resolve("z11", route=""), "z11")

    def test_z15_route_only_returns_part(self):

        self.assertEqual(mr.resolve("z15", route="I"), "z15")
        self.assertEqual(mr.resolve("z15", route="II"), "z15")

    def test_missing_display_returns_part(self):
        self.assertEqual(mr.resolve("z15"), "z15")
        self.assertEqual(mr.resolve("z15", display_kind="未知显示"), "z15")

    def test_unknown_part_returns_original(self):
        self.assertEqual(mr.resolve("z99", route="I"), "z99")
        self.assertEqual(mr.resolve("foo"), "foo")

    def test_internal_part_unchanged(self):
        self.assertEqual(mr.resolve("z11-1", route="I"), "z11-1")
        self.assertEqual(mr.resolve("z15-IF", display_kind="领显"), "z15-IF")

    def test_none_part(self):
        self.assertIsNone(mr.resolve(None, route="I"))
        self.assertEqual(mr.describe(None), "")

    def test_describe_all_eight(self):
        cases = [
            (("z11", "I", None), "Z11（I路）→ z11-收发（代替码推断）"),
            (("z11", "II", None), "Z11（II路）→ z11-1（代替码推断）"),
            (("z12", "I", None), "Z12（I路）→ z12-电源（代替码推断）"),
            (("z12", "II", None), "Z12（II路）→ z12-GL（代替码推断）"),
            (("z14", "I", None), "Z14（I路）→ z14（代替码推断）"),
            (("z14", "II", None), "Z14（II路）→ z14（代替码推断）"),
            (("z15", None, "操显"), "Z15（操显）→ z15-显示电路（代替码推断）"),
            (("z15", None, "领显"), "Z15（领显）→ z15-IF（代替码推断）"),
        ]
        for (part, route, disp), want in cases:
            got = mr.describe(part, route=route, display_kind=disp)
            self.assertEqual(got, want)
            self.assertIn("（代替码推断）", got)
            self.assertNotIn("直接标识", got)

    def test_describe_z14_still_counts_as_inference(self):

        
        for route in ("I", "II"):
            got = mr.describe("z14", route=route)
            self.assertIn("（代替码推断）", got)
            self.assertIn("→ z14", got)
            self.assertNotIn("未推断", got)

    def test_describe_missing_param(self):
        self.assertEqual(mr.describe("z11"), "Z11（未推断：需要路别 I/II）")
        self.assertEqual(mr.describe("z15"), "Z15（未推断：需要操显/领显）")
        self.assertNotIn("代替码推断", mr.describe("z11"))

    def test_describe_uses_actual_matched_param(self):

        self.assertEqual(mr.describe("z11", route="II", display_kind="操显"),
                         "Z11（II路）→ z11-1（代替码推断）")
        self.assertEqual(mr.describe("z15", route="I", display_kind="领显"),
                         "Z15（领显）→ z15-IF（代替码推断）")

    def test_describe_direct_identification(self):
        self.assertEqual(mr.describe("z11-1"), "z11-1（直接标识）")
        self.assertEqual(mr.describe("z99"), "z99（直接标识）")
        self.assertNotIn("代替码推断", mr.describe("z11-1"))

    def test_mapping_loads_fixture_counts(self):
        info = mr.mapping_info()
        self.assertEqual(info["n_codes"], 4)
        self.assertEqual(info["n_markers"], 0)
        self.assertEqual(info["n_legacy"], 4)
        self.assertEqual(info["n_rules"], 4)
        self.assertEqual(info["n_edges"], 8)
        self.assertTrue(os.path.isfile(info["path"]))

    def test_mapping_path_is_fixture(self):
        self.assertEqual(os.path.abspath(mr.mapping_info()["path"]),
                         os.path.abspath(self.fixture_path))

    def test_resolver_is_data_driven(self):
        doc = copy.deepcopy(FIXTURE)
        doc["modules"]["Z11"]["module_by_route"]["I"] = "z11-测试覆盖"
        fd, path = tempfile.mkstemp(suffix=".json", prefix="markers_test_")
        os.close(fd)
        try:
            self.write_doc(path, doc)
            old = os.environ.get("AFH03_MARKERS_JSON")
            os.environ["AFH03_MARKERS_JSON"] = path
            try:
                mr.reload()
                self.assertEqual(mr.resolve("z11", route="I"), "z11-测试覆盖")

                self.assertEqual(mr.resolve("z14", route="II"), "z14")
            finally:
                if old is None:
                    os.environ.pop("AFH03_MARKERS_JSON", None)
                else:
                    os.environ["AFH03_MARKERS_JSON"] = old
                mr.reload()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

class TestDataLayer(unittest.TestCase):
    """真实数据文件的结构/别名检查（不吃 FIXTURE）。"""

    @classmethod
    def setUpClass(cls):
        with open(MARKERS, encoding="utf-8") as f:
            cls.doc = json.load(f)
        cls.mods = cls.doc["modules"]
        cls.markers = cls.doc["markers"]
        with open(LED, encoding="utf-8") as f:
            cls.led = json.load(f)
        cls.led_by_id = {p["id"]: p for p in cls.led["parts"]}

    def test_24_code_structure_preserved(self):
        self.assertEqual(len(self.markers), 18)
        self.assertEqual(len(self.mods), 24)
        ids = sorted(m["marker_id"] for m in self.mods.values())
        self.assertEqual(ids, list(range(24)))
        self.assertEqual(len({m["code_hex"] for m in self.mods.values()}), 24)
        self.assertEqual(self.doc["dictionary"]["n"], 24)

        mod_by_id = {m["marker_id"]: m for m in self.mods.values()}
        for m in self.markers:
            self.assertEqual(mod_by_id[m["id"]]["part"], m["part"])

    def test_cabinet_codes_have_route_mapping(self):

        

        for bucket in (self.markers, list(self.mods.values())):
            entry = next(e for e in bucket if e.get("part") == "z14")
            self.assertEqual(entry.get("module_by_route"), {"I": "z14", "II": "z14"})
            self.assertTrue(entry.get("note"))
            for part in ("z11", "z12"):
                entry = next(e for e in bucket if e.get("part") == part)
                routes = entry.get("module_by_route") or {}
                self.assertEqual(set(routes), {"I", "II"}, part)
                self.assertTrue(all(routes.values()), part)

    def test_z14_resolves_to_z14_on_real_data(self):
        mr.reload()
        try:
            self.assertEqual(mr.resolve("z14", route="I"), "z14")
            self.assertEqual(mr.resolve("z14", route="II"), "z14")
        finally:
            mr.reload()

    def test_z15_has_display_mapping(self):
        want = {"操显": "z15-显示电路", "领显": "z15-IF"}
        for bucket in (self.markers, list(self.mods.values())):
            entry = next(e for e in bucket if e.get("part") == "z15")
            self.assertEqual(entry.get("module_by_display"), want)
            self.assertEqual(entry.get("module_by_display_kind"), want)
            self.assertNotIn("module_by_route", entry)
            self.assertIn("代替码推断", entry.get("note", ""))

    def test_substitution_scheme_has_4_rules(self):
        scheme = self.doc["substitution_scheme"]
        self.assertEqual(set(k for k in scheme if k.startswith("z")),
                         {"z11", "z12", "z14", "z15"})
        self.assertIn("代替码推断", scheme["_note"])

    def test_led_aliases_eight_modules(self):
        expected = {
            "Z11": {"z11-收发", "z11@I", "一路Z11"},
            "Z11-1": {"z11@II", "二路Z11"},
            "Z12_PWR": {"z12-电源", "z12@I", "一路Z12"},
            "Z12-GL": {"z12@II", "二路Z12"},
            "Z14_PANEL": {"z14-信处", "z14@I", "一路Z14"},

            "Z14-CLK": {"z14@II", "二路Z14", "z14"},
            "Z15_PANEL": {"z15-显示电路", "z15@操显", "操显Z15"},
            "Z15-IF": {"z15@领显", "领显Z15"},
        }
        self.assertEqual(len(expected), 8)
        for pid, need in expected.items():
            aliases = self.led_by_id[pid].get("aliases") or []
            self.assertTrue(need <= set(aliases), "%s 缺别名: %s" % (pid, need - set(aliases)))
            self.assertEqual(len(aliases), len(set(aliases)), "%s 有重复别名" % pid)

            
            if pid.startswith("Z14"):
                self.assertIn("代替码推断", self.led_by_id[pid].get("substitution_note", ""))

    def test_led_status_unchanged(self):

        
        expected = {
            "Z14_PANEL": "现场口述_待核对",
            "Z14-CLK": "现场口述_待核对",
        }
        for pid, status in expected.items():
            self.assertEqual(self.led_by_id[pid].get("status", ""), status, pid)
        for pid in ("Z11", "Z11-1", "Z12_PWR", "Z12-GL", "Z15_PANEL", "Z15-IF"):
            self.assertTrue(self.led_by_id[pid].get("status"), pid)

    def test_led_part_count_unchanged(self):
        self.assertEqual(len(self.led["parts"]), 25)

    def test_z14clk_lamps_identical_to_z14_panel(self):
        clk = self.led_by_id["Z14-CLK"]
        panel = self.led_by_id["Z14_PANEL"]
        self.assertEqual(len(panel["lamps"]), 3)
        self.assertEqual(clk["lamps"], panel["lamps"])

    def test_z14clk_three_lamps_expected(self):
        clk = self.led_by_id["Z14-CLK"]
        self.assertEqual(clk.get("kind"), "led")
        self.assertEqual(clk.get("expected_count"), 3)
        self.assertEqual(clk.get("expected_colors"), ["green", "red", "green"])
        self.assertEqual([l.get("name") for l in clk["lamps"]],
                         ["复位", "电源", "3.15A 保险丝"])
        self.assertEqual([l.get("expect") for l in clk["lamps"]],
                         ["on", "on", "off"])

    def test_z14clk_status_and_note(self):
        clk = self.led_by_id["Z14-CLK"]
        self.assertEqual(clk.get("status"), "现场口述_待核对")
        self.assertEqual(clk.get("note"),
                         "现场说明：两块 Z14，Z14-CLK 板当 Z14 使用（2026-10-25 用户口述）")
        self.assertIn("当 Z14 使用", clk.get("status_note", ""))

if __name__ == "__main__":
    unittest.main(verbosity=2)
