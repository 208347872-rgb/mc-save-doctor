"""mc-save-doctor 命令行入口。

    mcsavedoctor info    <世界目录>            这个存档是谁、什么版本、出生点在哪
    mcsavedoctor find    <世界目录>            待得最久的地方（= 家），给出 /tp
    mcsavedoctor map     <世界目录>            出一张俯视图 PNG
    mcsavedoctor report  <世界目录>            全部塞进一份 HTML
    mcsavedoctor repair  <世界目录>            体检（默认只诊断，--apply 才动文件）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import __version__
from . import render, repair, report, survey
from .world import World, WorldError


# ------------------------------------------------------------------ 小工具
def _ts(ms):
    if not ms:
        return "未知"
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ms) / 1000))
    except (ValueError, OSError):
        return str(ms)


def _tp(x, y, z):
    return f"/tp {int(x)} {int(y)} {int(z)}"


def _open(path):
    try:
        return World(path)
    except WorldError as exc:
        print(f"打不开：{exc}", file=sys.stderr)
        raise SystemExit(2)


def _scan_all(world, dims=None, quiet=False):
    """扫多个维度，返回 ({维度: (chunks, errors)}, 总错误列表)。"""
    out = {}
    errors = []
    targets = dims or list(world.dimensions())
    for dim in targets:
        if dim not in world.dimensions():
            if not quiet:
                print(f"跳过 {dim}：没有 region 目录", file=sys.stderr)
            continue
        if not quiet:
            print(f"扫描 {dim} ...", file=sys.stderr)
        chunks, errs = survey.scan(world, dim)
        out[dim] = (chunks, errs)
        errors.extend(errs)
    return out, errors


def _world_dict(world):
    return {
        "path": world.path,
        "name": world.name,
        "version": world.version,
        "spawn": list(world.spawn) if world.spawn else None,
        "allow_commands": world.allow_commands,
        "last_played": _ts(world.last_played),
        "dimensions": {k: len([f for f in os.listdir(v) if f.endswith(".mca")])
                       for k, v in world.dimensions().items()},
        "level_error": world.level_error,
    }


def _player_dict(p):
    return {
        "uuid": p.uuid,
        "error": p.error,
        "pos": [round(v, 2) for v in p.pos] if p.pos else None,
        "dimension": p.dimension,
        "health": p.health,
        "xp_level": p.xp_level,
        "spawn": list(p.spawn) if p.spawn else None,
        "last_death": list(p.last_death) if p.last_death else None,
        "last_death_dimension": p.last_death_dim,
        "items": p.items,
    }


# ------------------------------------------------------------------ info
def cmd_info(args):
    w = _open(args.world)
    players = w.players()
    if args.json:
        data = _world_dict(w)
        data["players"] = [_player_dict(p) for p in players]
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print(f"世界      {w.name}")
    print(f"路径      {w.path}")
    print(f"版本      {w.version or '未知'}")
    if w.level_error:
        print(f"警告      {w.level_error}")
    if w.spawn:
        print(f"出生点    {w.spawn}   {_tp(w.spawn[0], w.spawn[1] + 2, w.spawn[2])}")
    print(f"作弊      {'开（可以直接 /tp）' if w.allow_commands else '关'}")
    print(f"最后游玩  {_ts(w.last_played)}")
    dims = w.dimensions()
    print(f"维度      " + ("、".join(f"{k}({len([f for f in os.listdir(v) if f.endswith('.mca')])} 个 region)"
                                     for k, v in dims.items()) or "没有 region 目录"))
    if players:
        print("\n玩家：")
        for p in players:
            head = f"  {p.uuid[:8]}"
            if p.error:
                print(f"{head}  读不出来：{p.error}")
                continue
            pos = ("坐标 " + " ".join(f"{v:.0f}" for v in p.pos)) if p.pos else "坐标读不到"
            bed = f"床 {p.spawn}" if p.spawn else "没睡过床"
            death = f"上次死于 {p.last_death}" if p.last_death else "没死过"
            print(f"{head}  {pos}  [{p.dimension}]  血 {p.health}  等级 {p.xp_level}  {bed}  {death}")
    return 0


# ------------------------------------------------------------------ find
def cmd_find(args):
    w = _open(args.world)
    dims = [args.dim] if args.dim else None
    scanned, errors = _scan_all(w, dims, quiet=args.json)
    result = {"world": _world_dict(w), "dimensions": {}, "errors": errors}

    if not args.json:
        print(f"\n{w.name} · {w.path}")
    for dim, (chunks, errs) in scanned.items():
        zs = survey.zones(chunks, radius=args.radius, limit=args.top)
        entries = []
        for i, z in enumerate(zs, 1):
            top_y = w.surface_y(dim, z.x, z.z)
            ty = (top_y + 2) if top_y is not None else 64
            entries.append({
                "rank": i, "x": z.x, "y": ty, "z": z.z,
                "inhabited_ticks": z.inhabited,
                "inhabited_human": survey.human_time(z.inhabited),
                "chunks": z.chunks,
                "entities": z.entities,
                "samples": z.samples[:20],
                "tp": _tp(z.x, ty, z.z),
            })
        result["dimensions"][dim] = entries
        if args.json:
            continue
        print(f"\n== {dim} ==  扫到 {len(chunks)} 个 chunk"
              + (f"，{len(errs)} 个读不出来" if errs else ""))
        if not entries:
            print("  这个维度没有玩家活动痕迹")
        for e in entries:
            ents = "、".join(f"{k}×{v}" for k, v in
                            sorted(e["entities"].items(), key=lambda kv: -kv[1])[:5]) or "—"
            print(f"  #{e['rank']} 中心 {e['x']:>6} {e['y']:>4} {e['z']:>6}   "
                  f"停留 {e['inhabited_human']}   {e['chunks']} 个 chunk")
            print(f"      玩家方块：{ents}")
            print(f"      {e['tp']}")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print("\n坐标是按停留时间反推的，不是定位器：到那片区域自己看一眼再挖。")
    if w.spawn and any(p.spawn is None for p in w.players() if not p.error):
        print("顺手根治：回家放张床睡一觉，或者 /setworldspawn 把出生点搬到家里。")
    return 0


# ------------------------------------------------------------------ map
def cmd_map(args):
    w = _open(args.world)
    dim = args.dim or "overworld"
    if args.center:
        try:
            cx, cz = (int(v) for v in args.center.replace("，", ",").split(","))
        except ValueError:
            print("--center 要写成 x,z，例如 --center 1247,1269", file=sys.stderr)
            return 2
    else:
        players = [p for p in w.players() if p.pos and not p.error]
        if players and players[0].pos:
            cx, cz = int(players[0].pos[0]), int(players[0].pos[2])
        elif w.spawn:
            cx, cz = w.spawn[0], w.spawn[2]
        else:
            cx = cz = 0
    markers = []
    for p in w.players():
        if p.pos and p.dimension in (dim, "minecraft:" + dim):
            markers.append((int(p.pos[0]), int(p.pos[2]), (255, 60, 60)))
        if p.last_death and (p.last_death_dim in (None, dim, "minecraft:" + dim)):
            markers.append((p.last_death[0], p.last_death[2], (255, 220, 60)))
    box = render.auto_box(w, dim, cx, cz, size=args.size)
    png, wpx, hpx = render.render(w, dim, *box, scale=args.scale, markers=markers)
    out = args.out or f"{os.path.basename(w.path)}-{dim}-{cx}_{cz}.png"
    with open(out, "wb") as f:
        f.write(png)
    print(f"已写出 {out}  ({wpx}x{hpx} 像素)")
    print(f"覆盖范围 x {box[0]}..{box[1]}  z {box[2]}..{box[3]}  （红=玩家，黄=上次死亡点）")
    return 0


# ------------------------------------------------------------------ report
def cmd_report(args):
    w = _open(args.world)
    scanned, errors = _scan_all(w, [args.dim] if args.dim else None, quiet=False)
    players = w.players()
    issues, stats = repair.diagnose(w)
    stats["players"] = len(players)

    dim = args.dim or "overworld"
    map_png = None
    note = ""
    try:
        players_pos = [p for p in players if p.pos and not p.error]
        if players_pos:
            cx, cz = int(players_pos[0].pos[0]), int(players_pos[0].pos[2])
            note = f"以玩家最后位置 {cx},{cz} 为中心，左右各 {args.size // 2} 格"
        elif w.spawn:
            cx, cz = w.spawn[0], w.spawn[2]
            note = f"以出生点 {cx},{cz} 为中心"
        else:
            cx = cz = 0
        markers = [(int(p.pos[0]), int(p.pos[2]), (255, 60, 60))
                   for p in players if p.pos and p.dimension in (dim, "minecraft:" + dim)]
        markers += [(p.last_death[0], p.last_death[2], (255, 220, 60))
                    for p in players if p.last_death and p.last_death_dim in (None, dim, "minecraft:" + dim)]
        box = render.auto_box(w, dim, cx, cz, size=args.size)
        map_png = render.render(w, dim, *box, scale=max(1, args.scale - 1), markers=markers)[0]
    except Exception as exc:                              # noqa: BLE001 —— 地图失败不该拖垮报告
        note = f"没能画图：{exc}"

    html_text = report.build(w, scanned, players, issues, stats, map_png=map_png, map_note=note)
    out = args.out or f"{os.path.basename(w.path)}-存档体检.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html_text)
    print(f"报告已写出：{out}")
    print(f"问题 {len(issues)} 条（能自动修 {sum(1 for i in issues if i.fixable)} 条）")
    if errors:
        print(f"读不出来的 chunk：{len(errors)} 个（详情见报告）")
    return 0


# ------------------------------------------------------------------ repair
def cmd_repair(args):
    w = _open(args.world)
    issues, stats = repair.diagnose(w, scan_chunks=not args.fast)
    if args.json:
        print(json.dumps({"world": _world_dict(w), "stats": stats,
                          "issues": [i.as_dict() for i in issues]},
                         ensure_ascii=False, indent=2))
    else:
        print(f"{w.name}  ({w.path})")
        print(f"扫描 {stats['regions']} 个 region、{stats['chunks']} 个 chunk、"
              f"{stats['players']} 个玩家存档")
        if not issues:
            print("没发现问题。")
        for i in issues:
            flag = {"error": "错误", "warn": "警告", "info": "提示"}.get(i.severity, i.severity)
            print(f"  [{flag}] {i.detail}")
            print(f"         {i.path}")
    if not args.apply:
        fixable = [i for i in issues if i.fixable]
        if fixable:
            print(f"\n有 {len(fixable)} 条能自动修。加 --apply 才会动手（会先备份）：")
            log, _ = repair.apply_issues(w, fixable, dry_run=True)
            for line in log:
                print("  " + line)
        return 0

    log, backup_dir = repair.apply_issues(w, issues, dry_run=False)
    print()
    for line in log:
        print("  " + line)
    # 修完再验一遍
    issues2, _ = repair.diagnose(w, scan_chunks=False)
    remain = [i for i in issues2 if i.severity == "error"]
    print(f"\n复检：{len(remain)} 个错误剩下")
    for i in remain:
        print(f"  [错误] {i.detail}")
    return 0


# ------------------------------------------------------------------ main
def build_parser():
    p = argparse.ArgumentParser(
        prog="mcsavedoctor",
        description="Minecraft 存档体检：找回你家在哪、上次死在哪，顺手修坏档。",
    )
    p.add_argument("--version", action="version", version=f"mc-save-doctor {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, world_help="世界目录（.minecraft/saves/xxx），也可以给 saves 目录"):
        sp.add_argument("world", help=world_help)

    sp = sub.add_parser("info", help="世界概况：版本、出生点、玩家、作弊开关")
    common(sp)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("find", help="找家：按停留时间排出待得最久的地方，给 /tp")
    common(sp)
    sp.add_argument("--dim", help="只扫一个维度（overworld / the_nether / the_end）")
    sp.add_argument("--top", type=int, default=5, help="每个维度列几个热区（默认 5）")
    sp.add_argument("--radius", type=int, default=8, help="合并热区的半径，单位 chunk（默认 8 = 128 格）")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_find)

    sp = sub.add_parser("map", help="画俯视图 PNG")
    common(sp)
    sp.add_argument("--dim", default="overworld")
    sp.add_argument("--center", help="中心坐标 x,z（默认玩家最后位置）")
    sp.add_argument("--size", type=int, default=256, help="边长多少格（默认 256）")
    sp.add_argument("--scale", type=int, default=2, help="每格几个像素（默认 2）")
    sp.add_argument("-o", "--out", help="输出 PNG 路径")
    sp.set_defaults(func=cmd_map)

    sp = sub.add_parser("report", help="出一份 HTML 报告（概况 + 热区 + 地图 + 体检）")
    common(sp)
    sp.add_argument("--dim", default="overworld", help="画哪个维度的地图")
    sp.add_argument("--size", type=int, default=256)
    sp.add_argument("--scale", type=int, default=2)
    sp.add_argument("-o", "--out", help="输出 HTML 路径")
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("repair", help="体检/修坏档（默认只诊断，--apply 才动文件）")
    common(sp)
    sp.add_argument("--apply", action="store_true", help="真的动手修（会先备份到旁边目录）")
    sp.add_argument("--fast", action="store_true", help="只查头部，不逐个解 chunk")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_repair)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
