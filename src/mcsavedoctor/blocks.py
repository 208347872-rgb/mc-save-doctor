"""chunk 方块解码。

支持三种存法：
  1.18+     sections[].block_states.palette / .data   （palette 元素是字符串或 {Name}）
  1.13~1.17 sections[].Palette / .BlockStates          （另外 chunk 外面套一层 Level）
  <=1.12    sections[].Blocks 全局数字 ID              暂不支持，会让上层报「旧格式」
"""
from __future__ import annotations

AIR = frozenset({
    "minecraft:air", "minecraft:cave_air", "minecraft:void_air",
    "air", "cave_air", "void_air",
})
M64 = (1 << 64) - 1


def air(name):
    return name is None or name in AIR


def sections(chunk):
    return chunk.get("sections") or chunk.get("Sections") or []


def _name_of(entry):
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        nm = entry.get("Name")
        if isinstance(nm, str):
            return nm
        # 26.x 部分存档把调色板写成无名 compound：{"": "minecraft:stone"}
        if len(entry) == 1:
            only = next(iter(entry.values()))
            if isinstance(only, str):
                return only
    return None


def palette_and_data(sec):
    """返回 (names, longs) 或者 (None, None)。"""
    bs = sec.get("block_states")
    if isinstance(bs, dict):
        pal = bs.get("palette") or []
        return [_name_of(p) for p in pal], bs.get("data")
    pal = sec.get("Palette") or sec.get("palette") or []
    if pal:
        return [_name_of(p) for p in pal], sec.get("BlockStates") or sec.get("blocks")
    return None, None


def iter_section_blocks(sec):
    """yield (lx, ly, lz, name)，只吐非空气方块。坐标系是 section 内的 0..15。"""
    sy = sec.get("Y", sec.get("y", 0)) or 0
    names, longs = palette_and_data(sec)
    if names is None:            # <=1.12 的 Blocks 数字 ID，未支持
        return
    if not longs:
        nm = names[0] if names else None
        if air(nm):
            return
        for i in range(4096):
            yield i & 15, (i >> 8) & 15, (i >> 4) & 15, nm
        return

    count = len(names)
    bits = max(4, (count - 1).bit_length()) if count > 1 else 4
    per = 64 // bits
    mask = (1 << bits) - 1

    if len(longs) * per >= 4096:
        # 现代（1.16+）：一个 long 里塞 per 个值，不跨 long
        for li, lv in enumerate(longs):
            u = lv & M64
            base = li * per
            if base >= 4096:
                break
            for j in range(per):
                idx = base + j
                if idx >= 4096:
                    break
                i = (u >> (j * bits)) & mask
                if i >= count:
                    continue
                nm = names[i]
                if air(nm):
                    continue
                yield idx & 15, (idx >> 8) & 15, (idx >> 4) & 15, nm
    else:
        # 1.13~1.15：值可以跨 long
        for idx in range(4096):
            start = idx * bits
            li, off = divmod(start, 64)
            if li >= len(longs):
                break
            v = longs[li] & M64
            if off + bits > 64 and li + 1 < len(longs):
                v |= (longs[li + 1] & M64) << 64
            i = (v >> off) & mask
            if i >= count:
                continue
            nm = names[i]
            if air(nm):
                continue
            yield idx & 15, (idx >> 8) & 15, (idx >> 4) & 15, nm


def has_legacy_blocks(chunk):
    """1.12 及以前：方块存在 Blocks 字节数组里，我们读不出名字。"""
    for sec in sections(chunk):
        if sec.get("Blocks") and not palette_and_data(sec)[0]:
            return True
    return False


def top_block(chunk, lx, lz, min_y=-64):
    """某个 (lx,lz) 列最高的非空气方块 -> (y, name) / None。"""
    best = None
    for sec in sections(chunk):
        sy = sec.get("Y", sec.get("y", 0)) or 0
        names, longs = palette_and_data(sec)
        if names is None:
            continue
        if not longs:
            nm = names[0] if names else None
            if air(nm):
                continue
            y = sy * 16 + 15
            if best is None or y > best[0]:
                best = (y, nm)
            continue
        count = len(names)
        bits = max(4, (count - 1).bit_length()) if count > 1 else 4
        per = 64 // bits
        mask = (1 << bits) - 1
        idx = (lx & 15) | ((lz & 15) << 4)
        if len(longs) * per >= 4096:
            li, j = divmod(idx, per)
            if li >= len(longs):
                continue
            v = (longs[li] & M64) >> (j * bits) & mask
        else:
            start = idx * bits
            li, off = divmod(start, 64)
            if li >= len(longs):
                continue
            v = longs[li] & M64
            if off + bits > 64 and li + 1 < len(longs):
                v |= (longs[li + 1] & M64) << 64
            v = (v >> off) & mask
        if v >= count:
            continue
        nm = names[v]
        if air(nm):
            continue
        # 这一列在 section 里的最高非空气 y
        for j in range(15, -1, -1):
            if len(longs) * per >= 4096:
                li2, j2 = divmod(idx | (j << 8), per)
                if li2 >= len(longs):
                    continue
                v2 = (longs[li2] & M64) >> (j2 * bits) & mask
            else:
                start = (idx | (j << 8)) * bits
                li2, off2 = divmod(start, 64)
                if li2 >= len(longs):
                    continue
                v2 = longs[li2] & M64
                if off2 + bits > 64 and li2 + 1 < len(longs):
                    v2 |= (longs[li2 + 1] & M64) << 64
                v2 = (v2 >> off2) & mask
            if v2 < count and not air(names[v2]):
                y = sy * 16 + j
                if best is None or y > best[0]:
                    best = (y, names[v2])
                break
    return best


def pack_section(blocks, y_index=0):
    """给测试用：把 {(x,y,z): 方块名} 打成 palette + data（不跨 long 的新格式）。"""
    names = []
    seen = {}
    for (x, y, z), nm in blocks.items():
        if nm not in seen:
            seen[nm] = len(names)
            names.append(nm)
    if not names:
        return {"Y": y_index, "block_states": {"palette": ["minecraft:air"]}}
    bits = max(4, (len(names) - 1).bit_length())
    per = 64 // bits
    total = (4096 + per - 1) // per
    longs = [0] * total
    for (x, y, z), nm in blocks.items():
        idx = (y << 8) | (z << 4) | x
        li, j = divmod(idx, per)
        longs[li] |= seen[nm] << (j * bits)
    return {"Y": y_index, "block_states": {"palette": names, "data": longs}}
