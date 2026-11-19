@echo off
chcp 936 >nul
setlocal
rem 双击 = 我自己去找存档并出报告；也可以把存档文件夹拖到本文件上。
rem 结果：本文件旁边的「存档体检报告.html」，浏览器打开就能看。

set PYTHONIOENCODING=gbk:replace
set "TARGET=%~1"

echo.
if "%TARGET%"=="" (
  echo 没给文件夹，我自己去找存档...
) else (
  echo 体检这个存档：%TARGET%
)
echo.

if "%TARGET%"=="" (
  python "%~dp0run.py" report -o "%~dp0存档体检报告.html"
) else (
  python "%~dp0run.py" report "%TARGET%" -o "%~dp0存档体检报告.html"
)

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
