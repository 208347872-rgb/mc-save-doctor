"""把体检结果写成一份 HTML 报告（图片内嵌 base64，单文件、断网也能看）。"""
from __future__ import annotations

import base64
import html
import time

from . import survey

CSS = """
body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#14161a;color:#e6e6e6;margin:0;padding:24px;}
h1{font-size:22px;margin:0 0 4px} h2{font-size:16px;margin:28px 0 8px;color:#8ec07c}
.muted{color:#8a8f98;font-size:13px}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:6px}
th,td{border-bottom:1px solid #2a2e35;padding:6px 8px;text-align:left;vertical-align:top}
th{color:#aab0b8;font-weight:600}
code{background:#1f232a;padding:1px 5px;border-radius:4px;font-size:12.5px}
.tp{color:#8ec07c}
.err{color:#fb4934}.warn{color:#fabd2f}.ok{color:#8ec07c}
img{max-width:100%;image-rendering:pixelated;border:1px solid #2a2e35;margin-top:8px}
.card{background:#191c21;border:1px solid #23272e;border-radius:8px;padding:14px 16px;margin-top:10px}
"""


def _h(text):
    return html.escape(str(text)) if text is not None else ""


def _tp(x, y, z):
    return f"/tp {x} {y} {z}"


def build(world, dims_stats, players, issues, stats, map_png=None, map_note=""):
    """dims_stats: {维度: (chunks, errors)}"""
    sv = survey
    when = time.strftime("%Y-%m-%d %H:%M:%S")
    parts = [f"<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
             f"<title>{_h(world.name)} · 存档体检报告</title><style>{CSS}</style><body>"]
    parts.append(f"<h1>{_h(world.name)}</h1>")
    parts.append(f"<div class='muted'>报告生成于 {when} · <code>{_h(world.path)}</code></div>")

    # ---- 基本信息
    spawn = world.spawn
    ver = world.version
    parts.append("<div class='card'><h2 style='margin-top:0'>世界概况</h2><table>")
    rows = [
        ("版本", ver or "未知"),
        ("出生点", f"{spawn} · <code class='tp'>{_tp(*spawn)}</code>" if spawn else "读不到"),
        ("作弊/命令", "开着（能直接用 /tp）" if world.allow_commands else "关着（要先去 设置→对局域网开放→允许作弊）"),
        ("已扫描 chunk", f"{stats.get('chunks', 0)} 个，读不出来 {stats.get('chunk_errors', 0)} 个"),
        ("玩家存档", f"{stats.get('players', 0)} 个"),
    ]
    for k, v in rows:
        parts.append(f"<tr><th style='width:120px'>{k}</th><td>{v}</td></tr>")
    parts.append("</table></div>")

    # ---- 玩家
    if players:
        parts.append("<h2>玩家</h2><table><tr><th>UUID</th><th>最后位置</th><th>维度</th><th>血</th><th>上次死亡点</th><th>床/重生点</th></tr>")
        for p in players:
            if p.error:
                parts.append(f"<tr><td><code>{_h(p.uuid[:8])}</code></td><td colspan='5' class='err'>读不出来：{_h(p.error)}</td></tr>")
                continue
            pos = "读不到"
            if p.pos:
                x, y, z = (round(v, 1) for v in p.pos)
                pos = f"{x:.0f} {y:.0f} {z:.0f} <code class='tp'>{_tp(int(x), int(y) + 1, int(z))}</code>"
            death = ""
            if p.last_death:
                death = (f"{p.last_death} <code class='tp'>"
                         f"{_tp(p.last_death[0], p.last_death[1] + 1, p.last_death[2])}</code>")
            bed = f"{p.spawn}" if p.spawn else "<span class='warn'>没睡过床（死了回世界出生点）</span>"
            parts.append(f"<tr><td><code>{_h(p.uuid[:8])}</code></td><td>{pos}</td>"
                         f"<td>{_h(p.dimension or '')}</td><td>{_h(p.health)}</td>"
                         f"<td>{death or '没死过'}</td><td>{bed}</td></tr>")
        parts.append("</table>")

    # ---- 热区
    parts.append("<h2>待得最久的地方（大概率就是家）</h2>")
    parts.append("<div class='muted'>按 chunk 的 InhabitedTime 排：玩家在一个 chunk 里待了多久。"
                 "相邻 chunk 会并成一个区域，停留时间是加总的。</div>")
    for dim, (chunks, _errs) in dims_stats.items():
        zs = sv.zones(chunks, limit=5)
        if not zs:
            continue
        parts.append(f"<h2 style='font-size:14px;color:#aab0b8'>{_h(dim)}</h2>")
        parts.append("<table><tr><th>#</th><th>中心坐标</th><th>停留时长</th><th>chunk 数</th><th>玩家方块</th><th>传送</th></tr>")
        for i, z in enumerate(zs, 1):
            top_y = world.surface_y(dim, z.x, z.z)
            ty = (top_y + 2) if top_y is not None else 64
            ents = "、".join(f"{k}×{v}" for k, v in sorted(z.entities.items(), key=lambda kv: -kv[1])[:4]) or "—"
            parts.append(
                f"<tr><td>{i}</td><td>{z.x} {ty} {z.z}</td><td>{sv.human_time(z.inhabited)}</td>"
                f"<td>{z.chunks}</td><td>{_h(ents)}</td>"
                f"<td><code class='tp'>{_tp(z.x, ty, z.z)}</code></td></tr>")
        parts.append("</table>")

    # ---- 地图
    if map_png:
        b64 = base64.b64encode(map_png).decode("ascii")
        parts.append("<h2>俯视图</h2>")
        if map_note:
            parts.append(f"<div class='muted'>{_h(map_note)}</div>")
        parts.append(f"<img alt='世界俯视图' src='data:image/png;base64,{b64}'>")

    # ---- 体检结果
    parts.append("<h2>体检结果</h2>")
    if not issues:
        parts.append("<div class='ok'>没发现问题。</div>")
    else:
        parts.append("<table><tr><th>级别</th><th>问题</th><th>位置</th><th>能不能自动修</th></tr>")
        for i in issues:
            cls = {"error": "err", "warn": "warn", "info": "muted"}.get(i.severity, "")
            fix = "能（--apply）" if i.fixable else "—"
            parts.append(f"<tr><td class='{cls}'>{i.severity}</td><td>{_h(i.detail)}</td>"
                         f"<td><code>{_h(i.code)}</code></td><td>{fix}</td></tr>")
        parts.append("</table>")
        if any(i.fixable for i in issues):
            parts.append("<div class='muted'>修复命令：<code>mcsavedoctor repair &lt;世界目录&gt; --apply</code>"
                         "（会先把动到的文件备份到世界旁边的 mc-save-doctor-backup-时间戳 目录）</div>")

    parts.append("<div class='muted' style='margin-top:28px'>mc-save-doctor · 坐标是反推出来的，"
                 "到那片区域自己看一眼再挖。</div></body></html>")
    return "".join(parts)
