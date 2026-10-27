@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动磁盘调度仿真 Web 界面...
python disksched.py serve
pause
