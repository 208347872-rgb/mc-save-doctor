"""世界俯视图：每列取最高的非空气方块上色，手写 PNG（不依赖 PIL）。

这样别人 pip 装完就能用，不用再装 Pillow / numpy。
"""
from __future__ import annotations

import glob
import os
import struct
import zlib

from . import blocks

COLORS = {
    "grass_block": (100, 160, 60), "dirt": (134, 96, 67), "coarse_dirt": (120, 85, 60),
    "podzol": (110, 80, 45), "mycelium": (140, 130, 130), "farmland": (90, 65, 45),
    "stone": (128, 128, 128), "cobblestone": (105, 105, 105), "mossy_cobblestone": (95, 115, 80),
    "deepslate": (75, 75, 80), "tuff": (108, 109, 102), "andesite": (135, 135, 135),
    "diorite": (190, 190, 190), "granite": (150, 105, 90), "calcite": (220, 220, 215),
    "gravel": (135, 125, 125), "sand": (220, 210, 160), "red_sand": (190, 110, 50),
    "sandstone": (215, 205, 155), "water": (55, 100, 190), "lava": (255, 100, 0),
    "snow": (245, 250, 250), "ice": (150, 200, 240),
    "oak_planks": (170, 135, 80), "spruce_planks": (115, 85, 50),
    "birch_planks": (200, 180, 130), "dark_oak_planks": (80, 55, 30),
    "oak_log": (105, 80, 45), "spruce_log": (70, 50, 30), "birch_log": (215, 215, 205),
    "oak_leaves": (60, 120, 45), "spruce_leaves": (45, 90, 50), "birch_leaves": (90, 140, 60),
    "torch": (255, 210, 80), "wall_torch": (255, 210, 80), "lantern": (255, 200, 100),
    "glass": (200, 230, 240), "glass_pane": (200, 230, 240), "crafting_table": (150, 100, 60),
    "furnace": (110, 110, 110), "chest": (170, 120, 50), "barrel": (140, 100, 55),
    "white_wool": (235, 235, 235), "red_wool": (170, 45, 45),
    "stone_bricks": (120, 120, 120), "bricks": (150, 90, 80), "ladder": (170, 135, 80),
    "obsidian": (30, 20, 45), "gold_block": (250, 220, 90), "iron_bars": (150, 150, 150),
    "short_grass": (110, 170, 70), "tall_grass": (110, 170, 70), "wheat": (200, 180, 90),
    "coal_ore": (60, 60, 60), "iron_ore": (180, 150, 130), "bedrock": (40, 40, 40),
}


def color_of(name):
    if not name:
        return (0, 0, 0)
    n = name.replace("minecraft:", "")
    if n in COLORS:
        return COLORS[n]
    if n.endswith("_planks"):
        return (170, 135, 80)
    if n.endswith("_log") or n.endswith("_wood"):
        return (100, 75, 45)
    if n.endswith("_leaves"):
        return (60, 120, 45)
    if n.endswith("_wool") or n.endswith("_concrete"):
        return (215, 215, 215)
    if n.endswith("_bed"):
        return (200, 40, 40)
    if n.endswith("_ore"):
        return (120, 120, 120)
    if "water" in n:
        return (55, 100, 190)
    if "lava" in n:
        return (255, 100, 0)
    if "stone" in n or "granite" in n or "andesite" in n or "diorite" in n or "deepslate" in n:
        return (128, 128, 128)
    if "dirt" in n or "mud" in n:
        return (134, 96, 67)
    if "grass" in n or "fern" in n or "bush" in n:
        return (100, 170, 60)
    if "snow" in n:
        return (240, 245, 245)
    if "sand" in n:
        return (220, 210, 160)
    return (90, 90, 90)


def _png(chunk_list, width, height):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + row for row in chunk_list)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


def render(world, dim, x0, x1, z0, z1, scale=2, markers=()):
    """渲染一块矩形区域，返回 (png bytes, 宽, 高)。

    markers: [(x, z, (r,g,b))]，会在图上画 5x5 的十字，用来标玩家/死亡点。
    """
    x0, x1 = int(x0), int(x1)
    z0, z1 = int(z0), int(z1)
    if x1 < x0:
        x0, x1 = x1, x0
    if z1 < z0:
        z0, z1 = z1, z0
    scale = max(1, int(scale))
    top = {}

    region_dir = world.dimensions().get(dim)
    if not region_dir:
        raise FileNotFoundError(f"找不到维度 {dim} 的 region 目录")

    for path in sorted(glob.glob(os.path.join(region_dir, "r.*.*.mca"))):
        base = os.path.basename(path)
        try:
            rx, rz = int(base.split(".")[1]), int(base.split(".")[2])
        except (IndexError, ValueError):
            continue
        if not (rx * 512 <= x1 and (rx + 1) * 512 >= x0
                and rz * 512 <= z1 and (rz + 1) * 512 >= z0):
            continue
        from . import region as region_mod
        try:
            reg = region_mod.RegionFile(path)
        except OSError:
            continue
        for entry in reg.chunks():
            if not (entry.cx * 16 <= x1 and entry.cx * 16 + 15 >= x0
                    and entry.cz * 16 <= z1 and entry.cz * 16 + 15 >= z0):
                continue
            try:
                from . import nbt
                _, payload = nbt.parse(reg.read_nbt_bytes(entry))
                chunk = payload.get("Level") if isinstance(payload.get("Level"), dict) else payload
            except Exception:                        # noqa: BLE001 —— 单个坏 chunk 不该拖垮整张图
                continue
            for sec in blocks.sections(chunk):
                sy = sec.get("Y", 0) or 0
                for lx, ly, lz, name in blocks.iter_section_blocks(sec):
                    wx, wz, wy = entry.cx * 16 + lx, entry.cz * 16 + lz, sy * 16 + ly
                    if not (x0 <= wx <= x1 and z0 <= wz <= z1):
                        continue
                    cur = top.get((wx, wz))
                    if cur is None or cur[0] < wy:
                        top[(wx, wz)] = (wy, name)

    width, height = (x1 - x0 + 1) * scale, (z1 - z0 + 1) * scale
    if width <= 0 or height <= 0:
        raise ValueError("区域大小不对")

    # 先算每个像素的颜色，再给标记点画十字
    px = {}
    for (wx, wz), (_wy, name) in top.items():
        px[(wx, wz)] = color_of(name)
    for mx, mz, col in markers:
        mx, mz = int(mx), int(mz)
        for dx in range(-2, 3):
            for dz in range(-2, 3):
                if (dx == 0 or dz == 0) or (abs(dx) == 2 and abs(dz) == 2):
                    px[(mx + dx, mz + dz)] = col

    rows = []
    for z in range(z0, z1 + 1):
        row = bytearray()
        for x in range(x0, x1 + 1):
            row += bytes(px.get((x, z), (0, 0, 0))) * scale
        for _ in range(scale):
            rows.append(bytes(row))

    return _png(rows, width, height), width, height


def auto_box(world, dim, center_x, center_z, size=256):
    """以某点为中心切一块 size x size 的区域（不越世界边界也没关系，缺的涂黑）。"""
    half = int(size) // 2
    return (center_x - half, center_x + half, center_z - half, center_z + half)
