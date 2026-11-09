@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
python "%~dp0publish.py" %*
if errorlevel 1 (
  echo.
  echo 发布未完成，按任意键关闭窗口。
  pause >nul
)
endlocal
