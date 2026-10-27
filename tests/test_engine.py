"""算法正确性与边界测试：python -m pytest -q 或 python tests/test_engine.py。"""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from disk_sched.engine import (ALGOS, DiskConfig, compare, sanitize, simulate,
                               simulate_one)
from disk_sched.generator import PATTERNS, PRESETS, generate, parse_sequence

CLASSIC = [98, 183, 37, 122, 14, 124, 65, 67]
CFG = DiskConfig(tracks=200, start=53, direction="up")

# 教材经典例题，口径：SCAN 走到端点，C-SCAN 返回段计入
EXPECTED = {
    "FCFS": 640,
    "SSTF": 236,
    "SCAN": 331,
    "C-SCAN": 382,
    "LOOK": 299,
    "C-LOOK": 322,
}


def test_classic_totals():
    for algo, want in EXPECTED.items():
        r = simulate_one(CFG, CLASSIC, algo)
        assert r is not None, algo
        assert r.metrics["total_seek"] == want, f"{algo}: {r.metrics['total_seek']} != {want}"


def test_order_matches_total():
    for algo in ALGOS:
        r = simulate_one(CFG, CLASSIC, algo)
        walked = sum(s.dist for s in r.segments if s.counted)
        assert walked == r.metrics["total_seek"]


def test_scan_service_order():
    r = simulate_one(CFG, CLASSIC, "SCAN")
    assert r.order == [65, 67, 98, 122, 124, 183, 37, 14], r.order
    assert 199 in r.path, "SCAN 应向端点走到 199"


def test_look_does_not_touch_end():
    r = simulate_one(CFG, CLASSIC, "LOOK")
    assert max(r.path) == 183, r.path


def test_cscan_return_toggle():
    cfg = DiskConfig(tracks=200, start=53, direction="up", count_return=False)
    r = simulate_one(cfg, CLASSIC, "C-SCAN")
    # 382 - 199（返回段） = 183
    assert r.metrics["total_seek"] == 183, r.metrics["total_seek"]


def test_scan_to_end_toggle():
    cfg = DiskConfig(tracks=200, start=53, direction="up", scan_to_end=False)
    r = simulate_one(cfg, CLASSIC, "SCAN")
    assert r.metrics["total_seek"] == 299, r.metrics["total_seek"]
    assert max(r.path) == 183


def test_direction_down():
    cfg = DiskConfig(tracks=200, start=53, direction="down")
    a = simulate_one(cfg, CLASSIC, "SCAN")
    b = simulate_one(cfg, CLASSIC, "SCAN")
    assert a.order == b.order
    assert a.order[0] < 53, a.order


def test_sanitize():
    cfg = DiskConfig(tracks=100)
    assert sanitize(cfg, [5, 5, -3, 100, 250, 7]) == [5, 7]


def test_every_request_served_once():
    rng = random.Random(20261)
    for _ in range(60):
        tracks = rng.choice([50, 100, 200, 500])
        start = rng.randrange(tracks)
        direction = rng.choice(["up", "down"])
        cfg = DiskConfig(tracks=tracks, start=start, direction=direction)
        seq = rng.sample(range(tracks), rng.randint(1, min(tracks, 25)))
        results = simulate(cfg, seq)
        assert len(results) == len(ALGOS)
        for r in results:
            assert sorted(r.order) == sorted(seq), (r.algo, r.order, seq)
            assert all(0 <= t < tracks for t in r.path)


def test_empty_and_out_of_range():
    assert simulate(CFG, []) == []
    assert simulate(CFG, [-1, 500]) == []
    assert simulate_one(CFG, CLASSIC, "NOPE") is None


def test_compare_keys():
    c = compare(simulate(CFG, CLASSIC))
    assert c["best_seek"] == "SSTF"
    assert c["fewest_turns"] in ALGOS


def test_single_request():
    for algo in ALGOS:
        r = simulate_one(CFG, [77], algo)
        assert r.order == [77]
        # 只服务一个请求：FCFS/SSTF/LOOK 直接过去，SCAN 系列还要扫到端点
        if algo in ("FCFS", "SSTF", "LOOK"):
            assert r.metrics["total_seek"] == 24, (algo, r.metrics["total_seek"])
        else:
            assert r.metrics["total_seek"] >= 24


def test_generator_reproducible():
    a = generate("random", 12, 200, seed=42)
    b = generate("random", 12, 200, seed=42)
    assert a == b
    assert len(set(a)) == len(a)
    for p in PATTERNS:
        seq = generate(p, 15, 200, seed=7)
        assert len(seq) == len(set(seq))
        assert all(0 <= x < 200 for x in seq)


def test_parse_sequence():
    assert parse_sequence("98,183 37\n122") == [98, 183, 37, 122]
    assert parse_sequence("") == []


def test_presets_run():
    for name, p in PRESETS.items():
        cfg = DiskConfig(tracks=p["tracks"], start=p["start"], direction=p["direction"])
        rs = simulate(cfg, p["sequence"])
        assert len(rs) == len(ALGOS), name
        assert all(r.metrics["total_seek"] > 0 for r in rs)


# ---------------------------------------------------------------- 动态到达

from disk_sched.dynamic import compare_dynamic, simulate_dynamic, simulate_dynamic_multi
from disk_sched.streams import STREAMS, generate_stream


def test_dynamic_serves_everything():
    arr = generate_stream("poisson", 40, 200, seed=5, span_ms=400, start=53)
    for r in simulate_dynamic_multi(DiskConfig(), arr):
        assert r.metrics["served"] == r.metrics["total"] == 40, r.algo
        assert len(r.records) == 40
        assert {x.track for x in r.records} == {t for _, t in arr}


def test_dynamic_deterministic():
    arr = generate_stream("burst", 30, 200, seed=9, span_ms=300, start=90)
    a = simulate_dynamic(DiskConfig(start=90), arr, "SCAN")
    b = simulate_dynamic(DiskConfig(start=90), arr, "SCAN")
    assert [x.as_dict() for x in a.records] == [x.as_dict() for x in b.records]


def test_dynamic_fcfs_is_arrival_order():
    arr = [(0, 100), (10, 20), (20, 180), (30, 60)]
    r = simulate_dynamic(DiskConfig(start=0, tracks=200), arr, "FCFS")
    assert [x.track for x in r.records] == [100, 20, 180, 60]


def test_dynamic_wait_accounting():
    arr = generate_stream("steady", 20, 100, seed=3, span_ms=200, start=50)
    for r in simulate_dynamic_multi(DiskConfig(tracks=100, start=50), arr):
        for x in r.records:
            assert x.wait >= -1e-9
            assert abs((x.finish - x.at) - x.turnaround) < 1e-9
            assert x.finish >= x.start >= x.at


def test_dynamic_idle_when_queue_empty():
    # 只有一个请求，t=100 到，磁头 t=0 就空等
    r = simulate_dynamic(DiskConfig(tracks=200, start=53), [(100.0, 77)], "FCFS")
    rec = r.records[0]
    assert abs(rec.start - (100 + 24 * 0.15)) < 1e-6, rec.start
    assert r.metrics["idle_ms"] == 100


def test_dynamic_starvation_shows_up():
    """饥饿诱导流：SSTF 的平均等待最好，但最坏等待远大于 FCFS。"""
    arr = generate_stream("adversarial", 120, 200, seed=7, span_ms=600, start=53)
    rs = {r.algo: r for r in simulate_dynamic_multi(DiskConfig(), arr)}
    assert rs["SSTF"].metrics["avg_wait"] < rs["FCFS"].metrics["avg_wait"]
    assert rs["SSTF"].metrics["max_wait"] > 2.5 * rs["FCFS"].metrics["max_wait"]
    assert rs["SSTF"].metrics["fairness"] > 5


def test_stream_generator():
    for name in STREAMS:
        seq = generate_stream(name, 25, 200, seed=11, span_ms=300, start=100)
        assert len(seq) == 25, name
        assert all(0 <= t < 200 for _, t in seq), name
        assert all(0 <= at <= 300 for at, _ in seq), name
        assert seq == sorted(seq), name
    assert generate_stream("poisson", 10, 200, seed=2) == generate_stream("poisson", 10, 200, seed=2)


def test_dynamic_compare():
    arr = generate_stream("hotspot", 50, 200, seed=4, span_ms=300, start=60)
    c = compare_dynamic(simulate_dynamic_multi(DiskConfig(start=60), arr))
    assert c["best_wait"] in ALGOS
    assert c["most_fair"] in ALGOS


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL  {name}: {e}")
    print(f"\n{'全部通过' if not failed else str(failed) + ' 个失败'}")
    sys.exit(1 if failed else 0)
