#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一键部署：本地直跑或 Docker 容器，自动选端口、等健康检查、开浏览器。

    python deploy.py                 # 本地启动（默认）
    python deploy.py --docker        # 构建镜像并以容器启动（后台常驻）
    python deploy.py --stop          # 停止容器
    python deploy.py --port 9000     # 指定端口
    python deploy.py --host 0.0.0.0  # 允许局域网访问
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = "disk-sched"
IMAGE = "disk-sched:1.1"
HEALTH = "/api/health"


def _fix_stdout() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def pick_port(host: str, preferred: int) -> int:
    bind_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    for port in range(preferred, preferred + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((bind_host, port))
                return port
            except OSError:
                continue
    return preferred


def port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_health(port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}{HEALTH}"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.25)
    return False


def have(cmd: str) -> bool:
    try:
        subprocess.run([cmd, "--version"], capture_output=True, timeout=5)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def compose() -> list:
    if have("docker"):
        try:
            out = subprocess.run(["docker", "compose", "version"], capture_output=True, timeout=8)
            if out.returncode == 0:
                return ["docker", "compose"]
        except (OSError, subprocess.SubprocessError):
            pass
    if have("docker-compose"):
        return ["docker-compose"]
    return []


def banner(urls: list, port: int, mode: str, extra: str = "") -> None:
    line = "─" * 58
    print()
    print(line)
    print(f"  磁盘调度仿真 · {mode}")
    for u in urls:
        print(f"  →  {u}")
    print(f"  健康检查  http://127.0.0.1:{port}{HEALTH}")
    if extra:
        print(f"  {extra}")
    print(line)


def run_local(args) -> int:
    host = args.host
    port = pick_port(host, args.port)
    cmd = [sys.executable, os.path.join(ROOT, "disksched.py"), "serve",
           "--host", host, "--port", str(port), "--no-open"]
    print(f"启动本地服务：python disksched.py serve --host {host} --port {port}")
    child = subprocess.Popen(cmd, cwd=ROOT)
    try:
        if not wait_health(port, timeout=25):
            print("！服务启动超时，请检查端口是否被占用或依赖是否完整。")
            child.terminate()
            return 1
        urls = [f"http://127.0.0.1:{port}/"]
        if host in ("0.0.0.0", "::"):
            urls.append(f"http://{lan_ip()}:{port}/   （局域网）")
        banner(urls, port, "本地直跑", "停止：在本窗口按 Ctrl+C")
        if not args.no_open:
            webbrowser.open(urls[0])
        child.wait()
    except KeyboardInterrupt:
        print("\n已停止")
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
    return 0


def docker_daemon_ok() -> bool:
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=15)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def run_docker(args) -> int:
    if not have("docker"):
        print("！未找到 docker，请先安装 Docker Desktop，或去掉 --docker 用本地模式。")
        return 1
    if not docker_daemon_ok():
        print("！Docker 引擎没在跑（Docker Desktop 未启动，或 WSL2 后端未就绪）。")
        print("  处理办法：启动 Docker Desktop，等左下角显示 Engine running，再重跑本命令。")
        print("  如果不想用容器：直接 python deploy.py（或双击 一键启动.bat）。")
        return 1
    comp = compose()
    if not comp:
        print("！未找到 docker compose（v2 或 v1），请升级 Docker Desktop。")
        return 1

    port = args.port
    if port_open("127.0.0.1", port):
        print(f"！端口 {port} 已被占用（可能已经跑着一个实例）。先 python deploy.py --stop")
        return 1

    print("构建镜像并启动容器（首次约 1 分钟）…")
    env = {**os.environ, "DS_PORT": str(port)}
    r = subprocess.run(comp + ["-p", "disk-sched", "up", "-d", "--build"], cwd=ROOT, env=env)
    if r.returncode != 0:
        print("！docker compose 启动失败，输出见上。")
        return r.returncode

    if not wait_health(port, timeout=60):
        print("！容器起来了但健康检查没通过，看日志：docker compose logs --tail=50")
        return 1

    urls = [f"http://127.0.0.1:{port}/", f"http://{lan_ip()}:{port}/   （局域网）"]
    banner(urls, port, "Docker 容器", "停止：python deploy.py --stop")
    if not args.no_open:
        webbrowser.open(urls[0])
    return 0


def stop_docker() -> int:
    comp = compose()
    if not comp:
        print("！未找到 docker compose。")
        return 1
    r = subprocess.run(comp + ["-p", "disk-sched", "down", "--remove-orphans"], cwd=ROOT)
    print("容器已停止。" if r.returncode == 0 else "！停止失败，见上。")
    return r.returncode


def main() -> int:
    _fix_stdout()
    ap = argparse.ArgumentParser(
        prog="deploy",
        description="磁盘调度仿真一键部署（本地直跑 / Docker 容器）",
    )
    ap.add_argument("--docker", action="store_true", help="用 Docker 容器部署")
    ap.add_argument("--local", action="store_true", help="强制本地直跑（默认）")
    ap.add_argument("--stop", action="store_true", help="停止 Docker 容器")
    ap.add_argument("--port", type=int, default=8765, help="端口，默认 8765")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址；0.0.0.0 表示允许局域网")
    ap.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()

    if sys.version_info < (3, 9):
        print(f"！需要 Python 3.9+，当前 {sys.version.split()[0]}")
        return 1

    if args.stop:
        return stop_docker()
    if args.docker and not args.local:
        return run_docker(args)
    return run_local(args)


if __name__ == "__main__":
    raise SystemExit(main())
