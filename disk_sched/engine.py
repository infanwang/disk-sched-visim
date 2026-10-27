"""磁盘调度算法内核：FCFS / SSTF / SCAN / C-SCAN / LOOK / C-LOOK。

只依赖 Python 标准库。所有算法共用同一套「磁头路径 -> 分段 -> 指标」的计算口径，
保证命令行与网页端结果完全一致。

约定
----
* 磁道编号 0 .. tracks-1，0 在最外（或最内，不影响计算）。
* direction="up" 表示磁头朝磁道号增大方向移动。
* 重复请求会被合并（同一磁道的多次访问对调度没有意义）。
* SCAN 是否走到物理端点由 scan_to_end 控制；C-SCAN 按定义一定走到端点。
* C-SCAN / C-LOOK 的空返回段是否计入寻道长度由 count_return 控制（默认计入，
  与多数 408 教材口径一致），报告里同时给出两种口径。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

ALGOS: List[str] = ["FCFS", "SSTF", "SCAN", "C-SCAN", "LOOK", "C-LOOK"]

ALGO_INFO: Dict[str, Dict[str, str]] = {
    "FCFS": {
        "name": "先来先服务",
        "short": "按请求顺序服务，实现最简单",
        "trait": "绝对公平但寻道距离通常最大，磁头来回横跳。",
    },
    "SSTF": {
        "name": "最短寻道时间优先",
        "short": "每次挑离当前磁头最近的请求",
        "trait": "平均寻道最短，但远端请求可能饥饿，方向不连续。",
    },
    "SCAN": {
        "name": "扫描算法（电梯）",
        "short": "沿当前方向扫到端点再反向",
        "trait": "不会饥饿，响应较均匀；必须走到端点，边缘多跑一段。",
    },
    "C-SCAN": {
        "name": "循环扫描",
        "short": "单向扫到端点，空返另一端后继续单向扫",
        "trait": "各磁道等待最均匀，代价是返回段白跑一遍。",
    },
    "LOOK": {
        "name": "LOOK",
        "short": "SCAN 改良：扫到本方向最后一个请求就反向",
        "trait": "省掉走向端点的空跑，工程上最常用。",
    },
    "C-LOOK": {
        "name": "C-LOOK",
        "short": "C-SCAN 改良：扫到最后一个请求就空返另一端",
        "trait": "兼顾均匀与空跑距离，是 C-SCAN 的实用版。",
    },
}


@dataclass
class DiskConfig:
    """磁盘与仿真参数。"""

    tracks: int = 200                 # 磁道数，编号 0 .. tracks-1
    start: int = 53                   # 初始磁头位置
    direction: str = "up"             # up = 磁道号增大方向, down = 减小
    seek_ms_per_track: float = 0.15   # 每跨一条磁道的寻道时间（用于估算耗时）
    rotational_ms: float = 4.17       # 每服务一个请求的平均旋转延迟（7200rpm）
    scan_to_end: bool = True          # SCAN 是否真的走到端点
    count_return: bool = True         # C-SCAN / C-LOOK 的空返回段是否计入

    def normalized(self) -> "DiskConfig":
        tracks = max(2, int(self.tracks))
        return DiskConfig(
            tracks=tracks,
            start=min(max(int(self.start), 0), tracks - 1),
            direction="down" if str(self.direction).lower() in ("down", "desc", "-", "left") else "up",
            seek_ms_per_track=max(0.0, float(self.seek_ms_per_track)),
            rotational_ms=max(0.0, float(self.rotational_ms)),
            scan_to_end=bool(self.scan_to_end),
            count_return=bool(self.count_return),
        )


@dataclass
class Segment:
    """一段磁头移动。kind: seek=服务, turn=空走到端点, wrap=循环返回。"""

    src: int
    dst: int
    dist: int
    counted: bool
    kind: str

    def as_dict(self) -> dict:
        return {"from": self.src, "to": self.dst, "dist": self.dist,
                "counted": self.counted, "kind": self.kind}


@dataclass
class Result:
    algo: str
    order: List[int]
    path: List[int]
    segments: List[Segment]
    metrics: Dict[str, float] = field(default_factory=dict)
    times: List[float] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "algo": self.algo,
            "name": ALGO_INFO[self.algo]["name"],
            "order": self.order,
            "path": self.path,
            "segments": [s.as_dict() for s in self.segments],
            "metrics": self.metrics,
            "times": [round(t, 3) for t in self.times],
        }


def sanitize(cfg: DiskConfig, requests: Sequence) -> List[int]:
    """去越界、去重，保持原始顺序。"""
    seen, out = set(), []
    for r in requests:
        try:
            v = int(float(r))
        except (TypeError, ValueError):
            continue
        if v < 0 or v >= cfg.tracks or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _finish(cfg: DiskConfig, algo: str, order: List[int], path: List[int],
            kinds: List[str]) -> Result:
    """由路径节点与每段类型生成指标。kinds[i] 描述 path[i] -> path[i+1]。"""
    segs: List[Segment] = []
    for i, kind in enumerate(kinds):
        counted = True
        if kind in ("wrap", "wrap_seek") and not cfg.count_return:
            counted = False
        segs.append(Segment(path[i], path[i + 1], abs(path[i + 1] - path[i]), counted, kind))

    times: List[float] = []
    t = 0.0
    for s in segs:
        if s.counted:
            t += s.dist * cfg.seek_ms_per_track
        if s.kind in ("seek", "wrap_seek"):
            t += cfg.rotational_ms
            times.append(t)

    total = sum(s.dist for s in segs if s.counted)
    n = max(1, len(order))
    counted = [s for s in segs if s.counted and s.dist > 0]

    reversals, prev = 0, 0
    for s in counted:
        d = 1 if s.dst > s.src else -1
        if prev and d != prev:
            reversals += 1
        prev = d

    avg_resp = sum(times) / len(times) if times else 0.0
    metrics = {
        "total_seek": total,
        "avg_seek": round(total / n, 2),
        "max_step": max((s.dist for s in counted), default=0),
        "reversals": reversals,
        "far_track": max(path) if path else cfg.start,
        "near_track": min(path) if path else cfg.start,
        "makespan_ms": round(times[-1], 3) if times else 0.0,
        "avg_response_ms": round(avg_resp, 3),
        "max_response_ms": round(max(times), 3) if times else 0.0,
        "spread": round((max(times) / avg_resp), 2) if times and avg_resp else 0.0,
        "requests": len(order),
    }
    return Result(algo=algo, order=order, path=path, segments=segs,
                  metrics=metrics, times=times)


class _Builder:
    """把「服务/转向/返回」三种动作翻译成 path + kinds，避免重复代码。"""

    def __init__(self, cfg: DiskConfig):
        self.cfg = cfg
        self.path = [cfg.start]
        self.kinds: List[str] = []
        self.order: List[int] = []
        self.cur = cfg.start

    def move(self, track: int, kind: str = "seek", serve: bool = True) -> None:
        track = max(0, min(self.cfg.tracks - 1, int(track)))
        if track == self.cur and kind == "seek":
            # 已经停在目标磁道：记一段 0 距离的服务，保证指标与时间轴对齐
            self.path.append(track)
            self.kinds.append("seek")
        elif track == self.cur:
            return
        else:
            self.path.append(track)
            self.kinds.append(kind)
        if serve:
            self.order.append(track)
        self.cur = track

    def result(self, algo: str) -> Result:
        return _finish(self.cfg, algo, self.order, self.path, self.kinds)


def run_fcfs(cfg: DiskConfig, requests: List[int]) -> Result:
    b = _Builder(cfg)
    for t in requests:
        b.move(t)
    return b.result("FCFS")


def run_sstf(cfg: DiskConfig, requests: List[int]) -> Result:
    pending = list(requests)
    b = _Builder(cfg)
    direction = 1 if cfg.direction == "up" else -1
    while pending:
        best, best_key = None, None
        for r in pending:
            dist = abs(r - b.cur)
            moving = 1 if r > b.cur else (-1 if r < b.cur else 0)
            key = (dist, 0 if moving == direction else 1, r)
            if best_key is None or key < best_key:
                best, best_key = r, key
        pending.remove(best)
        prev = b.cur
        b.move(best)
        if best != prev:
            direction = 1 if best > prev else -1
    return b.result("SSTF")


def _groups(cfg: DiskConfig, requests: List[int], circular: bool):
    up = cfg.direction == "up"
    if up:
        first = sorted(r for r in requests if r >= cfg.start)
        second = sorted((r for r in requests if r < cfg.start), reverse=not circular)
    else:
        first = sorted((r for r in requests if r <= cfg.start), reverse=True)
        second = sorted((r for r in requests if r > cfg.start), reverse=circular)
    return first, second


def _scan_like(cfg: DiskConfig, requests: List[int], algo: str,
               to_end: bool, circular: bool) -> Result:
    up = cfg.direction == "up"
    first, second = _groups(cfg, requests, circular)
    b = _Builder(cfg)
    remaining = set(requests)

    for t in first:
        b.move(t)
        remaining.discard(t)

    end = cfg.tracks - 1 if up else 0
    other = 0 if up else cfg.tracks - 1

    if circular:
        # 1) 单向扫到头：C-SCAN 到物理端点，C-LOOK 只到本方向最后一个请求
        anchor = end if to_end else (first[-1] if first else b.cur)
        if b.cur != anchor:
            if anchor in remaining:
                b.move(anchor)
                remaining.discard(anchor)
            else:
                b.move(anchor, kind="turn", serve=False)
        # 2) 空返回另一端（C-SCAN 到端点，C-LOOK 到另一端首个请求）
        wrap_target = other if to_end else (second[0] if second else other)
        if b.cur != wrap_target:
            if wrap_target in remaining:
                b.move(wrap_target, kind="wrap_seek")
                remaining.discard(wrap_target)
            else:
                b.move(wrap_target, kind="wrap", serve=False)
        # 3) 同方向继续服务剩下的
        for t in second:
            if t in remaining:
                b.move(t)
                remaining.discard(t)
    else:
        if to_end and b.cur != end:
            if end in remaining:
                b.move(end)
                remaining.discard(end)
            else:
                b.move(end, kind="turn", serve=False)
        for t in second:
            if t in remaining:
                b.move(t)
                remaining.discard(t)

    # 兜底：任何未服务的请求按顺序补上（极端参数下可能发生）
    for t in requests:
        if t in remaining:
            b.move(t)
            remaining.discard(t)

    return b.result(algo)


def run_scan(cfg: DiskConfig, requests: List[int]) -> Result:
    return _scan_like(cfg, requests, "SCAN", cfg.scan_to_end, circular=False)


def run_cscan(cfg: DiskConfig, requests: List[int]) -> Result:
    return _scan_like(cfg, requests, "C-SCAN", True, circular=True)


def run_look(cfg: DiskConfig, requests: List[int]) -> Result:
    return _scan_like(cfg, requests, "LOOK", False, circular=False)


def run_clook(cfg: DiskConfig, requests: List[int]) -> Result:
    return _scan_like(cfg, requests, "C-LOOK", False, circular=True)


_RUNNERS = {
    "FCFS": run_fcfs,
    "SSTF": run_sstf,
    "SCAN": run_scan,
    "C-SCAN": run_cscan,
    "LOOK": run_look,
    "C-LOOK": run_clook,
}


def simulate(config: DiskConfig, requests: Sequence,
             algos: Optional[Sequence[str]] = None) -> List[Result]:
    cfg = config.normalized()
    req = sanitize(cfg, requests)
    if not req:
        return []
    names = [a for a in (algos or ALGOS) if a in _RUNNERS]
    return [_RUNNERS[a](cfg, list(req)) for a in names]


def simulate_one(config: DiskConfig, requests: Sequence, algo: str) -> Optional[Result]:
    cfg = config.normalized()
    req = sanitize(cfg, requests)
    if algo not in _RUNNERS or not req:
        return None
    return _RUNNERS[algo](cfg, list(req))


def compare(results: Sequence[Result]) -> Dict[str, object]:
    """谁赢哪一项。"""
    if not results:
        return {}
    m = lambda r: r.metrics
    best_seek = min(results, key=lambda r: (m(r)["total_seek"], m(r)["avg_response_ms"]))
    best_resp = min(results, key=lambda r: (m(r)["avg_response_ms"], m(r)["total_seek"]))
    best_worst = min(results, key=lambda r: m(r)["max_response_ms"])
    fair = min(results, key=lambda r: m(r)["spread"])
    turns = min(results, key=lambda r: m(r)["reversals"])
    return {
        "best_seek": best_seek.algo,
        "best_seek_value": m(best_seek)["total_seek"],
        "best_response": best_resp.algo,
        "best_response_value": m(best_resp)["avg_response_ms"],
        "best_worst_case": best_worst.algo,
        "best_worst_case_value": m(best_worst)["max_response_ms"],
        "most_fair": fair.algo,
        "most_fair_value": m(fair)["spread"],
        "fewest_turns": turns.algo,
        "fewest_turns_value": m(turns)["reversals"],
    }
