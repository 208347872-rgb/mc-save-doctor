"""世界目录识别 + level.dat / 玩家数据 / chunk 读取。

同时认两种布局：
  1.18+   <世界>/dimensions/minecraft/<维度>/region，玩家在 <世界>/players/data/
  旧版    <世界>/region、DIM-1/region、DIM1/region，玩家在 <世界>/playerdata/
"""
from __future__ import annotations

import glob
import os

from . import blocks, nbt, region

DIMENSIONS = ("overworld", "the_nether", "the_end")
LEGACY_DIM_DIRS = (("the_nether", "DIM-1"), ("the_end", "DIM1"))
DIM_BY_LEGACY_ID = {0: "overworld", -1: "the_nether", 1: "the_end"}


class WorldError(Exception):
    """给的路径不是存档。"""


class Player:
    __slots__ = ("uuid", "path", "error", "pos", "dimension", "health", "food",
                 "xp_level", "game_type", "spawn", "last_death", "last_death_dim", "items")

    def __init__(self, uuid, path):
        self.uuid = uuid
        self.path = path
        self.error = None
        self.pos = None
        self.dimension = None
        self.health = None
        self.food = None
        self.xp_level = None
        self.game_type = None
        self.spawn = None
        self.last_death = None
        self.last_death_dim = None
        self.items = 0

    def __repr__(self):
        return f"<Player {self.uuid} pos={self.pos}>"


def _vec(value):
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError):
            return None
    return None


def normalize_chunk(payload):
    """1.17 及以前 chunk 外面套一层 Level，拉平它。"""
    inner = payload.get("Level")
    if isinstance(inner, dict):
        out = dict(inner)
        out["_legacy_wrapped"] = True
        return out
    return payload


class World:
    def __init__(self, path):
        p = os.path.abspath(os.path.expanduser(str(path)))
        if not os.path.exists(p):
            raise WorldError(f"路径不存在：{p}")
        if os.path.isdir(p) and not os.path.isfile(os.path.join(p, "level.dat")):
            # 允许直接给 saves 目录：里面只有一个世界就自动认
            cands = [d for d in sorted(glob.glob(os.path.join(p, "*")))
                     if os.path.isfile(os.path.join(d, "level.dat"))]
            if len(cands) == 1:
                p = cands[0]
            elif len(cands) > 1:
                names = "、".join(os.path.basename(c) for c in cands[:6])
                raise WorldError(f"这个目录下有多个世界，请指定其中一个：{names}")
            else:
                raise WorldError(f"没找到 level.dat：{p}")
        if not os.path.isdir(p):
            raise WorldError(f"不是目录：{p}")

        self.path = p
        self.level_path = os.path.join(p, "level.dat")
        self.level_old_path = self.level_path + "_old"
        self.level = {}
        self.level_error = None
        if os.path.isfile(self.level_path):
            try:
                self.level = nbt.unwrap_data(nbt.load_payload(self.level_path))
                if not isinstance(self.level, dict):
                    raise nbt.NbtError("level.dat 根不是 compound")
            except Exception as exc:                     # noqa: BLE001 —— 坏档也要能继续体检
                self.level_error = f"level.dat 读不出来：{exc}"
        else:
            self.level_error = "level.dat 不存在"

    # ------------------------------------------------------------ 元信息
    @property
    def name(self):
        return self.level.get("LevelName") or os.path.basename(self.path)

    @property
    def version(self):
        v = self.level.get("Version")
        if isinstance(v, dict):
            return v.get("Name") or v.get("Id")
        return self.level.get("version") or self.level.get("StorageVersion")

    @property
    def data_version(self):
        return self.level.get("DataVersion")

    @property
    def spawn(self):
        sp = self.level.get("spawn")
        if isinstance(sp, dict):
            pos = sp.get("pos") or sp.get("Pos")
            if isinstance(pos, (list, tuple)) and len(pos) >= 3:
                try:
                    return (int(pos[0]), int(pos[1]), int(pos[2]))
                except (TypeError, ValueError):
                    return None
        if all(k in self.level for k in ("SpawnX", "SpawnY", "SpawnZ")):
            return (int(self.level["SpawnX"]), int(self.level["SpawnY"]), int(self.level["SpawnZ"]))
        return None

    @property
    def allow_commands(self):
        return bool(self.level.get("allowCommands"))

    @property
    def game_type(self):
        return self.level.get("GameType")

    @property
    def last_played(self):
        return self.level.get("LastPlayed")

    @property
    def day_time(self):
        return self.level.get("DayTime")

    @property
    def hardcore(self):
        return bool(self.level.get("hardcore"))

    # ------------------------------------------------------------ 目录结构
    def dimensions(self):
        """{维度名: region 目录}，只列真实存在的。"""
        out = {}
        for dim in DIMENSIONS:
            d = os.path.join(self.path, "dimensions", "minecraft", dim, "region")
            if os.path.isdir(d):
                out[dim] = d
        # mod 加维度
        for d in sorted(glob.glob(os.path.join(self.path, "dimensions", "*", "*", "region"))):
            parts = d.replace("\\", "/").split("/")
            ns, dim = parts[-3], parts[-2]
            if ns == "minecraft":
                continue
            out[f"{ns}:{dim}"] = d
        if not out:
            d = os.path.join(self.path, "region")
            if os.path.isdir(d):
                out["overworld"] = d
            for dim, sub in LEGACY_DIM_DIRS:
                d = os.path.join(self.path, sub, "region")
                if os.path.isdir(d):
                    out[dim] = d
        return out

    def region_files(self, dim):
        d = self.dimensions().get(dim)
        return sorted(glob.glob(os.path.join(d, "r.*.*.mca"))) if d else []

    # ------------------------------------------------------------ 玩家
    def player_files(self):
        files = sorted(glob.glob(os.path.join(self.path, "players", "data", "*.dat")))
        legacy = sorted(glob.glob(os.path.join(self.path, "playerdata", "*.dat")))
        seen = {os.path.basename(f) for f in files}
        files += [f for f in legacy if os.path.basename(f) not in seen]
        return files

    def players(self):
        return [self._load_player(f) for f in self.player_files()]

    def _load_player(self, path):
        p = Player(os.path.basename(path)[:-4], path)
        try:
            root = nbt.load_payload(path)
            if not isinstance(root, dict):
                raise nbt.NbtError("玩家数据根不是 compound")
        except Exception as exc:                         # noqa: BLE001
            p.error = str(exc)
            return p
        p.pos = _vec(root.get("Pos"))
        dim = root.get("Dimension")
        if isinstance(dim, str):
            p.dimension = dim
        elif isinstance(dim, int):
            p.dimension = DIM_BY_LEGACY_ID.get(dim, str(dim))
        p.health = root.get("Health")
        p.food = root.get("foodLevel")
        p.xp_level = root.get("XpLevel")
        gt = root.get("playerGameType", root.get("GameType"))
        p.game_type = gt
        if all(k in root for k in ("SpawnX", "SpawnY", "SpawnZ")):
            p.spawn = (int(root["SpawnX"]), int(root["SpawnY"]), int(root["SpawnZ"]))
        d = root.get("LastDeathLocation")
        if isinstance(d, dict):
            pos = _vec(d.get("pos"))
            if pos:
                p.last_death = (int(pos[0]), int(pos[1]), int(pos[2]))
                p.last_death_dim = d.get("dimension")
        inv = root.get("Inventory")
        if isinstance(inv, list):
            p.items = len(inv)
        return p

    # ------------------------------------------------------------ chunk
    def iter_chunks(self, dim):
        """yield (region_file, entry, chunk dict 或 None, 错误信息或 None)。"""
        for rf in self.region_files(dim):
            try:
                reg = region.RegionFile(rf)
            except Exception as exc:                     # noqa: BLE001
                yield None, None, None, f"{os.path.basename(rf)}：{exc}"
                continue
            for entry in reg.chunks():
                try:
                    raw = reg.read_nbt_bytes(entry)
                    _, payload = nbt.parse(raw)
                    if not isinstance(payload, dict):
                        raise nbt.NbtError("chunk 根不是 compound")
                    yield reg, entry, normalize_chunk(payload), None
                except Exception as exc:                 # noqa: BLE001
                    yield reg, entry, None, f"{os.path.basename(rf)} ({entry.cx},{entry.cz})：{exc}"

    def chunk_at(self, dim, cx, cz):
        """按 chunk 坐标精确读一个 chunk（找 tp 落点用，比全扫快）。"""
        d = self.dimensions().get(dim)
        if not d:
            return None
        path = os.path.join(d, f"r.{cx >> 5}.{cz >> 5}.mca")
        if not os.path.isfile(path):
            return None
        try:
            reg = region.RegionFile(path)
        except Exception:                                # noqa: BLE001
            return None
        idx = (cx & 31) + (cz & 31) * 32
        entry = reg.entries[idx]
        if not entry.present:
            return None
        try:
            _, payload = nbt.parse(reg.read_nbt_bytes(entry))
            return normalize_chunk(payload)
        except Exception:                                # noqa: BLE001
            return None

    def surface_y(self, dim, x, z):
        """世界坐标 (x,z) 最高的非空气方块 y，读不到就返回 None。"""
        cx, cz = x >> 4, z >> 4
        chunk = self.chunk_at(dim, cx, cz)
        if not chunk:
            return None
        got = blocks.top_block(chunk, x & 15, z & 15)
        return got[0] if got else None
