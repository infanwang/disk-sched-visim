"""内置 Web 服务：静态页面 + JSON API（stdlib 实现，无第三方依赖）。"""

from __future__ import annotations

import json
import os
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List
from urllib.parse import urlparse

from .engine import ALGO_INFO, ALGOS, DiskConfig, compare, simulate
from .generator import PATTERNS, PRESETS, generate, parse_sequence
from .streams import STREAMS, generate_stream
from .dynamic import compare_dynamic, simulate_dynamic_multi
from .report import markdown_dynamic_report, markdown_report

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def _meta() -> Dict[str, Any]:
    return {
        "algos": [{"id": a, **ALGO_INFO[a]} for a in ALGOS],
        "patterns": [{"id": k, **v} for k, v in PATTERNS.items()],
        "presets": [{"id": k, **v} for k, v in PRESETS.items()],
        "streams": [{"id": k, **v} for k, v in STREAMS.items()],
        "defaults": {
            "tracks": 200,
            "start": 53,
            "direction": "up",
            "seek_ms_per_track": 0.15,
            "rotational_ms": 4.17,
            "scan_to_end": True,
            "count_return": True,
            "stream": "hotspot",
            "stream_count": 120,
            "span_ms": 600,
        },
    }


def _simulate(body: Dict[str, Any]) -> Dict[str, Any]:
    cfg = DiskConfig(
        tracks=body.get("tracks", 200),
        start=body.get("start", 53),
        direction=body.get("direction", "up"),
        seek_ms_per_track=body.get("seek_ms_per_track", 0.15),
        rotational_ms=body.get("rotational_ms", 4.17),
        scan_to_end=body.get("scan_to_end", True),
        count_return=body.get("count_return", True),
    ).normalized()

    seq_raw = body.get("sequence", [])
    if isinstance(seq_raw, str):
        seq = parse_sequence(seq_raw)
    else:
        seq = [int(x) for x in seq_raw if str(x).strip() != ""]

    algos = body.get("algorithms") or list(ALGOS)
    algos = [a for a in algos if a in ALGOS]

    if (body.get("mode") or "static").lower() == "dynamic":
        return _simulate_dynamic(body, cfg, algos)

    if not seq:
        pattern = body.get("generate") or "random"
        seq = generate(pattern, int(body.get("count", 12)), cfg.tracks,
                       body.get("seed"), cfg.start)

    results = simulate(cfg, seq, algos)
    md = markdown_report(cfg, seq, results) if results else ""
    return {
        "config": cfg.__dict__,
        "sequence": seq,
        "results": [r.as_dict() for r in results],
        "summary": compare(results),
        "report_md": md,
    }


def _simulate_dynamic(body: Dict[str, Any], cfg: DiskConfig, algos: List[str]) -> Dict[str, Any]:
    raw = body.get("arrivals")
    stream = body.get("stream", "hotspot")
    count = int(body.get("count", 120))
    span = float(body.get("span_ms", 600))
    seed = body.get("seed")

    if raw:
        arrivals = []
        for item in raw:
            try:
                if isinstance(item, dict):
                    arrivals.append((float(item.get("at", 0)), int(item.get("track", 0))))
                else:
                    arrivals.append((float(item[0]), int(item[1])))
            except (TypeError, ValueError, IndexError):
                continue
    else:
        arrivals = generate_stream(stream, count, cfg.tracks, seed, span, cfg.start)

    results = simulate_dynamic_multi(cfg, arrivals, algos)
    stream_name = STREAMS.get(stream, {}).get("name", stream)
    md = markdown_dynamic_report(cfg, arrivals, results, stream_name, span) if results else ""
    return {
        "mode": "dynamic",
        "config": cfg.__dict__,
        "stream": stream,
        "stream_name": stream_name,
        "span_ms": span,
        "arrivals": [[t, tr] for t, tr in arrivals],
        "results": [r.as_dict() for r in results],
        "summary": compare_dynamic(results),
        "report_md": md,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "DiskSched/1.0"

    def log_message(self, fmt: str, *args) -> None:  # 安静一点
        if os.environ.get("DISKSCHED_VERBOSE"):
            super().log_message(fmt, *args)

    # ---------------------------------------------------------- helpers
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

    def _static(self, path: str) -> None:
        rel = path.lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(WEB_DIR, rel))
        if not full.startswith(os.path.normpath(WEB_DIR)) or not os.path.isfile(full):
            self._send(404, b"404 not found", "text/plain; charset=utf-8")
            return
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as f:
            data = f.read()
        self._send(200, data, MIME.get(ext, "application/octet-stream"))

    # ---------------------------------------------------------- routes
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json({"status": "ok", "service": "disk-sched", "version": "1.1.0",
                        "modes": ["static", "dynamic"]})
        elif path == "/api/meta":
            self._json(_meta())
        elif path.startswith("/api/"):
            self._json({"error": "unknown endpoint"}, 404)
        else:
            self._static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        body = self._body()
        if path == "/api/simulate":
            try:
                self._json(_simulate(body))
            except Exception as exc:  # 把异常回给前端，方便排查
                self._json({"error": f"{type(exc).__name__}: {exc}"}, 400)
        elif path == "/api/generate":
            try:
                cfg = DiskConfig(tracks=int(body.get("tracks", 200)),
                                 start=int(body.get("start", 53)),
                                 direction=body.get("direction", "up")).normalized()
                seq = generate(body.get("pattern", "random"), int(body.get("count", 12)),
                               cfg.tracks, body.get("seed"), cfg.start,
                               bool(body.get("sorted", False)))
                self._json({"sequence": seq})
            except Exception as exc:
                self._json({"error": f"{type(exc).__name__}: {exc}"}, 400)
        else:
            self._json({"error": "unknown endpoint"}, 404)


def _pick_port(port: int, host: str = "127.0.0.1") -> int:
    for candidate in range(port, port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, candidate))
                return candidate
            except OSError:
                continue
    return port


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "本机IP"


def serve(port: int = 8765, open_browser: bool = True, host: str = "127.0.0.1") -> int:
    port = _pick_port(port, host)
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}/"
    print(f"磁盘调度仿真 Web 界面已启动：{url}")
    if host in ("0.0.0.0", "::"):
        print(f"  局域网访问：http://{_lan_ip()}:{port}/")
    print("  按 Ctrl+C 退出")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
    return 0
