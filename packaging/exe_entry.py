"""打包成单文件 exe 时的入口。

双击 → 自动找存档 → 出报告 → 用默认浏览器打开。
带参数 → 原样转给命令行，例如 `mc-save-doctor.exe list`、`mc-save-doctor.exe find 1`。

这样小白不需要装 Python、不需要知道存档路径。
"""
from __future__ import annotations

import os
import sys
import tempfile
import webbrowser

from mcsavedoctor.cli import main


def _base_dir():
    """exe 在哪个目录，报告就写在哪个目录（源码运行时用当前目录）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.getcwd()


def _writable_report_path():
    """优先写在 exe 旁边；那儿不可写（比如放在 Program Files）就退到当前目录、临时目录。"""
    for folder in (_base_dir(), os.getcwd(), tempfile.gettempdir()):
        path = os.path.join(folder, "存档体检报告.html")
        try:
            with open(path, "ab"):
                pass
            return path
        except OSError:
            continue
    return os.path.join(os.getcwd(), "存档体检报告.html")


def run():
    if len(sys.argv) > 1:
        return main(sys.argv[1:])

    out = _writable_report_path()
    print("没给参数，我自己去找存档，出报告……\n", flush=True)
    code = main(["report", "-o", out])
    if code == 0 and os.path.isfile(out):
        print(f"\n报告：{out}")
        try:
            webbrowser.open("file:///" + out.replace("\\", "/"))
        except Exception:                                # noqa: BLE001 —— 打不开浏览器不影响报告
            pass
    if getattr(sys, "frozen", False):
        try:
            input("\n按回车关闭这个窗口……")
        except EOFError:
            pass
    return code


if __name__ == "__main__":
    raise SystemExit(run())
