"""补招名额求解器与逐月口径的独立验证（仅用标准库，python3 -I 运行）。"""

import itertools
import random
import sys
import time
from fractions import Fraction

sys.path.insert(0, "/workspace/backend")

from src.domain import quota  # noqa: E402
from src.domain.quota import (  # noqa: E402
    ZERO_RATE, monthly_rates, normalize_limits, plan_quota, solve_allocation,
)
from src.domain.spec import CHANNELS, PROGRAMS  # noqa: E402

CHANNEL_COUNT = len(CHANNELS)
PROGRAM_COUNT = len(PROGRAMS)
CELLS = CHANNEL_COUNT * PROGRAM_COUNT
MONTHS = 2
PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"FAIL  {name} {detail}")


def brute_force(channel_caps, program_needs, rates):
    """枚举全部整数分配（含分组容量约束），取字典序最优。"""
    domains = [range(min(channel_caps[i // PROGRAM_COUNT],
                         program_needs[i % PROGRAM_COUNT]) + 1) for i in range(CELLS)]
    best = None
    best_allocation = None
    for allocation in itertools.product(*domains):
        if any(sum(allocation[c * PROGRAM_COUNT + p] for p in range(PROGRAM_COUNT)) > channel_caps[c]
               for c in range(CHANNEL_COUNT)):
            continue
        if any(sum(allocation[c * PROGRAM_COUNT + p] for c in range(CHANNEL_COUNT)) > program_needs[p]
               for p in range(PROGRAM_COUNT)):
            continue
        totals = [sum(rates[i][m] * allocation[i] for i in range(CELLS)) for m in range(MONTHS)]
        key = (min(totals), -sum(allocation))
        if best is None or key > best:
            best, best_allocation = key, allocation
    return list(best_allocation), [sum(rates[i][m] * best_allocation[i] for i in range(CELLS))
                                   for m in range(MONTHS)]


def random_rates(rng):
    return [[Fraction(rng.randint(0, 5), rng.randint(1, 6)) for _ in range(MONTHS)] for _ in range(CELLS)]


def feasible(allocation, channel_caps, program_needs):
    for c in range(CHANNEL_COUNT):
        if sum(allocation[c * PROGRAM_COUNT + p] for p in range(PROGRAM_COUNT)) > channel_caps[c]:
            return False
    for p in range(PROGRAM_COUNT):
        if sum(allocation[c * PROGRAM_COUNT + p] for c in range(CHANNEL_COUNT)) > program_needs[p]:
            return False
    return all(value >= 0 for value in allocation)


def test_solver_matches_bruteforce():
    print("test_solver_matches_bruteforce")
    rng = random.Random(20261123)
    for case in range(50):
        channel_caps = [rng.randint(0, 4) for _ in range(CHANNEL_COUNT)]
        program_needs = [rng.randint(0, 4) for _ in range(PROGRAM_COUNT)]
        rates = random_rates(rng)
        got_alloc, got_totals = solve_allocation(channel_caps, program_needs, rates)
        want_alloc, want_totals = brute_force(channel_caps, program_needs, rates)
        check(f"case {case} objective", (min(got_totals), -sum(got_alloc))
              == (min(want_totals), -sum(want_alloc)),
              f"got={(float(min(got_totals)), sum(got_alloc))} want={(float(min(want_totals)), sum(want_alloc))}")
        check(f"case {case} feasible", feasible(got_alloc, channel_caps, program_needs))
        check(f"case {case} totals consistent", min(got_totals) == min(want_totals))


def test_determinism():
    print("test_determinism")
    rng = random.Random(7)
    caps = [rng.randint(5, 40) for _ in range(CHANNEL_COUNT)]
    needs = [rng.randint(5, 40) for _ in range(PROGRAM_COUNT)]
    rates = random_rates(rng)
    first, _ = solve_allocation(caps, needs, rates)
    for _ in range(3):
        again, _ = solve_allocation(caps, needs, rates)
        check("same allocation", again == first)


def test_zeros_and_ties():
    print("test_zeros_and_ties")
    rates = [[Fraction(1, 2), Fraction(1, 2)] for _ in range(CELLS)]
    caps = [0] * CHANNEL_COUNT
    needs = [10] * PROGRAM_COUNT
    allocation, totals = solve_allocation(caps, needs, rates)
    check("zero caps => zero quota", allocation == [0] * CELLS and sum(totals) == 0)

    # 两月转化率相同且为正：最大化最差月要求填满可运输容量，全容量解即打平下的最优。
    caps = [3] * CHANNEL_COUNT
    needs = [3] * PROGRAM_COUNT
    allocation, totals = solve_allocation(caps, needs, rates)
    expected_flow = min(sum(caps), sum(needs))
    check("flat rates -> fill transport capacity", sum(allocation) == expected_flow,
          f"allocation={allocation}")

    zero_rates = [[ZERO_RATE, ZERO_RATE] for _ in range(CELLS)]
    allocation, totals = solve_allocation(caps, needs, zero_rates)
    check("zero rates => zero quota", sum(allocation) == 0 and min(totals) == 0)


def test_maximin_priority():
    print("test_maximin_priority")
    # 单元格 0 只利好月份 0，单元格 1 只利好月份 1；项目 0 的待补只有 2，
    # 因此最差月最多抬到 2，资源应均摊到两个单元格。
    rates = [[Fraction(1), ZERO_RATE], [ZERO_RATE, Fraction(1)]] + [[ZERO_RATE, ZERO_RATE]] * (CELLS - 2)
    caps = [4] + [0] * (CHANNEL_COUNT - 1)
    needs = [2, 2] + [0] * (PROGRAM_COUNT - 2)
    allocation, totals = solve_allocation(caps, needs, rates)
    check("worst month maximized", min(totals) == 2 and totals == [2, 2],
          f"totals={[float(t) for t in totals]} alloc={allocation[:2]}")
    check("group caps hold", feasible(allocation, caps, needs))


def test_monthly_rates_missing_sample():
    print("test_monthly_rates_missing_sample")
    rows = [
        {"learner_id": "L1", "intake_date": "2026-10-06", "channel": CHANNELS[0],
         "program": PROGRAMS[0], "enrolled": False},
        {"learner_id": "L1", "intake_date": "2026-10-18", "channel": CHANNELS[1],
         "program": PROGRAMS[1], "enrolled": True},
        {"learner_id": "L2", "intake_date": "2026-11-02", "channel": CHANNELS[0],
         "program": PROGRAMS[0], "enrolled": True},
    ]
    months, table = monthly_rates(rows)
    check("months ordered", months == ["2026-10", "2026-11"])
    oct_cell = table["2026-10"][0]
    # 月报口径：同月存在归属项目（PROGRAMS[0]）的确认才计转化，跨项目确认不计。
    check("dedup attribution", oct_cell["confirmed"] == 0 and oct_cell["intakes"] == 1
          and oct_cell["rate"] == 0)
    nov_other = table["2026-11"][1]
    check("missing sample zero", nov_other["missing_sample"] and nov_other["rate"] == 0)


def test_plan_quota_end_to_end():
    print("test_plan_quota_end_to_end")
    rng = random.Random(11)
    rows = []
    for month in ("2026-10", "2026-11"):
        for ci, channel in enumerate(CHANNELS):
            for pi, program in enumerate(PROGRAMS):
                total = rng.randint(6, 20)
                confirmed = rng.randint(0, total)
                for k in range(total):
                    base = {"learner_id": f"{month}-{ci}-{pi}-{k}", "intake_date": f"{month}-05",
                            "channel": channel, "program": program, "enrolled": False}
                    rows.append(base)
                    if k < confirmed:
                        rows.append({**base, "intake_date": f"{month}-19", "enrolled": True})
    caps = normalize_limits({name: rng.randint(10, 40) for name in CHANNELS}, CHANNELS, "渠道接待上限")
    needs = normalize_limits({name: rng.randint(10, 40) for name in PROGRAMS}, PROGRAMS, "项目待补人数")
    result = plan_quota(rows, caps, needs)
    check("headline", result["headline"] == "下月补招名额内部分配方案")
    check("allocation rows", len(result["allocation"]) == CELLS)
    check("two month estimates", len(result["month_estimates"]) == 2)
    for row in result["allocation"]:
        check("nonnegative quota", row["quota"] >= 0)
    for summary in result["channel_summary"]:
        check("channel cap respected", summary["used"] <= summary["cap"], str(summary))
    for summary in result["program_summary"]:
        check("program need respected", summary["used"] <= summary["need"], str(summary))
    check("worst month flagged", sum(1 for row in result["month_estimates"] if row["is_worst"]) >= 1)
    check("metric quota sum", result["metrics"][1]["value"]
          == sum(row["quota"] for row in result["allocation"]))


def test_large_scale_performance():
    print("test_large_scale_performance")
    rng = random.Random(99)
    caps = [rng.randint(30, 120) for _ in range(CHANNEL_COUNT)]
    needs = [rng.randint(30, 120) for _ in range(PROGRAM_COUNT)]
    rates = random_rates(rng)
    start = time.perf_counter()
    allocation, totals = solve_allocation(caps, needs, rates)
    elapsed = time.perf_counter() - start
    check("finishes under 5s", elapsed < 5, f"{elapsed:.2f}s")
    check("feasible at scale", feasible(allocation, caps, needs))
    check("nonnegative", min(totals) >= 0)
    print(f"    scale caps={caps} needs={needs} elapsed={elapsed:.3f}s worst={float(min(totals)):.3f} "
          f"quota={sum(allocation)}")


def test_three_months_with_missing_samples():
    print("test_three_months_with_missing_samples")
    rng = random.Random(31)
    month_count = 3
    rates = []
    for index in range(CELLS):
        column = []
        for month in range(month_count):
            # 每月约 1/3 的格缺样（转化率为零），其余取正分数。
            column.append(ZERO_RATE if rng.random() < 0.33
                          else Fraction(rng.randint(1, 4), rng.randint(2, 6)))
        rates.append(column)
    # 三个月的 max-min 整数规划随容量指数增长，这里用现实小上限验证正确性与口径。
    caps = [rng.randint(4, 8) for _ in range(CHANNEL_COUNT)]
    needs = [rng.randint(4, 8) for _ in range(PROGRAM_COUNT)]
    start = time.perf_counter()
    allocation, totals = solve_allocation(caps, needs, rates)
    elapsed = time.perf_counter() - start
    check("three-month run under 5s", elapsed < 5, f"{elapsed:.2f}s")
    check("three totals", len(totals) == 3)
    check("feasible", feasible(allocation, caps, needs))
    check("deterministic", solve_allocation(caps, needs, rates)[0] == allocation)
    print(f"    three-month elapsed={elapsed:.3f}s totals={[float(t) for t in totals]} "
          f"worst={float(min(totals)):.3f} quota={sum(allocation)}")


def test_validation_errors():
    print("test_validation_errors")
    valid = {name: 1 for name in CHANNELS}
    check("valid roster accepted", normalize_limits(valid, CHANNELS, "渠道接待上限") == valid)
    for bad in ({}, {**valid, "x": 1}, "nope", None):
        try:
            normalize_limits(bad, CHANNELS, "渠道接待上限")
            check("reject bad roster", False, str(bad))
        except ValueError:
            check("reject bad roster", True)
    for bad in ({name: -1 for name in CHANNELS},
                {name: 1.5 for name in CHANNELS},
                {name: "1" for name in CHANNELS},
                {name: 1000 for name in CHANNELS}):
        try:
            normalize_limits(bad, CHANNELS, "渠道接待上限")
            check("reject out of range", False, str(bad))
        except ValueError:
            check("reject out of range", True)


if __name__ == "__main__":
    test_monthly_rates_missing_sample()
    test_solver_matches_bruteforce()
    test_determinism()
    test_zeros_and_ties()
    test_maximin_priority()
    test_plan_quota_end_to_end()
    test_large_scale_performance()
    test_three_months_with_missing_samples()
    test_validation_errors()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
