"""真跑一遍：假存档 + 真格式，覆盖解析、找家、地图、报告、修坏档、CLI。

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

from helpers import (make_legacy_world, make_modern_world, make_player,
                     region_file_for, write_region, write_region_dir,
                     chunk_payload)  # noqa: E402  (helpers 自己会加 src 到 sys.path)

from mcsavedoctor import nbt, region, render, repair, report, survey, locate  # noqa: E402
from mcsavedoctor.cli import main  # noqa: E402
from mcsavedoctor.world import World  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mcsd-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)

    def rb(self, path):
        with open(path, "rb") as f:
            return f.read()

    def rt(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()


class TestNbt(Base):
    def test_roundtrip(self):
        payload = {
            "Data": {
                "LevelName": "试一下",
                "n": nbt.Int(42),
                "l": nbt.Long(1 << 40),
                "b": nbt.Byte(-3),
                "f": nbt.Float(1.5),
                "arr": nbt.IntArray([1, 2, 3]),
                "longs": nbt.LongArray([-1, 0, (1 << 63) - 1]),
                "list": [{"id": "minecraft:stone", "Count": nbt.Byte(1)}],
                "empty": [],
            }
        }
        p = self.path("x.dat")
        nbt.save(p, "", payload)
        got = nbt.load_payload(p)
        self.assertEqual(got["Data"]["LevelName"], "试一下")
        self.assertEqual(got["Data"]["n"], 42)
        self.assertEqual(got["Data"]["arr"], [1, 2, 3])
        self.assertEqual(got["Data"]["empty"], [])

    def test_uncompressed_and_truncated(self):
        raw = nbt.dumps("", {"a": 1}, compress=False)
        name, payload = nbt.parse(raw)
        self.assertEqual(payload["a"], 1)
        with self.assertRaises(nbt.NbtError):
            nbt.parse(raw[:-3])


class TestWorld(Base):
    def test_modern_layout(self):
        root = make_modern_world(self.path("新存档"))
        w = World(root)
        self.assertEqual(w.name, "测试世界")
        self.assertEqual(w.spawn, (-560, 64, 16))
        self.assertTrue(w.allow_commands)
        self.assertIn("overworld", w.dimensions())
        players = w.players()
        self.assertEqual(len(players), 1)
        self.assertEqual(players[0].pos, (1247.5, 65.0, 1269.5))
        self.assertEqual(players[0].dimension, "minecraft:overworld")
        self.assertEqual(players[0].xp_level, 7)
        self.assertIsNone(players[0].spawn)      # 没睡过床

    def test_legacy_layout(self):
        root = make_legacy_world(self.path("老存档"))
        w = World(root)
        self.assertEqual(w.name, "老世界")
        self.assertEqual(w.spawn, (10, 70, 20))   # SpawnX/Y/Z
        self.assertFalse(w.allow_commands)
        self.assertEqual(sorted(w.dimensions()), ["overworld", "the_nether"])
        self.assertEqual(len(w.players()), 1)
        self.assertTrue(w.players()[0].path.endswith("playerdata")
                        or "playerdata" in w.players()[0].path)

    def test_saves_dir_autodetect(self):
        make_modern_world(self.path("saves", "唯一世界"))
        w = World(self.path("saves"))
        self.assertEqual(w.name, "测试世界")

    def test_players_extra(self):
        root = make_modern_world(self.path("有死亡点"), death=(300, 12, -400), bed=(1200, 65, 1250))
        w = World(root)
        p = w.players()[0]
        self.assertEqual(p.last_death, (300, 12, -400))
        self.assertEqual(p.last_death_dim, "minecraft:overworld")
        self.assertEqual(p.spawn, (1200, 65, 1250))


class TestSurvey(Base):
    def test_find_home_zone(self):
        root = make_modern_world(self.path("找家"))
        w = World(root)
        chunks, errors = survey.scan(w, "overworld")
        self.assertEqual(errors, [])
        self.assertEqual(len(chunks), 3)
        zones = survey.zones(chunks, limit=3)
        self.assertEqual(zones[0].cx, 78)
        self.assertEqual(zones[0].cz, 79)
        self.assertEqual(zones[0].x, 1256)       # 78*16+8
        self.assertEqual(zones[0].inhabited, 120_000)
        self.assertEqual(zones[0].entities.get("箱子"), 2)
        self.assertEqual(survey.human_time(120_000), "1 小时 40 分")

    def test_zone_merges_neighbours(self):
        payloads = [
            (5, 5, chunk_payload(5, 5, inhabited=10_000)),
            (6, 5, chunk_payload(6, 5, inhabited=5_000)),
            (40, 40, chunk_payload(40, 40, inhabited=9_000)),
        ]
        root = make_modern_world(self.path("并区"), chunks=payloads)
        w = World(root)
        chunks, _ = survey.scan(w, "overworld")
        zones = survey.zones(chunks, radius=8, limit=5)
        self.assertEqual(zones[0].inhabited, 15_000)
        self.assertEqual(zones[0].chunks, 2)
        self.assertEqual(zones[1].inhabited, 9_000)

    def test_surface_y(self):
        root = make_modern_world(self.path("地表"))
        w = World(root)
        # section Y=4，方块在 ly=0..15 全是 stone -> 最高 4*16+15 = 79
        self.assertEqual(w.surface_y("overworld", 1250, 1270), 79)

    def test_nameless_palette(self):
        """26.x 某些存档的调色板写成无名 compound：{"": "minecraft:stone"}。"""
        payload = chunk_payload(3, 3, inhabited=10)
        sec = payload["sections"][0]
        sec["block_states"]["palette"] = [{"": "minecraft:stone"}]
        root = make_modern_world(self.path("无名调色板"), chunks=[(3, 3, payload)])
        w = World(root)
        self.assertEqual(w.surface_y("overworld", 3 * 16 + 5, 3 * 16 + 5), 79)
        chunks, _ = survey.scan(w, "overworld")
        self.assertEqual(chunks[0].inhabited, 10)


class TestRender(Base):
    def test_png(self):
        root = make_modern_world(self.path("画图"))
        w = World(root)
        png, wide, high = render.render(w, "overworld", 1240, 1272, 1260, 1290,
                                        scale=2, markers=[(1250, 1270, (255, 0, 0))])
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual((wide, high), (33 * 2, 31 * 2))
        # 解回像素，确认标点位是红的、地面是灰的
        import struct
        import zlib
        import binascii
        pos, idat = 8, b""
        while pos < len(png):
            length = struct.unpack(">I", png[pos:pos + 4])[0]
            tag = png[pos + 4:pos + 8]
            data = png[pos + 8:pos + 8 + length]
            if tag == b"IDAT":
                idat += data
            pos += 12 + length
        raw = zlib.decompress(idat)
        stride = wide * 3 + 1
        self.assertEqual(len(raw), stride * high)
        # 标记点在 (1250,1270)，图上像素 (10*2, 10*2)
        off = 20 * stride + 1 + 20 * 3
        self.assertEqual(tuple(raw[off:off + 3]), (255, 0, 0))
        # 别处应该是石头灰（假存档地面全是 stone），取世界坐标 (1255,1272)
        off2 = 24 * stride + 1 + 30 * 3
        self.assertEqual(tuple(raw[off2:off2 + 3]), (128, 128, 128))


class TestReport(Base):
    def test_html(self):
        root = make_modern_world(self.path("报告"), death=(1250, 20, 1270))
        old = os.getcwd()
        os.chdir(self.tmp)
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = main(["report", root, "-o", self.path("r.html")])
        finally:
            os.chdir(old)
        self.assertEqual(code, 0)
        text = self.rt(self.path("r.html"))
        self.assertIn("测试世界", text)
        self.assertIn("/tp 1256 81 1272", text)          # 热区 tp
        self.assertIn("data:image/png;base64,", text)    # 地图内嵌
        self.assertIn("体检结果", text)


class TestRepair(Base):
    def test_level_dat_from_old(self):
        root = make_modern_world(self.path("坏level"))
        good = self.rb(os.path.join(root, "level.dat"))
        with open(os.path.join(root, "level.dat_old"), "wb") as f:
            f.write(good)
        with open(os.path.join(root, "level.dat"), "wb") as f:
            f.write(b"\x1f\x8b\x08\x00garbage-not-gzip")
        w = World(root)
        self.assertIsNotNone(w.level_error)

        issues, _ = repair.diagnose(w)
        codes = {i.code for i in issues}
        self.assertIn("level_unreadable", codes)
        self.assertTrue(any(i.fixable for i in issues))

        log, backup = repair.apply_issues(w, issues, dry_run=False)
        self.assertTrue(any("恢复" in line for line in log))
        self.assertTrue(os.path.isdir(backup))
        again = World(root)
        self.assertIsNone(again.level_error)
        self.assertEqual(again.name, "测试世界")

    def test_dry_run_touches_nothing(self):
        root = make_modern_world(self.path("演练"))
        good = nbt.dumps("", {"Data": {"LevelName": "能救回来"}})
        with open(os.path.join(root, "level.dat_old"), "wb") as f:
            f.write(good)
        with open(os.path.join(root, "level.dat"), "wb") as f:
            f.write(b"broken")
        w = World(root)
        issues, _ = repair.diagnose(w)
        before = self.rb(os.path.join(root, "level.dat"))
        log, backup = repair.apply_issues(w, issues, dry_run=True)
        self.assertIsNone(backup)
        self.assertEqual(self.rb(os.path.join(root, "level.dat")), before)
        self.assertTrue(any("演练" in line for line in log))

    def test_isolate_bad_chunk(self):
        # 同一个 region 文件里放两个 chunk：一个砸坏，一个完好
        root = make_modern_world(self.path("坏chunk"), chunks=[
            (78, 79, chunk_payload(78, 79, inhabited=120_000)),
            (79, 79, chunk_payload(79, 79, inhabited=1_000)),
        ])
        rpath = region_file_for(os.path.join(root, "dimensions", "minecraft", "overworld", "region"), 78, 79)
        with open(rpath, "rb") as f:
            data = bytearray(f.read())
        # 把第二个 chunk（78,79）的压缩数据砸坏
        reg = region.RegionFile(rpath)
        target = [e for e in reg.chunks() if (e.cx, e.cz) == (78, 79)][0]
        start = target.byte_offset + 5
        for i in range(start, start + 20):
            data[i] = 0xFF
        with open(rpath, "wb") as f:
            f.write(bytes(data))

        w = World(root)
        issues, stats = repair.diagnose(w)
        self.assertGreaterEqual(stats["chunk_errors"], 1)
        bad = [i for i in issues if i.code == "chunk_unreadable"]
        self.assertEqual(len(bad), 1)
        self.assertTrue(bad[0].fixable)

        log, backup = repair.apply_issues(w, issues, dry_run=False)
        self.assertTrue(os.path.isdir(backup))
        # 隔离后：坏的那个从头部消失，完好的邻居还在
        reg2 = region.RegionFile(rpath)
        self.assertNotIn((78, 79), [(e.cx, e.cz) for e in reg2.chunks()])
        self.assertIn((79, 79), [(e.cx, e.cz) for e in reg2.chunks()])
        issues2, stats2 = repair.diagnose(w)
        self.assertEqual(stats2["chunk_errors"], 0)
        chunks, _ = survey.scan(w, "overworld")
        self.assertEqual(len(chunks), 1)
        # 原始文件必须躺在备份目录里（保留相对路径）
        self.assertTrue(os.path.isfile(os.path.join(
            backup, "dimensions", "minecraft", "overworld", "region", os.path.basename(rpath))))

    def test_bad_player(self):
        root = make_modern_world(self.path("坏玩家"))
        pdat = os.path.join(root, "players", "data", "11111111-2222-3333-4444-555555555555.dat")
        with open(pdat, "wb") as f:
            f.write(b"\x1f\x8b\x08\x00nope")
        w = World(root)
        issues, _ = repair.diagnose(w)
        self.assertIn("player_unreadable", {i.code for i in issues})
        repair.apply_issues(w, issues, dry_run=False)
        self.assertFalse(os.path.isfile(pdat))
        self.assertTrue(any(".broken-" in f for f in os.listdir(os.path.dirname(pdat))))

    def test_healthy_world_is_clean(self):
        root = make_modern_world(self.path("健康"))
        issues, stats = repair.diagnose(World(root))
        self.assertEqual([i for i in issues if i.severity == "error"], [])
        self.assertEqual(stats["chunk_errors"], 0)


class TestLocate(Base):
    """小白不用知道路径：自动翻出各启动器/版本隔离里的世界。"""

    def _fake_env(self, two=True):
        home, appdata = self.path("home"), self.path("appdata")
        make_modern_world(os.path.join(appdata, ".minecraft", "versions", "26.3",
                                      "saves", "世界A"), name="世界A")
        if two:
            b = make_modern_world(os.path.join(home, ".minecraft", "saves", "世界B"), name="世界B")
            old = time.time() - 100_000
            os.utime(os.path.join(b, "level.dat"), (old, old))
        return mock.patch.dict(os.environ, {
            "APPDATA": appdata, "HOME": home, "USERPROFILE": home,
            "LOCALAPPDATA": self.path("local"),
        })

    def test_finds_both_layouts(self):
        with self._fake_env():
            cands = locate.find_worlds()
        self.assertEqual([c.name for c in cands], ["世界A", "世界B"])   # 按最后游玩倒序
        self.assertEqual(cands[0].size > 0, True)
        self.assertTrue(cands[0].path.endswith("世界A"))

    def test_duplicates_not_listed_twice(self):
        home, appdata = self.path("home"), self.path("appdata")
        # 同一个目录被两条规则撞上（home 和 USERPROFILE 相同等）
        make_modern_world(os.path.join(home, ".minecraft", "saves", "世界C"), name="世界C")
        with mock.patch.dict(os.environ, {"APPDATA": appdata, "HOME": home,
                                          "USERPROFILE": home, "LOCALAPPDATA": self.path("local")}):
            cands = locate.find_worlds()
        self.assertEqual(len([c for c in cands if c.name == "世界C"]), 1)

    def test_cli_list(self):
        with self._fake_env():
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(main(["list"]), 0)
            out = buf.getvalue()
            self.assertIn("找到 2 个世界", out)
            self.assertIn("世界A", out)
            self.assertIn("世界B", out)

    def test_cli_world_optional(self):
        with self._fake_env(two=False):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["info"]), 0)          # 不给路径也能跑
            self.assertIn("世界A", buf.getvalue())

    def test_cli_pick_by_number(self):
        with self._fake_env():
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["info", "2"]), 0)     # 2 = 世界B
            self.assertIn("世界B", buf.getvalue())

    def test_cli_many_without_choice_exits(self):
        with self._fake_env():
            with contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()), \
                 mock.patch.object(sys, "stdin", io.StringIO("")):
                with self.assertRaises(SystemExit):
                    main(["info"])


class TestCli(Base):
    def test_find_json(self):
        root = make_modern_world(self.path("cli"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = main(["find", root, "--json", "--top", "2"])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["world"]["name"], "测试世界")
        top = data["dimensions"]["overworld"][0]
        self.assertEqual((top["x"], top["z"]), (1256, 1272))
        self.assertEqual(top["tp"], "/tp 1256 81 1272")
        self.assertEqual(top["entities"], {"箱子": 2})

    def test_info_text(self):
        root = make_modern_world(self.path("cli2"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(main(["info", root]), 0)
        out = buf.getvalue()
        self.assertIn("测试世界", out)
        self.assertIn("(-560, 64, 16)", out)
        self.assertIn("没睡过床", out)

    def test_repair_cli_dry_run(self):
        root = make_modern_world(self.path("cli3"))
        with open(os.path.join(root, "level.dat"), "wb") as f:
            f.write(b"x")
        with open(os.path.join(root, "level.dat_old"), "wb") as f:
            f.write(nbt.dumps("", {"Data": {"LevelName": "救回来的世界"}}))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(["repair", root])
        self.assertEqual(code, 0)
        self.assertIn("--apply", buf.getvalue())
        self.assertEqual(self.rb(os.path.join(root, "level.dat")), b"x")


if __name__ == "__main__":
    unittest.main(verbosity=2)
