@echo off
chcp 936 >nul
cd /d "%~dp0"
echo 装 PyInstaller（只有打包的人需要，用工具的人不需要）...
python -m pip install -q --disable-pip-version-check pyinstaller || goto :err

echo 打包中...（要等两三分钟）
python -m PyInstaller --noconfirm --clean --onefile --console --name mc-save-doctor --paths src packaging\exe_entry.py || goto :err

echo.
echo 好了：dist\mc-save-doctor.exe
echo 双击它 = 自动找存档并出报告；带参数 = 当命令行用（dist\mc-save-doctor.exe list）
pause
exit /b 0

:err
echo.
echo 打包失败，看上面的报错。
pause
exit /b 1
