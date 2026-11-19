"""mc-save-doctor —— Minecraft 存档体检工具。

    from mcsavedoctor import World, survey

    w = World("C:/Users/me/AppData/Roaming/.minecraft/saves/我的世界")
    print(w.name, w.spawn, w.allow_commands)
    for dim in w.dimensions():
        chunks, errors = survey.scan(w, dim)
        for zone in survey.zones(chunks, limit=3):
            print(dim, zone.x, zone.z, survey.human_time(zone.inhabited))
"""
from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["World", "WorldError", "__version__", "blocks", "nbt", "region",
           "render", "repair", "report", "survey"]

from .world import World, WorldError      # noqa: E402
from . import blocks, nbt, region, render, repair, report, survey  # noqa: E402,F401
