"""扫 region：谁待得最久、哪些方块是玩家放的。

主力证据是 chunk 的 InhabitedTime（玩家在这个 chunk 里待了多少 tick，1200 tick = 1 分钟）。
方块密度只是辅助：矿井和村庄满地都是木板和火把，单看方块必然误判。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import blocks

TICKS_PER_MINUTE = 1200

# 玩家才会放的方块实体（村庄/遗迹不会自然生成酿造台、告示牌）
PLAYER_BLOCKS = {
    "minecraft:brewing_stand": "酿造台",
    "minecraft:sign": "告示牌",
    "minecraft:hanging_sign": "悬挂告示牌",
    "minecraft:chest": "箱子",
    "minecraft:trapped_chest": "陷阱箱",
    "minecraft:barrel": "木桶",
    "minecraft:ender_chest": "末影箱",
    "minecraft:furnace": "熔炉",
    "minecraft:blast_furnace": "高炉",
    "minecraft:smoker": "烟熏炉",
    "minecraft:crafting_table": "工作台",
    "minecraft:enchanting_table": "附魔台",
    "minecraft:beacon": "信标",
    "minecraft:hopper": "漏斗",
    "minecraft:dispenser": "发射器",
    "minecraft:dropper": "投掷器",
    "minecraft:white_bed": "床",
    "minecraft:red_bed": "床",
    "minecraft:blue_bed": "床",
    "minecraft:black_bed": "床",
    "minecraft:spawner": "刷怪笼",
}

# 地表人工方块（判断「这里有人造过东西」，必须和 InhabitedTime 交叉验证）
ARTIFICIAL = {
    "minecraft:oak_planks", "minecraft:spruce_planks", "minecraft:birch_planks",
    "minecraft:jungle_planks", "minecraft:acacia_planks", "minecraft:dark_oak_planks",
    "minecraft:cobblestone", "minecraft:stone_bricks", "minecraft:bricks",
    "minecraft:torch", "minecraft:wall_torch", "minecraft:lantern",
    "minecraft:glass", "minecraft:glass_pane", "minecraft:chest",
    "minecraft:crafting_table", "minecraft:furnace", "minecraft:ladder",
}


@dataclass
class ChunkStat:
    cx: int
    cz: int
    inhabited: int = 0
    entities: dict = field(default_factory=dict)   # 方块实体种类 -> 个数
    samples: list = field(default_factory=list)    # [(种类, x, y, z)]
    artificial: int = 0                            # 地表人工方块个数

    @property
    def x(self):
        return self.cx * 16 + 8

    @property
    def z(self):
        return self.cz * 16 + 8

    @property
    def minutes(self):
        return self.inhabited / TICKS_PER_MINUTE


@dataclass
class Zone:
    cx: int
    cz: int
    inhabited: int
    chunks: int
    entities: dict
    samples: list
    artificial: int = 0

    @property
    def x(self):
        return self.cx * 16 + 8

    @property
    def z(self):
        return self.cz * 16 + 8


def chunk_entities(chunk):
    """读 block_entities / TileEntities，只留玩家相关的。"""
    out = {}
    samples = []
    for key in ("block_entities", "TileEntities", "tile_entities"):
        raw = chunk.get(key)
        if not isinstance(raw, list):
            continue
        for be in raw:
            if not isinstance(be, dict):
                continue
            bid = be.get("id")
            if not isinstance(bid, str):
                continue
            label = PLAYER_BLOCKS.get(bid)
            if not label:
                continue
            short = label
            out[short] = out.get(short, 0) + 1
            x, y, z = be.get("x"), be.get("y"), be.get("z")
            if x is None or y is None or z is None:
                pos = be.get("Pos")
                if isinstance(pos, (list, tuple)) and len(pos) >= 3:
                    x, y, z = (int(pos[0]), int(pos[1]), int(pos[2]))
            if x is not None and y is not None and z is not None:
                try:
                    samples.append((short, int(x), int(y), int(z)))
                except (TypeError, ValueError):
                    pass
    return out, samples


def scan(world, dim):
    """扫一个维度。返回 (chunk 列表, 错误列表)。"""
    stats = []
    errors = []
    for _reg, entry, chunk, err in world.iter_chunks(dim):
        if err:
            errors.append(err)
            continue
        if entry is None:
            continue
        st = ChunkStat(entry.cx, entry.cz)
        try:
            st.inhabited = int(chunk.get("InhabitedTime") or 0)
        except (TypeError, ValueError):
            st.inhabited = 0
        st.entities, st.samples = chunk_entities(chunk)
        stats.append(st)
    return stats, errors


def surface_scan(chunk):
    """数一个 chunk 里的人工方块（y>=40，排除地下矿井）。"""
    count = 0
    for sec in blocks.sections(chunk):
        sy = sec.get("Y", 0) or 0
        for lx, ly, lz, name in blocks.iter_section_blocks(sec):
            if name in ARTIFICIAL and sy * 16 + ly >= 40:
                count += 1
    return count


def zones(stats, radius=8, limit=5):
    """把挨在一起的 chunk 并成一个「热区」，按总停留时间排序。

    radius 单位是 chunk（8 chunk = 128 格）。
    """
    remaining = sorted(stats, key=lambda s: s.inhabited, reverse=True)
    out = []
    used = set()
    for s in remaining:
        key = (s.cx, s.cz)
        if key in used or s.inhabited <= 0:
            continue
        members = [t for t in remaining
                   if (t.cx, t.cz) not in used
                   and abs(t.cx - s.cx) <= radius and abs(t.cz - s.cz) <= radius]
        if not members:
            continue
        used.update((t.cx, t.cz) for t in members)
        total = sum(t.inhabited for t in members)
        entities = {}
        samples = []
        artificial = 0
        for t in members:
            for k, v in t.entities.items():
                entities[k] = entities.get(k, 0) + v
            samples.extend(t.samples[:40])
            artificial += t.artificial
        out.append(Zone(cx=s.cx, cz=s.cz, inhabited=total, chunks=len(members),
                        entities=entities, samples=samples, artificial=artificial))
        if len(out) >= limit:
            break
    return out


def dimension_hint(dim):
    if dim == "the_nether":
        return "下界里 tp 前先想好落点，y 太高会掉进岩浆海"
    if dim == "the_end":
        return "末地 tp 要小心虚空"
    return None


def human_time(ticks):
    """tick -> 「3 小时 12 分」这种。"""
    minutes = ticks / TICKS_PER_MINUTE
    if minutes < 1:
        return "不到 1 分钟"
    hours = int(minutes // 60)
    minutes = int(minutes % 60)
    if hours:
        return f"{hours} 小时 {minutes} 分"
    return f"{minutes} 分钟"
