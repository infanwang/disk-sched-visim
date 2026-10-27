"""命令行入口：run / gen / report / bench / demo / serve。"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from typing import Dict, List, Optional, Sequence

from .engine import ALGO_INFO, ALGOS, DiskConfig, Result, compare, simulate
from .generator import PATTERNS, PRESETS, generate, parse_sequence
from .dynamic import simulate_dynamic_multi, compare_dynamic
from .streams import STREAMS, generate_stream
from .report import (Painter, THEMES, benchmark_table, detail_block, dyn_metrics_table,
                     fmt_int, header_block, markdown_dynamic_report, markdown_report,
                     metrics_table, summary_block, table)


def _fix_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def _cfg_from_args(a: argparse.Namespace) -> DiskConfig:
    preset = PRESETS.get(getattr(a, "preset", "") or "", None)
    tracks = getattr(a, "tracks", None)
    start = getattr(a, "start", None)
    direction = getattr(a, "direction", None)
    if preset:
        tracks = tracks if tracks is not None else preset["tracks"]
        start = start if start is not None else preset["start"]
        direction = direction or preset["direction"]
    return DiskConfig(
        tracks=int(tracks if tracks is not None else 200),
        start=int(start if start is not None else 53),
        direction=direction or "up",
        seek_ms_per_track=float(getattr(a, "seek_ms", 0.15)),
        rotational_ms=float(getattr(a, "rot_ms", 4.17)),
        scan_to_end=bool(getattr(a, "scan_to_end", True)),
        count_return=bool(getattr(a, "count_return", True)),
    ).normalized()


def _seq_from_args(a: argparse.Namespace, cfg: DiskConfig) -> List[int]:
    if getattr(a, "seq", None):
        return parse_sequence(a.seq)
    if getattr(a, "preset", None) and not getattr(a, "generate", None):
        p = PRESETS.get(a.preset)
        if p:
            return list(p["sequence"])  # type: ignore[arg-type]
    pattern = getattr(a, "generate", None) or "random"
    return generate(pattern, int(getattr(a, "count", 12)), cfg.tracks,
                    getattr(a, "seed", None), cfg.start, bool(getattr(a, "sorted", False)))


def _algos_from_args(a: argparse.Namespace) -> List[str]:
    raw = (getattr(a, "algo", None) or "all").strip()
    if raw.lower() == "all":
        return list(ALGOS)
    picked = []
    for part in raw.replace(";", ",").split(","):
        p = part.strip().upper().replace("CSCAN", "C-SCAN").replace("CLOOK", "C-LOOK")
        if p in ALGOS:
            picked.append(p)
    return picked or list(ALGOS)


def _painter(a: argparse.Namespace) -> Painter:
    theme = getattr(a, "theme", "navy") or "navy"
    no_color = bool(getattr(a, "no_color", False)) or os.environ.get("NO_COLOR")
    if theme == "none":
        no_color = True
    return Painter(theme=theme, enabled=not no_color, ascii_only=bool(getattr(a, "ascii", False)))


def cmd_run(a: argparse.Namespace) -> int:
    p = _painter(a)
    cfg = _cfg_from_args(a)
    seq = _seq_from_args(a, cfg)
    algos = _algos_from_args(a)
    results = simulate(cfg, seq, algos)
    if not results:
        print(p("没有有效请求（检查序列与磁道范围）", "bad"))
        return 2

    if a.json:
        print(json.dumps({"config": cfg.__dict__, "sequence": seq,
                          "results": [r.as_dict() for r in results],
                          "summary": compare(results)}, ensure_ascii=False, indent=2))
        return 0

    print(header_block(cfg, seq, p))
    print()
    print(metrics_table(results, p))
    print()
    print(summary_block(results, p))
    if a.detail:
        print()
        for r in results:
            print(detail_block(r, p))
            print()
    if a.save:
        with open(a.save, "w", encoding="utf-8") as f:
            json.dump({"config": cfg.__dict__, "sequence": seq,
                       "results": [r.as_dict() for r in results]}, f, ensure_ascii=False, indent=2)
        print(p(f"已保存 {a.save}", "dim"))
    return 0


def cmd_gen(a: argparse.Namespace) -> int:
    cfg = _cfg_from_args(a)
    seq = generate(a.pattern, a.count, cfg.tracks, a.seed, cfg.start, a.sorted)
    if a.json:
        print(json.dumps({"pattern": a.pattern, "seed": a.seed, "sequence": seq}, ensure_ascii=False))
    else:
        print(",".join(str(x) for x in seq))
    return 0


def cmd_report(a: argparse.Namespace) -> int:
    p = _painter(a)
    cfg = _cfg_from_args(a)
    seq = _seq_from_args(a, cfg)
    results = simulate(cfg, seq, _algos_from_args(a))
    if not results:
        print(p("没有有效请求", "bad"))
        return 2

    fmt = (a.format or "md").lower()
    if fmt == "json":
        text = json.dumps({"config": cfg.__dict__, "sequence": seq,
                           "results": [r.as_dict() for r in results],
                           "summary": compare(results)}, ensure_ascii=False, indent=2)
    elif fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["算法", "总寻道", "平均寻道", "最大单次", "换向", "估算总耗时ms",
                    "平均响应ms", "最坏响应ms", "服务顺序"])
        for r in results:
            m = r.metrics
            w.writerow([r.algo, m["total_seek"], m["avg_seek"], m["max_step"], m["reversals"],
                        m["makespan_ms"], m["avg_response_ms"], m["max_response_ms"],
                        " ".join(str(x) for x in r.order)])
        text = buf.getvalue()
    else:
        text = markdown_report(cfg, seq, results)

    if a.out:
        enc = "utf-8-sig" if fmt == "csv" else "utf-8"
        with open(a.out, "w", encoding=enc, newline="" if fmt == "csv" else None) as f:
            f.write(text)
        print(p(f"报告已写入 {a.out}", "good"))
        if fmt == "md":
            print(p("  提示：可用 Typora / VS Code 预览，或粘进 Word 转 PDF。", "dim"))
    else:
        print(text)
    return 0


def cmd_bench(a: argparse.Namespace) -> int:
    p = _painter(a)
    base = _cfg_from_args(a)
    patterns = [x.strip() for x in (a.patterns or "random,sequential,hotspot,bimodal,alternating,zipf").split(",") if x.strip()]
    algos = _algos_from_args(a)
    cases = max(1, a.cases)
    rows = []
    for pat in patterns:
        wins = {x: 0 for x in algos}
        wins_worst = {x: 0 for x in algos}
        totals = {x: 0.0 for x in algos}
        resp = {x: 0.0 for x in algos}
        for i in range(cases):
            cfg = DiskConfig(tracks=base.tracks, start=base.start,
                             direction=base.direction,
                             seek_ms_per_track=base.seek_ms_per_track,
                             rotational_ms=base.rotational_ms,
                             scan_to_end=base.scan_to_end, count_return=base.count_return)
            seq = generate(pat, a.count, base.tracks, seed=i * 7919 + 13, start=base.start)
            res = simulate(cfg, seq, algos)
            if not res:
                continue
            for r in res:
                totals[r.algo] += r.metrics["total_seek"]
                resp[r.algo] += r.metrics["avg_response_ms"]
            best = min(res, key=lambda r: (r.metrics["total_seek"], r.metrics["avg_response_ms"]))
            wins[best.algo] += 1
            worst = min(res, key=lambda r: r.metrics["max_response_ms"])
            wins_worst[worst.algo] += 1
        rows.append({"pattern": PATTERNS.get(pat, {}).get("name", pat),
                     "cases": cases, "wins": wins, "wins_worst": wins_worst,
                     "avg": {k: (totals[k] / cases if cases else 0) for k in algos},
                     "avg_resp": {k: (resp[k] / cases if cases else 0) for k in algos}})

    print(p("批量基准测试", "head") + p(f"  每种负载 {cases} 组随机样本，每组 {a.count} 个请求", "dim"))
    print(p(f"  磁道 {base.tracks}  起点 {base.start}  方向 {base.direction}  "
            f"每磁道 {base.seek_ms_per_track} ms", "dim"))
    print()
    print(p("胜率一：总寻道最短", "head"))
    print(benchmark_table(rows, algos, p))
    print()
    print(p("胜率二：最坏响应最低（公平性视角）", "head"))
    rows2 = []
    for row in rows:
        rows2.append({"pattern": row["pattern"], "cases": row["cases"],
                      "wins": row.get("wins_worst", {})})
    print(benchmark_table(rows2, algos, p))
    print()
    headers = ["访问模式"] + list(algos)
    body = []
    for row in rows:
        avg = row["avg"]  # type: ignore[assignment]
        body.append([str(row["pattern"])] + [f'{fmt_int(avg[a])}' for a in algos])
    print(p("平均总寻道长度（条）", "dim"))
    print(table(headers, body, p, ["left"] + ["right"] * len(algos)))
    print()
    print(p("读法：静态批处理下 SSTF 的总寻道几乎总是最短（贪心近似最优），", "dim"))
    print(p("      真正的代价在最坏响应与换向次数——真实系统请求是动态到达的，", "dim"))
    print(p("      远端请求会被不断插队，这才是 SSTF 饥饿的来源。", "dim"))
    return 0


def cmd_demo(a: argparse.Namespace) -> int:
    p = _painter(a)
    print(p("磁盘调度演示：同一序列，六种算法", "head"))
    print()
    preset = PRESETS["classic"]
    cfg = DiskConfig().normalized()
    seq = list(preset["sequence"])  # type: ignore[arg-type]
    results = simulate(cfg, seq)
    print(header_block(cfg, seq, p))
    print()
    print(metrics_table(results, p))
    print()
    print(summary_block(results, p))
    print()
    print(p("再一组：请求全在磁头一侧，看「空跑」到底多贵", "head"))
    print()
    cfg2 = DiskConfig(tracks=200, start=180, direction="up")
    seq2 = PRESETS["one_side"]["sequence"]  # type: ignore[index]
    res2 = simulate(cfg2, seq2)  # type: ignore[arg-type]
    print(header_block(cfg2, seq2, p))  # type: ignore[arg-type]
    print()
    print(metrics_table(res2, p, show_bars=False))
    print()
    by = {r.algo: r for r in res2}
    if "SCAN" in by and "LOOK" in by:
        gap = by["SCAN"].metrics["total_seek"] - by["LOOK"].metrics["total_seek"]
        print(p(f"  SCAN 比 LOOK 多跑 {gap:.0f} 条，这正好是从最后一个请求走到端点的空跑。", "dim"))
    if "C-SCAN" in by and "C-LOOK" in by:
        gap2 = by["C-SCAN"].metrics["total_seek"] - by["C-LOOK"].metrics["total_seek"]
        print(p(f"  C-SCAN 比 C-LOOK 多跑 {gap2:.0f} 条，这是「走到物理端点再返回」的代价。", "dim"))
    print(p("  结论：LOOK / C-LOOK 就是 SCAN / C-SCAN 减去无意义的端点行程，", "dim"))
    print(p("        这也是实际磁盘固件普遍用 LOOK 系列而不是 SCAN 的原因。", "dim"))
    return 0


def cmd_dyn(a: argparse.Namespace) -> int:
    p = _painter(a)
    cfg = _cfg_from_args(a)
    arrivals = generate_stream(a.stream, a.count, cfg.tracks, a.seed, a.span, cfg.start)
    results = simulate_dynamic_multi(cfg, arrivals, _algos_from_args(a))
    if not results:
        print(p("没有有效请求", "bad"))
        return 2

    if a.json:
        print(json.dumps({
            "mode": "dynamic",
            "config": cfg.__dict__,
            "stream": a.stream,
            "arrivals": [[t, tr] for t, tr in arrivals],
            "results": [r.as_dict() for r in results],
            "summary": compare_dynamic(results),
        }, ensure_ascii=False, indent=2))
        return 0

    name = STREAMS.get(a.stream, {}).get("name", a.stream)
    print(p("动态到达仿真", "head") + p(f"  {name}", "dim"))
    print(p("─" * 62, "border"))
    print(f'  磁道 {cfg.tracks}   起点 {cfg.start}   方向 {"增大↑" if cfg.direction == "up" else "减小↓"}   '
          f'到达窗口 {a.span:.0f} ms   请求 {len(arrivals)} 个   种子 {a.seed}')
    est = cfg.rotational_ms + cfg.seek_ms_per_track * 10
    load = len(arrivals) * est / max(1.0, a.span)
    print(p(f'  估算负载 ρ ≈ {load:.1f}（>1 时队列持续增长）', "dim"))
    print()
    print(dyn_metrics_table(results, p))
    print()

    c = compare_dynamic(results)
    if c:
        print(p("结论", "head"))
        print(f'  平均等待最短  {c["best_wait"]}   （{c["best_wait_value"]} ms）')
        print(f'  最坏等待最低  {c["best_worst"]}   （{c["best_worst_value"]} ms）')
        print(f'  吞吐最高      {c["best_throughput"]}   （{c["best_throughput_value"]} 请求/秒）')
        print(f'  公平性最好    {c["most_fair"]}   （最坏/中位 = {c["most_fair_value"]}）')
        print()

    worst = max(results, key=lambda r: r.metrics["max_wait"])
    if worst.metrics["fairness"] >= 5:
        print(p(f'  饥饿信号：{worst.algo} 的最坏等待达到中位数的 {worst.metrics["fairness"]:.1f} 倍。', "warn"))
        top = sorted(worst.records, key=lambda x: x.wait, reverse=True)[:3]
        for x in top:
            print(p(f'    磁道 {x.track}：到达 {x.at:.0f} ms，开始服务 {x.start:.0f} ms，等了 {x.wait:.0f} ms', "dim"))
        print()

    if a.trace:
        for r in results[:1]:
            print(p(f'{r.algo} 逐请求明细', "head"))
            heads = ["#", "磁道", "到达", "开始", "等待"]
            rows = [[str(x.idx + 1), str(x.track), f"{x.at:.0f}", f"{x.start:.0f}", f"{x.wait:.0f}"]
                    for x in r.records]
            print(table(heads, rows, p, ["right"] * 5))
    return 0


def cmd_serve(a: argparse.Namespace) -> int:
    from .server import serve
    return serve(port=a.port, open_browser=not a.no_open, host=getattr(a, "host", "127.0.0.1"))


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--tracks", type=int, default=None, help="磁道数，默认 200")
    common.add_argument("--start", type=int, default=None, help="初始磁头位置，默认 53")
    common.add_argument("--dir", dest="direction", choices=["up", "down"], default=None,
                        help="初始方向 up=磁道号增大 / down=减小")
    common.add_argument("--seek-ms", type=float, default=0.15, help="每跨一条磁道的寻道时间(ms)")
    common.add_argument("--rot-ms", type=float, default=4.17, help="每个请求的平均旋转延迟(ms)")
    common.add_argument("--scan-to-end", dest="scan_to_end", action="store_true", default=True,
                        help="SCAN 走到物理端点（默认）")
    common.add_argument("--no-scan-to-end", dest="scan_to_end", action="store_false",
                        help="SCAN 只走到最后一个请求")
    common.add_argument("--count-return", dest="count_return", action="store_true", default=True,
                        help="C-SCAN/C-LOOK 的返回段计入寻道（默认）")
    common.add_argument("--no-count-return", dest="count_return", action="store_false",
                        help="返回段不计入寻道")
    common.add_argument("--theme", default="navy", choices=list(THEMES) + ["none"],
                        help="终端配色主题")
    common.add_argument("--no-color", action="store_true", help="关闭颜色")
    common.add_argument("--ascii", action="store_true", help="只用 ASCII 字符（兼容老终端）")
    common.add_argument("--json", action="store_true", help="输出 JSON")

    seq_grp = argparse.ArgumentParser(add_help=False)
    seq_grp.add_argument("--seq", help='访问序列，如 "98,183,37,122"')
    seq_grp.add_argument("--preset", choices=list(PRESETS), help="使用内置例题")
    seq_grp.add_argument("--generate", choices=list(PATTERNS), help="按模式生成序列")
    seq_grp.add_argument("--count", type=int, default=12, help="生成序列的请求数")
    seq_grp.add_argument("--seed", type=int, default=None, help="随机种子")
    seq_grp.add_argument("--sorted", action="store_true", help="生成后按方向排序")
    seq_grp.add_argument("--algo", default="all", help="算法，all 或 FCFS,SSTF,...")

    ap = argparse.ArgumentParser(
        prog="disksched",
        description="磁盘调度算法可视化仿真：算法对比、序列生成、性能报告、Web 界面",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例
  python disksched.py run --preset classic --detail
  python disksched.py run --generate bimodal --count 10 --seed 7 --algo SSTF,SCAN,LOOK
  python disksched.py report --generate hotspot --seed 3 -o 报告.md
  python disksched.py bench --cases 100
  python disksched.py serve --port 8765
""",
    )
    sub = ap.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", parents=[common, seq_grp], help="跑一次对比")
    p_run.add_argument("--detail", action="store_true", help="打印每个算法的轨迹与分段")
    p_run.add_argument("--save", help="把结果存成 JSON")
    p_run.set_defaults(func=cmd_run)

    p_gen = sub.add_parser("gen", parents=[common], help="生成访问序列")
    p_gen.add_argument("--pattern", default="random", choices=list(PATTERNS))
    p_gen.add_argument("--count", type=int, default=12)
    p_gen.add_argument("--seed", type=int, default=None)
    p_gen.add_argument("--sorted", action="store_true")
    p_gen.set_defaults(func=cmd_gen)

    p_rep = sub.add_parser("report", parents=[common, seq_grp], help="生成性能对比报告")
    p_rep.add_argument("-o", "--out", help="输出文件（默认打印到终端）")
    p_rep.add_argument("--format", default="md", choices=["md", "json", "csv"])
    p_rep.set_defaults(func=cmd_report)

    p_bench = sub.add_parser("bench", parents=[common], help="批量基准：各负载下的胜率")
    p_bench.add_argument("--cases", type=int, default=100)
    p_bench.add_argument("--count", type=int, default=12)
    p_bench.add_argument("--patterns", default="random,sequential,hotspot,bimodal,alternating,zipf")
    p_bench.add_argument("--algo", default="all")
    p_bench.set_defaults(func=cmd_bench)

    p_demo = sub.add_parser("demo", parents=[common], help="内置演示")
    p_demo.set_defaults(func=cmd_demo)

    p_dyn = sub.add_parser("dyn", parents=[common], help="动态到达仿真（带排队）")
    p_dyn.add_argument("--stream", default="hotspot", choices=list(STREAMS),
                       help="到达流模式")
    p_dyn.add_argument("--count", type=int, default=120, help="请求数")
    p_dyn.add_argument("--span", type=float, default=600.0, help="到达窗口（ms）")
    p_dyn.add_argument("--seed", type=int, default=None)
    p_dyn.add_argument("--algo", default="all")
    p_dyn.add_argument("--trace", action="store_true", help="打印逐请求明细")
    p_dyn.set_defaults(func=cmd_dyn)

    p_srv = sub.add_parser("serve", help="启动 Web 可视化界面")
    p_srv.add_argument("--port", type=int, default=8765)
    p_srv.add_argument("--host", default="127.0.0.1",
                       help="监听地址，局域网/容器用 0.0.0.0")
    p_srv.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    p_srv.set_defaults(func=cmd_serve)

    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    _fix_stdout()
    ap = build_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "cmd", None):
        ap.print_help()
        return 0
    # 子命令未带 color 参数时的兜底
    for key, val in (("theme", "navy"), ("no_color", False), ("ascii", False), ("json", False)):
        if not hasattr(args, key):
            setattr(args, key, val)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\n已中断")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
