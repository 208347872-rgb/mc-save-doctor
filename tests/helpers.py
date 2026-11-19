"""造测试用的假存档（真 NBT、真 region 格式），不依赖任何真实世界。"""
from __future__ import annotations

import gzip
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

from mcsavedoctor import blocks, nbt  # noqa: E402


def make_level(path, name="测试世界", spawn=(-560, 64, 16), version="1.20.4",
               allow_commands=True, last_played=1_700_000_000_000):
    payload = {"Data": {
        "LevelName": name,
        "Version": {"Name": version, "Id": 3953},
        "DataVersion": 3953,
        "spawn": {"pos": nbt.IntArray(list(spawn)), "dimension": "minecraft:overworld"},
        "allowCommands": nbt.Byte(1 if allow_commands else 0),
        "GameType": 0,
        "LastPlayed": nbt.Long(last_played),
        "DayTime": nbt.Long(6000),
    }}
    nbt.save(path, "", payload)


def make_legacy_level(path, name="老世界", spawn=(10, 70, 20)):
    """1.16 那种平铺的 level.dat（出生点用 SpawnX/Y/Z）。"""
    payload = {"Data": {
        "LevelName": name,
        "Version": {"Name": "1.16.5", "Id": 2586},
        "SpawnX": int(spawn[0]),
        "SpawnY": int(spawn[1]),
        "SpawnZ": int(spawn[2]),
        "allowCommands": nbt.Byte(0),
        "GameType": 0,
    }}
    nbt.save(path, "", payload)


def make_player(path, pos=(100.5, 70.0, 200.5), dim="minecraft:overworld",
                health=20.0, death=None, bed=None, items=2):
    root = {
        "Pos": [float(pos[0]), float(pos[1]), float(pos[2])],
        "Dimension": dim,
        "Health": float(health),
        "foodLevel": 20,
        "XpLevel": 7,
        "playerGameType": 0,
        "Inventory": [
            {"id": "minecraft:diamond_pickaxe", "Count": nbt.Byte(1), "Slot": nbt.Byte(0)}
            for _ in range(items)
        ],
    }
    if death:
        root["LastDeathLocation"] = {
            "dimension": dim,
            "pos": nbt.IntArray([int(death[0]), int(death[1]), int(death[2])]),
        }
    if bed:
        root["SpawnX"], root["SpawnY"], root["SpawnZ"] = (int(v) for v in bed)
    nbt.save(path, "Player", root)


def chunk_payload(cx, cz, inhabited=0, blocks_map=None, y_section=4, entities=()):
    """造一个 1.18+ 格式的 chunk：一块地面 + 可选方块实体。"""
    blocks_map = dict(blocks_map or {(x, 0, z): "minecraft:stone"
                                     for x in range(16) for z in range(16)})
    sec = blocks.pack_section(blocks_map, y_index=y_section)
    sec["block_states"]["data"] = nbt.LongArray(sec["block_states"].get("data") or [])
    return {
        "xPos": cx, "zPos": cz, "yPos": y_section - 4,
        "InhabitedTime": nbt.Long(inhabited),
        "Status": "minecraft:full",
        "sections": [sec, {"Y": 5, "block_states": {"palette": ["minecraft:air"]}}],
        "block_entities": [
            {"id": "minecraft:chest", "x": int(x), "y": int(y), "z": int(z)}
            for (x, y, z) in entities
        ],
        "structures": {"starts": {}},
    }


def write_region(path, chunks):
    """chunks: [(cx, cz, payload dict)]，按真 region 格式落盘。

    文件路径决定 region 坐标（r.<rx>.<rz>.mca），chunk 必须落在这个 region 范围内。
    """
    base = os.path.basename(path)
    try:
        rx, rz = int(base.split(".")[1]), int(base.split(".")[2])
    except (IndexError, ValueError):
        rx = rz = 0
    header = bytearray(8192)
    body = bytearray()
    next_sector = 2
    for cx, cz, payload in chunks:
        if not (rx * 32 <= cx < (rx + 1) * 32 and rz * 32 <= cz < (rz + 1) * 32):
            raise ValueError(f"chunk ({cx},{cz}) 不属于 {base}")
        blob = b"\x01" + nbt.dumps("", payload, compress=True)   # 1 = gzip
        total = 4 + len(blob)
        count = (total + 4095) // 4096
        idx = (cx - rx * 32) + (cz - rz * 32) * 32
        loc = next_sector.to_bytes(3, "big") + bytes([count])
        header[idx * 4:idx * 4 + 4] = loc
        header[4096 + idx * 4:4096 + idx * 4 + 4] = (1_700_000_000).to_bytes(4, "big")
        body += struct.pack(">I", len(blob)) + blob
        body += b"\x00" * (count * 4096 - total)
        next_sector += count
    with open(path, "wb") as f:
        f.write(bytes(header))
        f.write(bytes(body))
    return path


def write_region_dir(region_dir, chunks):
    """按 chunk 坐标自动分到各自的 r.rx.rz.mca。"""
    os.makedirs(region_dir, exist_ok=True)
    groups = {}
    for cx, cz, payload in chunks:
        groups.setdefault((cx >> 5, cz >> 5), []).append((cx, cz, payload))
    paths = []
    for (rx, rz), items in sorted(groups.items()):
        paths.append(write_region(os.path.join(region_dir, f"r.{rx}.{rz}.mca"), items))
    return paths


def region_file_for(region_dir, cx, cz):
    return os.path.join(region_dir, f"r.{cx >> 5}.{cz >> 5}.mca")


def make_modern_world(root, chunks=None, uuid="11111111-2222-3333-4444-555555555555",
                      player_pos=(1247.5, 65.0, 1269.5), death=None, bed=None,
                      name="测试世界"):
    """1.18+ 布局：dimensions/minecraft/overworld/region + players/data/"""
    os.makedirs(os.path.join(root, "dimensions", "minecraft", "overworld", "region"), exist_ok=True)
    os.makedirs(os.path.join(root, "players", "data"), exist_ok=True)
    make_level(os.path.join(root, "level.dat"), name=name)
    make_player(os.path.join(root, "players", "data", uuid + ".dat"),
                pos=player_pos, death=death, bed=bed)
    chunks = chunks or [
        (1, 1, chunk_payload(1, 1, inhabited=500)),
        (78, 79, chunk_payload(78, 79, inhabited=120_000,
                               entities=[(1250, 69, 1270), (1260, 69, 1280)])),
        (2, 2, chunk_payload(2, 2, inhabited=900)),
    ]
    write_region_dir(os.path.join(root, "dimensions", "minecraft", "overworld", "region"), chunks)
    return root


def make_legacy_world(root, uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"):
    """1.16 布局：region/ + playerdata/ + DIM-1/"""
    os.makedirs(os.path.join(root, "region"), exist_ok=True)
    os.makedirs(os.path.join(root, "DIM-1", "region"), exist_ok=True)
    os.makedirs(os.path.join(root, "playerdata"), exist_ok=True)
    make_legacy_level(os.path.join(root, "level.dat"))
    make_player(os.path.join(root, "playerdata", uuid + ".dat"), pos=(10.0, 70.0, 20.0))
    write_region_dir(os.path.join(root, "region"),
                     [(0, 0, chunk_payload(0, 0, inhabited=60_000))])
    write_region_dir(os.path.join(root, "DIM-1", "region"),
                     [(0, 0, chunk_payload(0, 0, inhabited=1000))])
    return root


def gzip_chunk_only(payload):
    return gzip.compress(nbt.dumps("", payload, compress=False))
