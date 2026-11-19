"""存档体检 + 修复。

原则：默认只诊断，一个字节都不改；要改必须显式 --apply，
而且改之前把动到的文件整份复制到旁边的备份目录里。
"""
from __future__ import annotations

import glob
import os
import shutil
import time
from dataclasses import dataclass, field

from . import blocks, nbt, region, world as world_mod

SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}


@dataclass
class Issue:
    severity: str          # error / warn / info
    code: str
    path: str
    detail: str
    fixable: bool = False
    extra: dict = field(default_factory=dict)

    def as_dict(self):
        return {"severity": self.severity, "code": self.code, "path": self.path,
                "detail": self.detail, "fixable": self.fixable,
                "extra": {k: str(v) for k, v in self.extra.items()}}


def _stamp():
    return time.strftime("%Y%m%d-%H%M%S")


def diagnose(world, scan_chunks=True, max_chunks=200_000):
    """返回 (issues, 统计信息)。"""
    issues = []
    stats = {"regions": 0, "chunks": 0, "chunk_errors": 0, "players": 0}

    # ---- level.dat
    if not os.path.isfile(world.level_path):
        if os.path.isfile(world.level_old_path):
            issues.append(Issue("error", "level_missing", world.level_path,
                                "level.dat 不存在，但旁边有 level.dat_old（上一次自动备份），可以从它恢复",
                                fixable=True))
        else:
            issues.append(Issue("error", "level_missing", world.level_path,
                                "level.dat 和 level.dat_old 都不存在，这个世界已经没了存档信息"))
    elif world.level_error:
        old_ok = False
        if os.path.isfile(world.level_old_path):
            try:
                nbt.load_payload(world.level_old_path)
                old_ok = True
            except Exception:                              # noqa: BLE001
                old_ok = False
        issues.append(Issue(
            "error", "level_unreadable", world.level_path,
            world.level_error + ("（level.dat_old 是好的，可以直接用它恢复）" if old_ok
                                 else "（level.dat_old 也读不出来，只能找备份了）"),
            fixable=old_ok))
    elif os.path.isfile(world.level_old_path):
        try:
            nbt.load_payload(world.level_old_path)
        except Exception as exc:                           # noqa: BLE001
            issues.append(Issue("warn", "level_old_bad", world.level_old_path,
                                f"level.dat_old 读不出来（不影响开游戏，但下次自动备份就用不上它了）：{exc}"))

    # ---- 玩家数据
    for f in world.player_files():
        stats["players"] += 1
        try:
            nbt.load_payload(f)
        except Exception as exc:                           # noqa: BLE001
            issues.append(Issue("error", "player_unreadable", f,
                                f"玩家数据坏了，游戏里会变成新玩家（背包没了）：{exc}",
                                fixable=True))

    # ---- region
    dims = world.dimensions()
    if not dims:
        issues.append(Issue("error", "no_regions", world.path,
                            "没找到任何 region 目录，这个目录可能不是世界存档"))
    legacy_warned = False
    for dim, rdir in dims.items():
        for path in sorted(glob.glob(os.path.join(rdir, "r.*.*.mca"))):
            stats["regions"] += 1
            try:
                reg = region.RegionFile(path)
            except Exception as exc:                       # noqa: BLE001
                issues.append(Issue("error", "region_unreadable", path, f"打不开：{exc}"))
                continue
            for detail in reg.header_issues():
                issues.append(Issue("warn", "region_header", path, detail))
            if os.path.getsize(path) % region.SECTOR:
                issues.append(Issue("warn", "region_truncated", path,
                                    "文件长度不是 4096 的整数倍，末尾可能被截断了"))
            if not scan_chunks:
                continue
            for entry in reg.chunks()[:max_chunks]:
                stats["chunks"] += 1
                try:
                    raw = reg.read_nbt_bytes(entry)
                    _, payload = nbt.parse(raw)
                    if not isinstance(payload, dict):
                        raise nbt.NbtError("chunk 根不是 compound")
                    chunk = world_mod.normalize_chunk(payload)
                    if not legacy_warned and blocks.has_legacy_blocks(chunk):
                        legacy_warned = True
                        issues.append(Issue(
                            "warn", "legacy_blocks", path,
                            "这是 1.12 及以前的存档：方块存在数字 ID 里，"
                            "「找方块/画地图」会降级，但「找家（停留时间）」照常可用"))
                except Exception as exc:                   # noqa: BLE001
                    stats["chunk_errors"] += 1
                    issues.append(Issue(
                        "error", "chunk_unreadable", path,
                        f"chunk ({entry.cx},{entry.cz}) 读不出来：{exc}",
                        fixable=True,
                        extra={"region": path, "index": entry.index, "cx": entry.cx, "cz": entry.cz}))

    issues.sort(key=lambda i: (SEVERITY_ORDER.get(i.severity, 9), i.code))
    return issues, stats


class Backup:
    """把要动的文件先整份复制到 <世界上级目录>/mc-save-doctor-backup-<时间>/ 下。"""

    def __init__(self, world):
        self.world = world
        self.dir = os.path.join(os.path.dirname(world.path), "mc-save-doctor-backup-" + _stamp())
        self.copied = []

    def add(self, path):
        if not os.path.exists(path):
            return
        rel = os.path.relpath(path, self.world.path)
        if rel.startswith(".."):
            rel = os.path.basename(path)
        dest = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if not os.path.exists(dest):
            shutil.copy2(path, dest)
            self.copied.append(dest)


def apply_issues(world, issues, dry_run=True):
    """返回 (log 行列表, 备份目录)。

    dry_run=True 时只说要干什么，不碰文件。
    """
    log = []
    todo = [i for i in issues if i.fixable]
    if not todo:
        return ["没有可自动修的问题"], None
    if dry_run:
        log.append("[演练模式] 以下动作在加 --apply 后才会真正执行：")
        for i in todo:
            log.append(f"  · {_describe(i)}")
        return log, None

    backup = Backup(world)
    for i in todo:
        try:
            if i.code in ("level_missing", "level_unreadable"):
                backup.add(i.path)
                if os.path.isfile(world.level_old_path):
                    backup.add(world.level_old_path)
                    shutil.copyfile(world.level_old_path, world.level_path)
                    log.append(f"已用 level.dat_old 恢复 level.dat（原文件已备份）")
                else:
                    log.append("没有 level.dat_old，跳过")
            elif i.code == "player_unreadable":
                backup.add(i.path)
                broken = i.path + ".broken-" + _stamp()
                os.replace(i.path, broken)
                log.append(f"已隔离坏掉的玩家数据：{os.path.basename(broken)}（原件在备份目录里）")
            elif i.code == "chunk_unreadable":
                rpath = i.extra.get("region")
                idx = i.extra.get("index")
                if not rpath or idx is None:
                    log.append("chunk 信息不全，跳过")
                    continue
                backup.add(rpath)
                reg = region.RegionFile(rpath)
                reg.isolate(reg.entries[int(idx)])
                log.append(f"已隔离坏 chunk ({i.extra.get('cx')},{i.extra.get('cz')})"
                           f"：从 {os.path.basename(rpath)} 的头部指针里摘掉，文件本身没删")
            else:
                log.append(f"没实现这种修复：{i.code}")
        except Exception as exc:                           # noqa: BLE001
            log.append(f"修复失败（{i.code}）：{exc}")
    if backup.copied:
        log.append(f"备份目录：{backup.dir}")
    return log, (backup.dir if backup.copied else None)


def _describe(issue):
    if issue.code in ("level_missing", "level_unreadable"):
        return "用 level.dat_old 覆盖恢复 level.dat"
    if issue.code == "player_unreadable":
        return f"把坏掉的玩家数据改名隔离：{os.path.basename(issue.path)}"
    if issue.code == "chunk_unreadable":
        return (f"隔离坏 chunk ({issue.extra.get('cx')},{issue.extra.get('cz')})"
                f"：{os.path.basename(issue.extra.get('region', ''))}")
    return issue.detail
