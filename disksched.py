#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""磁盘调度算法可视化仿真 —— 统一入口。

    python disksched.py run --preset classic --detail
    python disksched.py gen --pattern bimodal --count 10 --seed 7
    python disksched.py report --generate hotspot -o 报告.md
    python disksched.py bench --cases 100
    python disksched.py serve
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from disk_sched.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
