"""终端渲染（表格 / 条形图 / 主题）与 Markdown 报告生成。

表格按东亚字符宽度对齐，中文与数字混排不会错位；
颜色只在渲染层出现，任何 --json 输出都不带 ANSI 转义。
"""

from __future__ import annotations

import datetime as _dt
import unicodedata
from typing import Dict, Iterable, List, Optional, Sequence

from .engine import ALGO_INFO, ALGOS, DiskConfig, Result, compare

RESET = "\x1b[0m"

THEMES: Dict[str, Dict[str, str]] = {
    "navy": {   # 深色终端：藏青底气质，金色点缀
        "name": "深海",
        "head": "\x1b[38;5;180m",   # 沙金
        "accent": "\x1b[38;5;74m",  # 青蓝
        "good": "\x1b[38;5;71m",
        "warn": "\x1b[38;5;179m",
        "bad": "\x1b[38;5;167m",
        "dim": "\x1b[38;5;244m",
        "border": "\x1b[38;5;238m",
    },
    "paper": {  # 浅色终端
        "name": "纸白",
        "head": "\x1b[38;5;130m",
        "accent": "\x1b[38;5;25m",
        "good": "\x1b[38;5;28m",
        "warn": "\x1b[38;5;136m",
        "bad": "\x1b[38;5;124m",
        "dim": "\x1b[38;5;240m",
        "border": "\x1b[38;5;250m",
    },
    "vivid": {
        "name": "高饱和",
        "head": "\x1b[1;38;5;213m",
        "accent": "\x1b[38;5;51m",
        "good": "\x1b[38;5;46m",
        "warn": "\x1b[38;5;226m",
        "bad": "\x1b[38;5;196m",
        "dim": "\x1b[38;5;245m",
        "border": "\x1b[38;5;240m",
    },
    "mono": {
        "name": "单色",
        "head": "\x1b[1m", "accent": "\x1b[1m", "good": "\x1b[1m",
        "warn": "\x1b[1m", "bad": "\x1b[1m", "dim": "\x1b[2m", "border": "\x1b[2m",
    },
}


class Painter:
    def __init__(self, theme: str = "navy", enabled: bool = True, ascii_only: bool = False):
        self.enabled = enabled
        self.ascii_only = ascii_only
        self.t = THEMES.get(theme, THEMES["navy"])

    def __call__(self, text: str, key: str = "") -> str:
        if not self.enabled or key not in self.t:
            return text
        return f"{self.t[key]}{text}{RESET}"

    # 字符集：不支持 Unicode 时自动降级
    def ch(self, uni: str, ascii_: str) -> str:
        return ascii_ if self.ascii_only else uni


def dwidth(s: str) -> int:
    w = 0
    for ch in s:
        if unicodedata.combining(ch):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def pad(s: str, width: int, align: str = "left") -> str:
    space = max(0, width - dwidth(s))
    if align == "right":
        return " " * space + s
    if align == "center":
        left = space // 2
        return " " * left + s + " " * (space - left)
    return s + " " * space


def table(headers: Sequence[str], rows: Sequence[Sequence[str]], p: Painter,
          aligns: Optional[Sequence[str]] = None, highlight: Optional[set] = None,
          min_widths: Optional[Sequence[int]] = None) -> str:
    aligns = list(aligns or ["left"] * len(headers))
    widths = [max(dwidth(str(h)), *(dwidth(str(r[i])) for r in rows)) if rows else dwidth(str(h))
              for i, h in enumerate(headers)]
    if min_widths:
        widths = [max(w, mw) for w, mw in zip(widths, min_widths)]

    if p.ascii_only:
        chars = {"h": "-", "v": "|", "tl": "+", "tm": "+", "tr": "+",
                 "ml": "+", "mm": "+", "mr": "+", "bl": "+", "bm": "+", "br": "+"}
    else:
        chars = {"h": "─", "v": "│", "tl": "┌", "tm": "┬", "tr": "┐",
                 "ml": "├", "mm": "┼", "mr": "┤", "bl": "└", "bm": "┴", "br": "┘"}

    def rule(left: str, mid: str, right: str) -> str:
        parts = [chars["h"] * (w + 2) for w in widths]
        return (p(left, "border") + p(mid, "border").join(parts)
                + p(right, "border"))

    v = p(chars["v"], "border")
    out = [rule(chars["tl"], chars["tm"], chars["tr"])]
    out.append(v + v.join(" " + p(pad(str(h), widths[i], "center"), "head") + " "
                          for i, h in enumerate(headers)) + v)
    out.append(rule(chars["ml"], chars["mm"], chars["mr"]))
    for ri, row in enumerate(rows):
        cells = []
        for ci, cell in enumerate(row):
            txt = pad(str(cell), widths[ci], aligns[ci] if ci < len(aligns) else "left")
            cells.append(" " + (p(txt, "good") if highlight and (ri, ci) in highlight else txt) + " ")
        out.append(v + v.join(cells) + v)
    out.append(rule(chars["bl"], chars["bm"], chars["br"]))
    return "\n".join(out)


def bar(value: float, vmax: float, width: int = 28, p: Optional[Painter] = None,
        color: str = "accent") -> str:
    if vmax <= 0:
        return ""
    filled = int(round(value / vmax * width))
    filled = max(1, min(width, filled))
    full, empty = ("#", ".") if (p and p.ascii_only) else ("█", "░")
    body = full * filled + empty * (width - filled)
    return (p(body, color) if p else body)


def fmt_int(x) -> str:
    try:
        return f"{int(round(float(x))):,}"
    except (TypeError, ValueError):
        return str(x)


def metrics_table(results: Sequence[Result], p: Painter, show_bars: bool = True) -> str:
    if not results:
        return p("（没有结果）", "dim")
    best_total = min(r.metrics["total_seek"] for r in results)
    vmax = max(r.metrics["total_seek"] for r in results) or 1
    headers = ["算法", "总寻道", "平均/次", "最大单次", "换向", "平均响应ms", "最坏响应ms", "相对最优"]
    rows, hl = [], set()
    for i, r in enumerate(results):
        m = r.metrics
        ratio = (m["total_seek"] / best_total) if best_total else 1.0
        rows.append([
            f'{r.algo} {ALGO_INFO[r.algo]["name"]}' if ALGO_INFO[r.algo]["name"] != r.algo else r.algo,
            fmt_int(m["total_seek"]),
            f'{m["avg_seek"]:.1f}',
            fmt_int(m["max_step"]),
            str(m["reversals"]),
            f'{m["avg_response_ms"]:.1f}',
            f'{m["max_response_ms"]:.1f}',
            ("最优" if abs(ratio - 1) < 1e-9 else f"+{(ratio - 1) * 100:.0f}%"),
        ])
        if abs(ratio - 1) < 1e-9:
            hl.add((i, 1))
    txt = table(headers, rows, p, ["left", "right", "right", "right", "right",
                                   "right", "right", "right"], highlight=hl)
    if show_bars:
        lines = [txt, "", p("寻道长度对比（越短越好）", "dim")]
        for r in results:
            lines.append("  " + pad(r.algo, 7) + bar(r.metrics["total_seek"], vmax, 30, p)
                         + "  " + fmt_int(r.metrics["total_seek"]))
        return "\n".join(lines)
    return txt


def detail_block(r: Result, p: Painter, width: int = 0) -> str:
    m = r.metrics
    order = " -> ".join(str(x) for x in r.order)
    path = " -> ".join(str(x) for x in r.path)
    lines = [
        p(f'{r.algo}  {ALGO_INFO[r.algo]["name"]}', "head"),
        p(f'  {ALGO_INFO[r.algo]["trait"]}', "dim"),
        f'  服务顺序：{order}',
        f'  磁头轨迹：{path}',
        f'  总寻道 {fmt_int(m["total_seek"])} 条  |  平均 {m["avg_seek"]:.1f}  |  '
        f'最大单次 {fmt_int(m["max_step"])}  |  换向 {m["reversals"]} 次',
        f'  估算耗时 {m["makespan_ms"]:.1f} ms  |  平均响应 {m["avg_response_ms"]:.1f} ms  |  '
        f'最坏响应 {m["max_response_ms"]:.1f} ms',
    ]
    segs = [s for s in r.segments if s.kind != "seek" or s.dist > 0]
    if segs:
        shown = ""
        for s in segs[:14]:
            tag = {"seek": "", "turn": "·空走", "wrap": "·返回", "wrap_seek": "·返回"}[s.kind]
            shown += f'{s.src}->{s.dst}({s.dist}){tag}  '
        lines.append("  分段：" + shown.strip())
    return "\n".join(lines)


def header_block(cfg: DiskConfig, seq: Sequence[int], p: Painter) -> str:
    return "\n".join([
        p("磁盘调度仿真", "head") + p("  disk scheduling simulator", "dim"),
        p("─" * 62, "border"),
        f'  磁道数 {cfg.tracks}   起点 {cfg.start}   '
        f'方向 {"增大↑" if cfg.direction == "up" else "减小↓"}   '
        f'每磁道 {cfg.seek_ms_per_track} ms   旋转 {cfg.rotational_ms} ms',
        f'  请求 {len(seq)} 个：' + ", ".join(str(x) for x in seq),
    ])


def summary_block(results: Sequence[Result], p: Painter) -> str:
    c = compare(results)
    if not c:
        return ""
    lines = [
        p("结论", "head"),
        f'  寻道最短      {c["best_seek"]}   （{fmt_int(c["best_seek_value"])} 条）',
        f'  平均响应最快  {c["best_response"]}   （{c["best_response_value"]} ms）',
        f'  最坏响应最低  {c["best_worst_case"]}   （{c["best_worst_case_value"]} ms）',
        f'  公平性最好    {c["most_fair"]}   （最坏/平均 = {c["most_fair_value"]}）',
        f'  换向最少      {c["fewest_turns"]}   （{c["fewest_turns_value"]} 次）',
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- Markdown

def markdown_report(cfg: DiskConfig, seq: Sequence[int], results: Sequence[Result],
                    title: str = "磁盘调度算法性能对比分析报告") -> str:
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    best_total = min(r.metrics["total_seek"] for r in results) if results else 1
    L: List[str] = []
    L.append(f"# {title}")
    L.append("")
    L.append(f"> 生成时间：{now}　|　仿真口径：见文末「计算口径」")
    L.append("")
    L.append("## 一、实验配置")
    L.append("")
    L.append("| 项目 | 取值 |")
    L.append("| --- | --- |")
    L.append(f"| 磁道总数 | {cfg.tracks}（编号 0–{cfg.tracks - 1}） |")
    L.append(f"| 初始磁头位置 | {cfg.start} |")
    L.append(f"| 初始方向 | {'向磁道号增大' if cfg.direction == 'up' else '向磁道号减小'} |")
    L.append(f"| 请求数 | {len(seq)} |")
    L.append(f"| 每磁道寻道时间 | {cfg.seek_ms_per_track} ms（模型参数） |")
    L.append(f"| 平均旋转延迟 | {cfg.rotational_ms} ms（7200 rpm） |")
    L.append(f"| SCAN 走到端点 | {'是' if cfg.scan_to_end else '否（等价 LOOK）'} |")
    L.append(f"| C-SCAN 返回段计入 | {'是' if cfg.count_return else '否'} |")
    L.append("")
    L.append("**访问序列**")
    L.append("")
    L.append("```")
    L.append(", ".join(str(x) for x in seq))
    L.append("```")
    L.append("")
    L.append("## 二、综合指标对比")
    L.append("")
    L.append("| 算法 | 总寻道长度 | 平均寻道/次 | 最大单次 | 换向次数 | 估算总耗时(ms) | 平均响应(ms) | 最坏响应(ms) | 相对最优 |")
    L.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for r in results:
        m = r.metrics
        ratio = m["total_seek"] / best_total if best_total else 1
        _name = ALGO_INFO[r.algo]["name"]
        _label = f"{r.algo} · {_name}" if _name != r.algo else r.algo
        L.append(f'| {_label} | {fmt_int(m["total_seek"])} | '
                 f'{m["avg_seek"]:.1f} | {fmt_int(m["max_step"])} | {m["reversals"]} | '
                 f'{m["makespan_ms"]:.1f} | {m["avg_response_ms"]:.1f} | '
                 f'{m["max_response_ms"]:.1f} | {"最优" if abs(ratio - 1) < 1e-9 else f"+{(ratio-1)*100:.0f}%"} |')
    L.append("")
    L.append("### 寻道长度对比")
    L.append("")
    vmax = max(r.metrics["total_seek"] for r in results) or 1
    L.append("```text")
    for r in results:
        w = max(1, int(round(r.metrics["total_seek"] / vmax * 34)))
        L.append(f'{r.algo:<7} {"#" * w} {fmt_int(r.metrics["total_seek"])}')
    L.append("```")
    L.append("")

    c = compare(results)
    L.append("## 三、结论与建议")
    L.append("")
    L.append(f'1. **寻道最省**：{c.get("best_seek", "-")}，总寻道 {fmt_int(c.get("best_seek_value", 0))} 条；'
             f'相对最差方案节省 {(1 - best_total / (max(r.metrics["total_seek"] for r in results) or 1)) * 100:.0f}%。')
    L.append(f'2. **平均响应最快**：{c.get("best_response", "-")}，平均 {c.get("best_response_value", 0)} ms。')
    L.append(f'3. **最坏情况最好**：{c.get("best_worst_case", "-")}，最坏请求 {c.get("best_worst_case_value", 0)} ms，'
             f'适合对尾延迟敏感的场景。')
    L.append(f'4. **公平性最好**：{c.get("most_fair", "-")}，最坏响应与平均响应之比仅 {c.get("most_fair_value", 0)}。')
    L.append(f'5. **机械损耗最小**：{c.get("fewest_turns", "-")}，换向仅 {c.get("fewest_turns_value", 0)} 次。')
    L.append("")
    ranking = sorted(results, key=lambda r: r.metrics["total_seek"])
    if len(ranking) >= 2:
        gap = ranking[-1].metrics["total_seek"] - ranking[0].metrics["total_seek"]
        L.append(f"**总体排序（按总寻道）**：{' < '.join(r.algo for r in ranking)}，"
                 f"首尾相差 {fmt_int(gap)} 条磁道。")
    L.append("")
    L.append("**选型建议**")
    L.append("")
    L.append("- 批量、离线、追求吞吐：优先 SSTF 或 LOOK，寻道最短。")
    L.append("- 交互式系统、要求响应时间可预期：选 C-LOOK / C-SCAN，避免个别请求被无限推迟。")
    L.append("- 负载方向性强（顺序读写为主）：SCAN 系列优势明显；请求随机分散时 SSTF 更划算。")
    L.append("- 教学与考试：SSTF 的饥饿风险、SCAN 的端点空跑、C-SCAN 的返回代价，是三个必考点。")
    L.append("")

    L.append("## 四、各算法明细")
    L.append("")
    for r in results:
        m = r.metrics
        _n = ALGO_INFO[r.algo]["name"]
        L.append(f'### {r.algo} · {_n}' if _n != r.algo else f'### {r.algo}')
        L.append("")
        L.append(f'> {ALGO_INFO[r.algo]["short"]}　{ALGO_INFO[r.algo]["trait"]}')
        L.append("")
        L.append(f'- 服务顺序：`{" → ".join(str(x) for x in r.order)}`')
        L.append(f'- 磁头轨迹：`{" → ".join(str(x) for x in r.path)}`')
        L.append(f'- 指标：总寻道 {fmt_int(m["total_seek"])} 条，平均 {m["avg_seek"]:.1f} 条/次，'
                 f'最大单次 {fmt_int(m["max_step"])} 条，换向 {m["reversals"]} 次')
        non_seek = [s for s in r.segments if s.kind in ("turn", "wrap")]
        if non_seek:
            L.append('- 空走段：' + "、".join(
                f'{"端点空走" if s.kind == "turn" else "循环返回"} {s.src}→{s.dst}（{s.dist} 条）'
                for s in non_seek))
        L.append("")

    L.append("## 五、计算口径")
    L.append("")
    L.append(f"1. 寻道长度按磁头移动的磁道数累计；C-SCAN / C-LOOK 的返回段"
             f"{'计入' if cfg.count_return else '不计入'}总寻道（本报告取该口径，"
             f"另一口径的数值见命令行 `--count-return/--no-count-return`）。")
    L.append(f"2. 请求视为同时到达（静态批处理），不计 I/O 排队与传输时间。")
    L.append(f"3. 估算耗时 = 寻道距离 × {cfg.seek_ms_per_track} ms + 每请求 {cfg.rotational_ms} ms 旋转延迟，"
             f"仅用于横向比较，不代表真实磁盘性能。")
    L.append(f"4. 同一磁道的重复请求已合并；越界磁道号被丢弃。")
    L.append("")
    return "\n".join(L)


def benchmark_table(rows: List[Dict[str, object]], algos: Sequence[str], p: Painter) -> str:
    """rows: [{pattern, cases, avg: {...}, wins: {...}}]"""
    headers = ["访问模式", "样本"] + list(algos) + ["最稳定"]
    body, hl = [], set()
    for i, row in enumerate(rows):
        wins: Dict[str, int] = row["wins"]  # type: ignore[assignment]
        best = max(wins, key=lambda k: wins[k]) if wins else "-"
        cells = [str(row["pattern"]), str(row["cases"])]
        for a in algos:
            w = wins.get(a, 0)
            cells.append(f"{w}胜")
            if a == best:
                hl.add((i, 2 + list(algos).index(a)))
        cells.append(best)
        body.append(cells)
    return table(headers, body, p, ["left", "right"] + ["right"] * len(algos) + ["left"],
                 highlight=hl)


# ---------------------------------------------------------------- 动态到达

def dyn_metrics_table(results, p: Painter, show_bars: bool = True) -> str:
    if not results:
        return p("（没有结果）", "dim")
    best_avg = min(r.metrics["avg_wait"] for r in results)
    vmax = max(r.metrics["max_wait"] for r in results) or 1
    headers = ["算法", "完成", "平均等待", "P95 等待", "最大等待", "平均响应", "完成用时", "吞吐/s"]
    rows, hl = [], set()
    for i, r in enumerate(results):
        m = r.metrics
        rows.append([
            f'{r.algo} {ALGO_INFO[r.algo]["name"]}' if ALGO_INFO[r.algo]["name"] != r.algo else r.algo,
            f'{m["served"]}/{m["total"]}',
            f'{m["avg_wait"]:.1f}',
            f'{m["p95_wait"]:.1f}',
            f'{m["max_wait"]:.1f}',
            f'{m["avg_turn"]:.1f}',
            f'{m["makespan"]:.0f}',
            f'{m["throughput"]:.1f}',
        ])
        if abs(m["avg_wait"] - best_avg) < 1e-9:
            hl.add((i, 2))
    txt = table(headers, rows, p, ["left", "right", "right", "right", "right", "right", "right", "right"],
                highlight=hl)
    if not show_bars:
        return txt
    lines = [txt, "", p("最坏等待（ms，越短越不会被饿死）", "dim")]
    for r in results:
        lines.append("  " + pad(r.algo, 7) + bar(r.metrics["max_wait"], vmax, 30, p)
                     + f'  {r.metrics["max_wait"]:.0f}')
    return "\n".join(lines)


def markdown_dynamic_report(cfg: DiskConfig, arrivals, results, pattern_name: str = "",
                            span_ms: float = 0, title: str = "磁盘调度动态到达仿真报告") -> str:
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    L = [f"# {title}", "", f"> 生成时间：{now}　|　模型：请求按时间到达，磁头只从已到达队列中选取"]
    L += ["", "## 一、负载配置", "", "| 项目 | 取值 |", "| --- | --- |"]
    L.append(f"| 磁道总数 | {cfg.tracks}（0–{cfg.tracks - 1}） |")
    L.append(f"| 初始磁头 | {cfg.start} |")
    L.append(f"| 初始方向 | {'磁道号增大' if cfg.direction == 'up' else '磁道号减小'} |")
    L.append(f"| 到达模式 | {pattern_name or '-'} |")
    L.append(f"| 请求数 | {len(arrivals)} |")
    if span_ms:
        L.append(f"| 到达窗口 | {span_ms:.0f} ms |")
    load = 0.0
    if span_ms and results and results[0].metrics.get("served"):
        load = len(arrivals) * (cfg.rotational_ms + cfg.seek_ms_per_track * 10) / span_ms
    L.append(f"| 估算负载 ρ | ≈ {load:.1f}（>1 表示排队持续增长） |")
    L.append(f"| 每磁道寻道 | {cfg.seek_ms_per_track} ms |")
    L.append(f"| 旋转延迟 | {cfg.rotational_ms} ms |")
    L.append("")

    L.append("## 二、指标对比")
    L.append("")
    L.append("| 算法 | 完成 | 平均等待 | P95 等待 | 最大等待 | 平均响应 | 完成用时 | 吞吐(/s) | 公平性 |")
    L.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for r in results:
        m = r.metrics
        L.append(f'| {r.algo} | {m["served"]}/{m["total"]} | {m["avg_wait"]:.1f} | {m["p95_wait"]:.1f} | '
                 f'{m["max_wait"]:.1f} | {m["avg_turn"]:.1f} | {m["makespan"]:.0f} | '
                 f'{m["throughput"]:.1f} | {m["fairness"]:.1f}× |')
    L.append("")

    ok = [r for r in results if r.metrics.get("served")]
    if ok:
        best_avg = min(ok, key=lambda r: r.metrics["avg_wait"])
        best_max = min(ok, key=lambda r: r.metrics["max_wait"])
        worst_max = max(ok, key=lambda r: r.metrics["max_wait"])
        best_tp = max(ok, key=lambda r: r.metrics["throughput"])
        L.append("## 三、结论")
        L.append("")
        L.append(f'1. **平均等待最短**：{best_avg.algo}，{best_avg.metrics["avg_wait"]:.1f} ms。')
        L.append(f'2. **最坏等待最低**：{best_max.algo}，{best_max.metrics["max_wait"]:.1f} ms '
                 f'（公平性 {best_max.metrics["fairness"]:.1f}×）。')
        L.append(f'3. **吞吐最高**：{best_tp.algo}，{best_tp.metrics["throughput"]:.1f} 请求/秒。')
        L.append(f'4. **尾延迟最差**：{worst_max.algo}，最坏等待 {worst_max.metrics["max_wait"]:.1f} ms，'
                 f'是平均值的 {worst_max.metrics["fairness"]:.1f} 倍。')
        L.append("")
        if worst_max.metrics["fairness"] >= 5:
            L.append(f'> **饥饿信号**：{worst_max.algo} 的最坏等待达到中位数的 '
                     f'{worst_max.metrics["fairness"]:.1f} 倍，说明存在被持续插队、长期得不到服务的请求。'
                     f'这正是「平均等待很短」掩盖不了的代价。')
            L.append("")
        L.append("**读法**")
        L.append("")
        L.append("- 平均等待看「大多数人爽不爽」，最大等待与 P95 看「少数人会不会被饿死」。")
        L.append("- 负载 ρ>1 时队列持续增长，SSTF 会一直挑最近的新请求，远端旧请求无限延期。")
        L.append("- SCAN/C-SCAN 的等待有一个扫描周期的上界，代价是平均等待变长。")
        L.append("")

    L.append("## 四、各算法最坏等待的三个请求")
    L.append("")
    for r in results:
        worst = sorted(r.records, key=lambda x: x.wait, reverse=True)[:3]
        if not worst:
            continue
        L.append(f'### {r.algo} · 最坏 {r.metrics["max_wait"]:.1f} ms')
        L.append("")
        L.append("| 磁道 | 到达(ms) | 开始服务(ms) | 等待(ms) |")
        L.append("| ---: | ---: | ---: | ---: |")
        for x in worst:
            L.append(f"| {x.track} | {x.at:.1f} | {x.start:.1f} | {x.wait:.1f} |")
        L.append("")

    L.append("## 五、口径")
    L.append("")
    L.append("1. 请求按到达时刻进入队列，磁头只在服务间隙挑选，服务途中新到请求不打断当前服务。")
    L.append("2. 服务耗时 = 移动磁道数 × 每磁道寻道时间 + 一个平均旋转延迟。")
    L.append("3. 等待 = 开始服务时刻 − 到达时刻；响应 = 完成时刻 − 到达时刻。")
    L.append("4. 公平性 = 最大等待 ÷ 等待中位数，越大说明越有请求被长期忽视。")
    L.append("5. 队列为空时磁头空转，时间跳到下一个到达，空转时间单独统计。")
    L.append("")
    return "\n".join(L)
