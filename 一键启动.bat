@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo   磁盘调度仿真 · 一键部署
echo   ────────────────────────────────────────

rem 找 Python：优先 py 启动器，其次 python
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo   ！没有找到 Python。请安装 Python 3.9+ 后重试：
  echo     https://www.python.org/downloads/
  echo   安装时记得勾选 "Add Python to PATH"。
  echo.
  pause
  exit /b 1
)

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" 2>nul
if errorlevel 1 (
  echo   ！Python 版本过低，需要 3.9 或更高。
  %PY% --version
  pause
  exit /b 1
)

%PY% deploy.py %*
if errorlevel 1 (
  echo.
  echo   启动失败，请把上面的报错发给维护者。
  pause
)
endlocal
