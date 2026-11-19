@echo off
chcp 936 >nul
setlocal
rem 把世界存档文件夹拖到本文件上，或者双击后粘贴路径回车。
rem 结果：本文件旁边的「存档体检报告.html」，浏览器打开就能看。
rem 说明：这是本机自用的小入口，正式的用法见 README（pip install 后用 mcsavedoctor 命令）。

set PYTHONIOENCODING=gbk:replace
set "TARGET=%~1"
if "%TARGET%"=="" set /p TARGET=把存档文件夹路径粘进来（例如 %APPDATA%\.minecraft\saves\我的世界）:

if "%TARGET%"=="" (
  echo 没给路径，退出。
  pause
  exit /b 1
)

echo.
echo 正在体检：%TARGET%
echo.
python "%~dp0run.py" report "%TARGET%" -o "%~dp0存档体检报告.html"
if errorlevel 1 (
  echo.
  echo 出错了。如果是提示找不到 python，先装 Python 3.9+ 并勾上 Add to PATH。
  pause
  exit /b 1
)

echo.
echo 报告已经生成，浏览器打开这个文件：
echo   %~dp0存档体检报告.html
start "" "%~dp0存档体检报告.html"
pause
