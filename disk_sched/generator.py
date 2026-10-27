"""访问序列生成器：随机 / 顺序 / 热点 / 双峰 / 交替 / 幂律，以及几个经典例题预设。

全部使用固定 seed 的可复现随机数，命令行与网页端给出同一 seed 会得到同一序列。
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Optional

PATTERNS: Dict[str, Dict[str, str]] = {
    "random": {"name": "均匀随机", "desc": "磁道号在 0..N-1 上均匀分布，最常规的测试基准"},
    "sequential": {"name": "顺序访问", "desc": "连续递增/递减，模拟顺序读写大文件"},
    "hotspot": {"name": "热点集中", "desc": "70% 落在 12% 的磁道带内，模拟索引与元数据集中"},
    "bimodal": {"name": "双峰分布", "desc": "两个相距很远的簇，SSTF 的典型最坏情况"},
    "alternating": {"name": "高低交替", "desc": "在低位区与高位区之间来回跳，考察方向连续性"},
    "zipf": {"name": "幂律偏斜", "desc": "少数磁道被高频访问，模拟真实文件系统"},
}

PRESETS: Dict[str, Dict[str, object]] = {
    "classic": {
        "name": "教材经典例题",
        "desc": "王道/汤小丹通用例题：起点 53，磁头向增大方向",
        "tracks": 200,
        "start": 53,
        "direction": "up",
        "sequence": [98, 183, 37, 122, 14, 124, 65, 67],
    },
    "worst_sstf": {
        "name": "SSTF 最坏情况",
        "desc": "两端交替，SSTF 会被反复拉回，SCAN 更稳",
        "tracks": 200,
        "start": 100,
        "direction": "up",
        "sequence": [5, 195, 8, 192, 12, 188, 16, 184, 20, 180],
    },
    "one_side": {
        "name": "请求全在一侧",
        "desc": "所有请求都小于起点：考察 LOOK 与 SCAN 的空跑差异",
        "tracks": 200,
        "start": 180,
        "direction": "up",
        "sequence": [20, 45, 60, 75, 90, 110, 130, 150],
    },
    "edge": {
        "name": "贴边与端点",
        "desc": "含 0 与 N-1，检查端点服务与零距离换向",
        "tracks": 200,
        "start": 100,
        "direction": "down",
        "sequence": [0, 199, 1, 198, 100, 101, 99, 50],
    },
}


def _clamp(x: int, tracks: int) -> int:
    return max(0, min(tracks - 1, int(x)))


def _unique(values: List[int], count: int, tracks: int, rng: random.Random) -> List[int]:
    """去重并补足 count 个（轨数不够时允许少于 count）。"""
    seen, out = set(), []
    for v in values:
        v = _clamp(v, tracks)
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
        if len(out) >= count:
            break
    guard = 0
    while len(out) < count and len(seen) < tracks and guard < count * 40:
        guard += 1
        v = rng.randrange(tracks)
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def generate(pattern: str = "random", count: int = 12, tracks: int = 200,
             seed: Optional[int] = None, start: Optional[int] = None,
             sorted_out: bool = False) -> List[int]:
    """生成访问序列。

    pattern 取 PATTERNS 的键；count 为请求数（轨数不足时自动截断）；
    sorted_out=True 时按生成方向排序输出（更像顺序型负载）。
    """
    pattern = (pattern or "random").lower()
    if pattern not in PATTERNS:
        pattern = "random"
    count = max(1, min(int(count), tracks))
    rng = random.Random(seed)

    if pattern == "random":
        vals = [rng.randrange(tracks) for _ in range(count * 3)]

    elif pattern == "sequential":
        span = max(1, min(tracks, rng.randint(max(4, count * 2), tracks)))
        base = rng.randrange(0, max(1, tracks - span + 1))
        step = rng.randint(1, max(2, span // max(1, count // 2) or 2))
        vals = [base + i * step + rng.randint(-1, 1) for i in range(count * 2)]

    elif pattern == "hotspot":
        width = max(4, int(tracks * 0.12))
        lo = rng.randrange(0, max(1, tracks - width))
        vals = []
        for _ in range(count * 3):
            if rng.random() < 0.7:
                vals.append(rng.randrange(lo, lo + width))
            else:
                vals.append(rng.randrange(tracks))

    elif pattern == "bimodal":
        mid = tracks // 2
        vals = []
        for _ in range(count * 3):
            if rng.random() < 0.5:
                vals.append(rng.randrange(0, max(1, mid // 3)))
            else:
                vals.append(rng.randrange(max(1, tracks - mid // 3), tracks))

    elif pattern == "alternating":
        vals = []
        for i in range(count * 3):
            if i % 2 == 0:
                vals.append(rng.randrange(0, max(1, tracks // 8)))
            else:
                vals.append(rng.randrange(max(1, tracks - tracks // 8), tracks))

    else:  # zipf
        s = 1.15
        weights = [1.0 / math.pow(i + 1, s) for i in range(tracks)]
        total = sum(weights)
        acc, cdf = 0.0, []
        for w in weights:
            acc += w / total
            cdf.append(acc)
        vals = []
        for _ in range(count * 3):
            r = rng.random()
            lo, hi = 0, tracks - 1
            while lo < hi:
                mid2 = (lo + hi) // 2
                if cdf[mid2] < r:
                    lo = mid2 + 1
                else:
                    hi = mid2
            # 幂律偏向 0 附近，随机翻转让方向不固定
            vals.append(lo if rng.random() < 0.5 else tracks - 1 - lo)

    out = _unique(vals, count, tracks, rng)
    if sorted_out:
        out = sorted(out, reverse=(start is not None and start > tracks // 2))
    return out


def parse_sequence(text: str) -> List[int]:
    """从 "98,183,37" 或 "98 183 37" 或 "98\n183" 中解析磁道号。"""
    if not text:
        return []
    buf = ""
    for ch in str(text):
        buf += ch if (ch.isdigit() or ch == "-") else " "
    return [int(x) for x in buf.split() if x not in ("-", "")]
