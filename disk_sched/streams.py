"""到达流生成：给动态模式造「请求按时间到达」的负载。

输出 [ (到达时刻 ms, 磁道号), ... ]，按时间升序。
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

STREAMS: Dict[str, Dict[str, str]] = {
    "poisson": {
        "name": "泊松到达",
        "desc": "到达时刻在时间轴上均匀随机，磁道均匀分布——最中性的基准",
    },
    "steady": {
        "name": "匀速到达",
        "desc": "请求间隔固定，磁道均匀——只看纯粹的调度差异",
    },
    "burst": {
        "name": "突发成簇",
        "desc": "几毫秒内涌入一批，然后空一段——模拟高峰与空转",
    },
    "hotspot": {
        "name": "热点漂移",
        "desc": "85% 请求落在缓慢移动的热点带内——SSTF 会被热点牵着走",
    },
    "adversarial": {
        "name": "饥饿诱导",
        "desc": "开头放一个远端请求，随后持续在近端灌请求——专治 SSTF",
    },
    "zipf": {
        "name": "幂律偏斜",
        "desc": "少数磁道被高频访问，接近真实文件系统",
    },
}


def _clamp(x: int, tracks: int) -> int:
    return max(0, min(tracks - 1, int(x)))


def generate_stream(pattern: str = "poisson", count: int = 60, tracks: int = 200,
                    seed: Optional[int] = None, span_ms: float = 3000.0,
                    start: Optional[int] = None) -> List[Tuple[float, int]]:
    pattern = (pattern or "poisson").lower()
    if pattern not in STREAMS:
        pattern = "poisson"
    count = max(1, min(int(count), 5000))
    span_ms = max(1.0, float(span_ms))
    rng = random.Random(seed)
    start = tracks // 2 if start is None else _clamp(start, tracks)
    events: List[Tuple[float, int]] = []

    if pattern == "steady":
        gap = span_ms / count
        for i in range(count):
            at = i * gap + rng.uniform(0, gap * 0.15)
            events.append((min(span_ms, at), rng.randrange(tracks)))

    elif pattern == "poisson":
        times = sorted(rng.uniform(0, span_ms) for _ in range(count))
        for at in times:
            events.append((at, rng.randrange(tracks)))

    elif pattern == "burst":
        i = 0
        cursor = rng.uniform(0, span_ms * 0.05)
        while i < count and cursor < span_ms:
            size = rng.randint(3, 7)
            base = rng.randrange(tracks)
            for _ in range(size):
                if i >= count:
                    break
                at = cursor + rng.uniform(0, max(1.0, span_ms * 0.006))
                events.append((min(span_ms, at), _clamp(base + rng.randint(-12, 12), tracks)))
                i += 1
            cursor += rng.uniform(span_ms * 0.03, span_ms * 0.12)

    elif pattern == "hotspot":
        band = max(4, int(tracks * 0.08))
        for i in range(count):
            progress = i / max(1, count - 1)
            center = int(tracks * 0.15 + progress * tracks * 0.7)
            at = min(span_ms, rng.uniform(0, span_ms) * (0.85 + 0.3 * progress))
            if rng.random() < 0.85:
                tr = center + rng.randint(-band, band)
            else:
                tr = rng.randrange(tracks)
            events.append((at, _clamp(tr, tracks)))

    elif pattern == "adversarial":
        # 先让近端请求把队列灌满，再放一个远端请求：SSTF 从此再也看不到它
        far = tracks - 1 if start < tracks / 2 else 0
        band = max(3, int(tracks * 0.04))
        step = span_ms / max(1, count - 1)
        for i in range(count - 1):
            at = i * step
            tr = start + rng.randint(-band, band)
            events.append((min(span_ms, at), _clamp(tr, tracks)))
        events.append((round(span_ms * 0.15, 2), far))

    else:  # zipf
        for _ in range(count):
            at = rng.uniform(0, span_ms)
            tr = int((rng.random() ** 2.4) * tracks)
            if rng.random() < 0.5:
                tr = tracks - 1 - tr
            events.append((at, _clamp(tr, tracks)))

    events.sort(key=lambda e: (e[0], e[1]))
    return [(round(at, 2), tr) for at, tr in events]
