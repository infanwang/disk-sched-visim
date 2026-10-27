"""动态到达（带排队）仿真。

与静态批处理的区别：请求带到达时刻，磁头只在「已经到达且未服务」的队列里挑选，
服务途中新到的请求不打断当前服务。这样 SSTF 的饥饿、SCAN 的等待上界才看得见。

时间单位：毫秒。磁头速度 = 每跨一条磁道 seek_ms_per_track。
服务耗时 = 移动时间 + 一个平均旋转延迟。
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Dict, List, Optional, Sequence, Tuple

from .engine import ALGO_INFO, ALGOS, DiskConfig

CIRCULAR = ("C-SCAN", "C-LOOK")


@dataclass
class Arrival:
    idx: int
    track: int
    at: float


@dataclass
class Rec:
    idx: int
    track: int
    at: float
    start: float
    finish: float

    @property
    def wait(self) -> float:
        return self.start - self.at

    @property
    def turnaround(self) -> float:
        return self.finish - self.at

    def as_dict(self) -> dict:
        return {
            "idx": self.idx, "track": self.track, "at": round(self.at, 2),
            "start": round(self.start, 2), "finish": round(self.finish, 2),
            "wait": round(self.wait, 2), "turnaround": round(self.turnaround, 2),
        }


@dataclass
class DynResult:
    algo: str
    records: List[Rec]
    points: List[Dict[str, float]]
    metrics: Dict[str, float]

    def as_dict(self) -> dict:
        return {
            "algo": self.algo,
            "name": ALGO_INFO[self.algo]["name"],
            "records": [r.as_dict() for r in self.records],
            "points": self.points,
            "metrics": self.metrics,
        }


def _pct(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return s[k]


def _choose(algo: str, pending: List[Arrival], pos: int, up: bool,
            cfg: DiskConfig) -> Tuple[Optional[Arrival], bool, List[dict], float, float]:
    """返回 (目标请求, 新方向, 额外的空走点, 空走距离, 空走耗时)。

    额外空走只在 SCAN 走到端点、C-SCAN 回卷时出现。
    """
    extra: List[dict] = []
    if algo == "FCFS":
        return min(pending, key=lambda r: (r.at, r.idx)), up, extra, 0.0, 0.0
    if algo == "SSTF":
        return (min(pending, key=lambda r: (abs(r.track - pos), r.at, r.idx)),
                up, extra, 0.0, 0.0)

    ahead = [r for r in pending if (r.track >= pos if up else r.track <= pos)]
    if ahead:
        return (min(ahead, key=lambda r: (abs(r.track - pos), r.at)),
                up, extra, 0.0, 0.0)

    if algo in ("SCAN", "LOOK"):
        if algo == "LOOK":
            # 本方向没有请求：就地反向，最近的请求在反方向
            return (min(pending, key=lambda r: (abs(r.track - pos), r.at)),
                    not up, extra, 0.0, 0.0)
        # SCAN：先空走到端点，再反向
        end = cfg.tracks - 1 if up else 0
        d = abs(end - pos)
        if d:
            extra.append({"track": end, "kind": "turn"})
        return (min(pending, key=lambda r: (abs(r.track - pos), r.at)),
                not up, extra, float(d), d * cfg.seek_ms_per_track)

    # C-SCAN / C-LOOK：回卷到另一端
    if algo == "C-SCAN":
        other = 0 if up else cfg.tracks - 1
        d = abs(other - pos)
        if d:
            extra.append({"track": other, "kind": "wrap"})
        target = min(pending, key=lambda r: (r.track if up else -r.track))
        return (target, up, extra, float(d if cfg.count_return else 0),
                d * cfg.seek_ms_per_track if cfg.count_return else 0.0)

    # C-LOOK：直接回卷到另一端最近的待服务请求
    target = min(pending, key=lambda r: (r.track if up else -r.track))
    d = abs(target.track - pos)
    if d:
        extra.append({"track": target.track, "kind": "wrap"})
    return (target, up, extra, float(d if cfg.count_return else 0),
            d * cfg.seek_ms_per_track if cfg.count_return else 0.0)


def simulate_dynamic(cfg: DiskConfig, arrivals: Sequence[Tuple[float, int]],
                     algo: str, max_events: Optional[int] = None) -> DynResult:
    """arrivals: [(到达时刻 ms, 磁道号), ...]，顺序不限。"""
    cfg = cfg.normalized()
    if algo not in ALGOS:
        raise ValueError(f"未知算法 {algo}")

    clean: List[Arrival] = []
    for i, (at, track) in enumerate(arrivals):
        try:
            t = float(at)
            tr = int(track)
        except (TypeError, ValueError):
            continue
        if 0 <= tr < cfg.tracks and t >= 0:
            clean.append(Arrival(len(clean), tr, t))
    clean.sort(key=lambda r: (r.at, r.idx))
    n = len(clean)
    if not n:
        return DynResult(algo, [], [], {"served": 0, "total": 0})

    pending: List[Arrival] = []
    idx = 0
    pos = cfg.start
    up = cfg.direction == "up"
    now = 0.0
    distance = 0.0
    idle = 0.0
    records: List[Rec] = []
    points: List[Dict[str, float]] = [{"t": 0.0, "track": pos, "kind": "start"}]
    guard = max_events or (60 * n + 500)

    steps = 0
    while len(records) < n and steps < guard:
        steps += 1
        # 先把「此刻已经到达」的请求全部入队（关键：队列非空时也要继续收新请求）
        while idx < n and clean[idx].at <= now + 1e-9:
            pending.append(clean[idx])
            idx += 1

        if not pending:
            if idx >= n:
                break
            # 队列空 → 磁头空转，时间跳到下一个到达
            if clean[idx].at > now:
                idle += clean[idx].at - now
                now = clean[idx].at
                points.append({"t": round(now, 2), "track": pos, "kind": "idle"})
            continue

        target, new_up, extra, extra_dist, extra_time = _choose(algo, pending, pos, up, cfg)
        if target is None:
            break

        if extra:
            for pt in extra:
                pos = pt["track"]
                points.append({"t": round(now + extra_time, 2), "track": pos,
                               "kind": pt["kind"]})
            now += extra_time
            distance += extra_dist
            up = new_up
            # 回卷后位置已在对端，但目标可能等于当前位（无需再动）
            if target.track == pos:
                pass

        dist = abs(target.track - pos)
        travel = dist * cfg.seek_ms_per_track
        start = now + travel
        finish = start + cfg.rotational_ms
        records.append(Rec(target.idx, target.track, target.at, start, finish))
        distance += dist
        now = finish
        pos = target.track
        up = new_up
        points.append({"t": round(now, 2), "track": pos, "kind": "seek"})
        pending.remove(target)

    waits = [r.wait for r in records]
    turns = [r.turnaround for r in records]
    med = median(waits) if waits else 0.0
    metrics = {
        "served": len(records),
        "total": n,
        "avg_wait": round(sum(waits) / len(waits), 2) if waits else 0.0,
        "med_wait": round(med, 2),
        "p95_wait": round(_pct(waits, 0.95), 2),
        "max_wait": round(max(waits), 2) if waits else 0.0,
        "avg_turn": round(sum(turns) / len(turns), 2) if turns else 0.0,
        "max_turn": round(max(turns), 2) if turns else 0.0,
        "makespan": round(now, 2),
        "idle_ms": round(idle, 2),
        "distance": round(distance, 1),
        "throughput": round(len(records) / (now / 1000.0), 2) if now > 0 else 0.0,
        "fairness": round((max(waits) / med), 1) if med > 0 else 0.0,
        "starved": sum(1 for w in waits if w > 5 * med) if med > 0 else 0,
    }
    return DynResult(algo, records, points, metrics)


def simulate_dynamic_multi(cfg: DiskConfig, arrivals: Sequence[Tuple[float, int]],
                           algos: Optional[Sequence[str]] = None) -> List[DynResult]:
    names = [a for a in (algos or ALGOS) if a in ALGOS]
    return [simulate_dynamic(cfg, arrivals, a) for a in names]


def compare_dynamic(results: Sequence[DynResult]) -> Dict[str, object]:
    if not results:
        return {}
    ok = [r for r in results if r.metrics.get("served")]
    if not ok:
        return {}
    best_wait = min(ok, key=lambda r: (r.metrics["avg_wait"], r.metrics["max_wait"]))
    best_worst = min(ok, key=lambda r: r.metrics["max_wait"])
    best_tp = max(ok, key=lambda r: r.metrics["throughput"])
    best_fair = min(ok, key=lambda r: r.metrics["fairness"] or 9e9)
    return {
        "best_wait": best_wait.algo,
        "best_wait_value": best_wait.metrics["avg_wait"],
        "best_worst": best_worst.algo,
        "best_worst_value": best_worst.metrics["max_wait"],
        "best_throughput": best_tp.algo,
        "best_throughput_value": best_tp.metrics["throughput"],
        "most_fair": best_fair.algo,
        "most_fair_value": best_fair.metrics["fairness"],
    }
