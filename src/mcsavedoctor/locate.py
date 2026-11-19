"""自动找存档：把各启动器、各版本隔离目录里的世界都翻出来。

顺序：
  1. 官方启动器 %APPDATA%\\.minecraft\\saves
  2. 版本隔离  .minecraft\\versions\\<版本>\\saves      （PCL / HMCL / 官方都这么干）
  3. Prism / MultiMC / HMCL / Modrinth App 的实例目录
  4. 桌面上、文档里那些自己放的 .minecraft
  5. 环境变量 MCSD_SAVES 里手动加的路径（用 ; 或 : 分隔）
"""
from __future__ import annotations

import glob
import os

from . import nbt


class Candidate:
    __slots__ = ("path", "name", "version", "mtime", "size", "source")

    def __init__(self, path, name, version, mtime, size, source):
        self.path = path
        self.name = name
        self.version = version
        self.mtime = mtime
        self.size = size
        self.source = source

    def __repr__(self):
        return f"<Candidate {self.name} {self.path}>"


def _env(*names):
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


def _home():
    return _env("HOME", "USERPROFILE") or os.path.expanduser("~")


def _appdata():
    return _env("APPDATA") or os.path.join(_home(), "AppData", "Roaming")


def _localappdata():
    return _env("LOCALAPPDATA") or os.path.join(_home(), "AppData", "Local")


def saves_dirs():
    """返回 [(来源说明, saves 目录)]，只留存在的。"""
    home, appdata, local = _home(), _appdata(), _localappdata()
    patterns = [
        ("官方启动器", os.path.join(appdata, ".minecraft", "saves")),
        ("版本隔离", os.path.join(appdata, ".minecraft", "versions", "*", "saves")),
        ("版本隔离", os.path.join(home, ".minecraft", "versions", "*", "saves")),
        ("官方启动器", os.path.join(home, ".minecraft", "saves")),
        ("官方启动器", os.path.join(home, "Library", "Application Support", "minecraft", "saves")),
        ("Prism 启动器", os.path.join(appdata, "PrismLauncher", "instances", "*", ".minecraft", "saves")),
        ("Prism 启动器", os.path.join(home, "Library", "Application Support", "PrismLauncher",
                                     "instances", "*", ".minecraft", "saves")),
        ("Prism 启动器", os.path.join(home, ".local", "share", "PrismLauncher",
                                     "instances", "*", ".minecraft", "saves")),
        ("MultiMC", os.path.join(appdata, "MultiMC", "instances", "*", ".minecraft", "saves")),
        ("HMCL", os.path.join(appdata, "HMCL", ".minecraft", "saves")),
        ("HMCL", os.path.join(home, "HMCL", ".minecraft", "saves")),
        ("Modrinth App", os.path.join(appdata, "com.modrinth.theseus", "profiles", "*", "saves")),
        ("Modrinth App", os.path.join(local, "com.modrinth.theseus", "profiles", "*", "saves")),
    ]
    # 桌面上/文档里自己放的一份 .minecraft（PCL 常见）
    for base in (os.path.join(home, "Desktop"), os.path.join(home, "Documents"),
                 os.path.join(home, "Downloads"), home):
        patterns.append(("自己放的 .minecraft", os.path.join(base, "*", ".minecraft", "saves")))
        patterns.append(("自己放的 .minecraft", os.path.join(base, ".minecraft", "saves")))

    extra = os.environ.get("MCSD_SAVES")
    if extra:
        # Windows 用分号分隔，类 Unix 用冒号；不拿冒号切 Windows 的 C:
        for p in extra.replace(";", os.pathsep).split(os.pathsep):
            p = p.strip().strip('"')
            if p:
                patterns.append(("手动指定", p))

    out = []
    seen = set()
    for label, pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            key = os.path.normcase(os.path.abspath(path))
            if key in seen or not os.path.isdir(path):
                continue
            seen.add(key)
            out.append((label, path))
    return out


def _world_name(level_path, fallback):
    try:
        data = nbt.unwrap_data(nbt.load_payload(level_path))
        name = data.get("LevelName")
        ver = data.get("Version")
        version = ver.get("Name") if isinstance(ver, dict) else None
        return (name or fallback), version
    except Exception:                                     # noqa: BLE001 —— 名字读不出不影响列出来
        return fallback, None


def _dir_size(path, budget=20000):
    total = 0
    count = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
            count += 1
            if count > budget:
                return total
    return total


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.0f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def find_worlds(compute_size=True):
    """所有能找到的世界，按最后游玩时间从新到旧。"""
    found = []
    seen = set()
    for source, saves in saves_dirs():
        try:
            children = sorted(os.listdir(saves))
        except OSError:
            continue
        for child in children:
            path = os.path.join(saves, child)
            level = os.path.join(path, "level.dat")
            if not os.path.isfile(level):
                continue
            key = os.path.normcase(os.path.abspath(path))
            if key in seen:
                continue
            seen.add(key)
            name, version = _world_name(level, child)
            try:
                mtime = os.path.getmtime(level)
            except OSError:
                mtime = 0
            size = _dir_size(path) if compute_size else 0
            found.append(Candidate(path, name, version, mtime, size, source))
    found.sort(key=lambda c: c.mtime, reverse=True)
    return found


def describe(cands):
    """给人看的编号列表。"""
    lines = []
    for i, c in enumerate(cands, 1):
        import time
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(c.mtime)) if c.mtime else "未知"
        lines.append(f"  {i}) {c.name}    {human_size(c.size)}   最后玩 {when}    "
                     f"版本 {c.version or '未知'}   [{c.source}]")
        lines.append(f"     {c.path}")
    return "\n".join(lines)
