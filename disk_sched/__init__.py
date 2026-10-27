"""磁盘调度仿真器核心包。"""

from .engine import (ALGO_INFO, ALGOS, DiskConfig, Result, compare, sanitize,
                     simulate, simulate_one)
from .generator import PATTERNS, PRESETS, generate, parse_sequence

__all__ = [
    "ALGOS", "ALGO_INFO", "DiskConfig", "Result", "simulate", "simulate_one",
    "compare", "sanitize", "generate", "parse_sequence", "PATTERNS", "PRESETS",
]

__version__ = "1.0.0"
