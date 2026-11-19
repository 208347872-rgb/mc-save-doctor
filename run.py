#!/usr/bin/env python3
"""不装包直接跑：

    python run.py find "C:/Users/你/AppData/Roaming/.minecraft/saves/我的世界"
    python run.py report "…/saves/我的世界" -o 报告.html
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from mcsavedoctor.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
