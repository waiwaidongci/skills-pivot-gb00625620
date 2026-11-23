"""下月补招名额的内部分配与逐月确认估算。

口径与月报一致：先经 :mod:`src.domain.analysis` 的去重归属，再按自然月分别
计算渠道 × 项目转化率，缺样（零受理）按零处理。名额为整数，受渠道接待上限
（按渠道汇总）与项目待补人数（按项目汇总）双重约束，目标是先最大化最差月份
的预计确认总人数，再最小化使用名额总数（字典序最优）。所有比率使用分数精确
运算，避免浮点误差影响打平判定。
"""

from collections import defaultdict
from fractions import Fraction
from heapq import heappop, heappush
from hashlib import sha256
import json

from .analysis import _validated_intakes
from .spec import CHANNELS, PROGRAMS

LIMIT_MIN = 0
LIMIT_MAX = 999
TOTAL_QUOTA_CEILING = 9000
ZERO_RATE = Fraction(0)


def monthly_rates(rows):
    """返回批内各月的渠道 × 项目转化率（分数），缺样按零。

    同时返回每月每格确认人数与去重受理人数，供页面回查证据。
    """
    _, intakes = _validated_intakes(rows)
    program_count = len(PROGRAMS)
    buckets = defaultdict(lambda: [[0, 0] for _ in range(len(CHANNELS) * program_count)])
    for period, channel, program, converted in intakes:
        cell = buckets[period][CHANNELS.index(channel) * program_count + PROGRAMS.index(program)]
        cell[1] += 1
        cell[0] += int(converted)

    months = sorted(buckets)
    table = {}
    for period in months:
        grid = buckets[period]
        table[period] = []
        for index, (confirmed, total) in enumerate(grid):
            rate = Fraction(confirmed, total) if total else ZERO_RATE
            table[period].append({
                "channel": CHANNELS[index // program_count],
                "program": PROGRAMS[index % program_count],
                "confirmed": confirmed,
                "intakes": total,
                "rate": rate,
                "missing_sample": total == 0,
            })
    return months, table


def _rate_matrix(months, table):
    return [[table[period][index]["rate"] for period in months]
            for index in range(len(CHANNELS) * len(PROGRAMS))]


def _greedy_incumbent(channel_caps, program_needs, rates):
    """逐单位贪心构造可行初始解，受渠道与项目两组容量约束。"""
    program_count = len(program_needs)
    cell_count = len(channel_caps) * program_count
    month_count = len(rates[0])
    allocation = [0] * cell_count
    rem_caps = list(channel_caps)
    rem_needs = list(program_needs)
    while True:
        best = None
        best_key = None
        for index in range(cell_count):
            channel = index // program_count
            if rem_caps[channel] <= 0 or rem_needs[index % program_count] <= 0:
                continue
            gains = [rates[index][month] for month in range(month_count)]
            key = (min(gains), sum(gains), -index)
            if best_key is None or key > best_key:
                best_key, best = key, index
        if best is None:
            break
        allocation[best] += 1
        rem_caps[best // program_count] -= 1
        rem_needs[best % program_count] -= 1
    return allocation


class _MinCostFlow:
    """极小二分图上的最小费用流，求单月容量松弛后的精确确认上界。

    源点 → 渠道（容量为该渠道剩余接待上限）→ 项目（格边，费用为负转化率）
    → 汇点（项目边容量为该项目剩余待补）。运输问题约束矩阵全幺模，松弛最优即
    整数最优。采用顶点势能维护非负折减费用的最短增广路；一旦最短增广路费用转正
    （边际收益为负）即停止，累计费用取负即为任意可行流量下的最大确认收益。
    """

    def __init__(self, channel_count, program_count):
        self.source = 0
        self.program_first = 1 + channel_count
        self.sink = self.program_first + program_count
        self.graph = [[] for _ in range(self.sink + 1)]

    def _add(self, start, end, capacity, cost):
        forward = [end, len(self.graph[end]), capacity, cost]
        backward = [start, len(self.graph[start]), 0, -cost]
        self.graph[start].append(forward)
        self.graph[end].append(backward)

    def add_channel(self, channel, capacity):
        if capacity > 0:
            self._add(self.source, 1 + channel, capacity, ZERO_RATE)

    def add_program(self, program, capacity):
        if capacity > 0:
            self._add(self.program_first + program, self.sink, capacity, ZERO_RATE)

    def add_cell(self, channel, program, rate):
        if rate > 0:
            self._add(1 + channel, self.program_first + program, 10 ** 6, -rate)

    def best(self):
        """逐单位最短增广，边际费用转正即停止，返回最大确认收益。"""
        size = len(self.graph)
        potential = [ZERO_RATE] * size
        total = ZERO_RATE
        while True:
            distance = [None] * size
            distance[self.source] = ZERO_RATE
            predecessor = [None] * size
            queue = [(ZERO_RATE, self.source)]
            while queue:
                reduced, node = heappop(queue)
                if reduced != distance[node]:
                    continue
                for edge_index, edge in enumerate(self.graph[node]):
                    end, _, capacity, cost = edge
                    if capacity <= 0:
                        continue
                    step = cost + potential[node] - potential[end]
                    candidate = distance[node] + step
                    if distance[end] is None or candidate < distance[end]:
                        distance[end] = candidate
                        predecessor[end] = (node, edge_index)
                        heappush(queue, (candidate, end))
            if predecessor[self.sink] is None:
                return -total
            for node in range(size):
                if distance[node] is not None:
                    potential[node] += distance[node]
            path_cost = potential[self.sink] - potential[self.source]
            if path_cost >= 0:
                return -total
            node = self.sink
            while node != self.source:
                previous, edge_index = predecessor[node]
                edge = self.graph[previous][edge_index]
                edge[2] -= 1
                self.graph[node][edge[1]][2] += 1
                total += edge[3]
                node = previous


def _scenario_bound(rem_caps, rem_needs, rates, month, decided, allocation,
                    channel_count, program_count):
    """某月在剩余分组容量下可达到的最大预计确认上界（精确，含已落定部分）。

    流量网络只承载未决格，容量取剩余分组容量，其最优收益再加上已落定格的贡献。
    """
    flow = _MinCostFlow(channel_count, program_count)
    for channel, capacity in enumerate(rem_caps):
        flow.add_channel(channel, capacity)
    for program, capacity in enumerate(rem_needs):
        flow.add_program(program, capacity)
    for index in range(channel_count * program_count):
        if index in decided:
            continue
        channel, program = divmod(index, program_count)
        flow.add_cell(channel, program, rates[index][month])
    settled = sum(rates[index][month] * allocation[index] for index in decided)
    return settled + flow.best()


def solve_allocation(channel_caps, program_needs, rates):
    """字典序最优的整数名额分配。

    约束为渠道接待上限（按渠道汇总）与项目待补人数（按项目汇总）两组分组容量。
    第一目标最大化 ``min_m Σ_m r_cm·x_c``，打平时最小化 ``Σ x_c``。
    深度优先分支定界，单月上界由二分图最小费用流精确计算，比率全程分数精确比较。
    """
    channel_count = len(channel_caps)
    program_count = len(program_needs)
    cell_count = channel_count * program_count
    month_count = len(rates[0])
    order = sorted(range(cell_count),
                   key=lambda index: (max(rates[index]) - min(rates[index]), max(rates[index])),
                   reverse=True)

    best = [0] * cell_count
    best_min = Fraction(-1)
    best_sum = 0

    def dfs(position, allocation, rem_caps, rem_needs, used_total):
        nonlocal best, best_min, best_sum
        if position == cell_count:
            month_totals = [sum(rates[index][month] * allocation[index] for index in range(cell_count))
                            for month in range(month_count)]
            current_min = min(month_totals) if month_totals else ZERO_RATE
            if current_min > best_min or (current_min == best_min and used_total < best_sum):
                best, best_min, best_sum = list(allocation), current_min, used_total
            return

        if best_min >= 0:
            decided = set(order[:position])
            upper = min(_scenario_bound(rem_caps, rem_needs, rates, month, decided, allocation,
                                        channel_count, program_count) for month in range(month_count))
            if upper < best_min or (upper == best_min and used_total >= best_sum):
                return

        index = order[position]
        channel, program = divmod(index, program_count)
        upper_value = min(rem_caps[channel], rem_needs[program])
        # 取值从小到大：先探省名额分支，配合打平剪枝锁定最少名额。
        for value in range(upper_value + 1):
            allocation[index] = value
            rem_caps[channel] -= value
            rem_needs[program] -= value
            dfs(position + 1, allocation, rem_caps, rem_needs, used_total + value)
            rem_caps[channel] += value
            rem_needs[program] += value
        allocation[index] = 0

    if month_count and any(any(rates[index]) for index in range(cell_count)) \
            and sum(channel_caps) and sum(program_needs):
        seed = _greedy_incumbent(channel_caps, program_needs, rates)
        seed_totals = [sum(rates[index][month] * seed[index] for index in range(cell_count))
                       for month in range(month_count)]
        if seed_totals:
            best, best_min, best_sum = seed, min(seed_totals), sum(seed)
        dfs(0, [0] * cell_count, list(channel_caps), list(program_needs), 0)

    totals = [sum(rates[index][month] * best[index] for index in range(cell_count))
              for month in range(month_count)]
    return best, totals


def normalize_limits(raw, roster, label):
    if not isinstance(raw, dict):
        raise ValueError(f"{label}须以名册名称填写。")
    if set(raw) != set(roster):
        raise ValueError(f"{label}须且只能包含名册中的 {len(roster)} 个名称。")
    cleaned = {}
    for name in roster:
        value = raw[name]
        if type(value) is not int or not LIMIT_MIN <= value <= LIMIT_MAX:
            raise ValueError(f"{label}「{name}」须为 {LIMIT_MIN} 至 {LIMIT_MAX} 的整数。")
        cleaned[name] = value
    return cleaned


def make_signature(dataset_id, caps, needs):
    payload = {"dataset_id": dataset_id,
               "caps": {name: caps[name] for name in CHANNELS},
               "needs": {name: needs[name] for name in PROGRAMS}}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()


def _fraction_text(value):
    return f"{float(value):.4f}".rstrip("0").rstrip(".")


def plan_quota(rows, caps, needs):
    """完整内部分析：逐月证据、最优名额分配与逐月预计确认。"""
    months, table = monthly_rates(rows)
    if not months:
        raise ValueError("该批次没有可归属的受理月份，无法估算补招。")
    channel_caps = [caps[name] for name in CHANNELS]
    program_needs = [needs[name] for name in PROGRAMS]
    if sum(channel_caps) > TOTAL_QUOTA_CEILING or sum(program_needs) > TOTAL_QUOTA_CEILING:
        raise ValueError(f"渠道上限与项目待补的合计均不能超过 {TOTAL_QUOTA_CEILING} 人。")

    rates = _rate_matrix(months, table)
    allocation, month_totals = solve_allocation(channel_caps, program_needs, rates)
    program_count = len(PROGRAMS)

    allocation_rows = []
    channel_used = {name: 0 for name in CHANNELS}
    program_used = {name: 0 for name in PROGRAMS}
    for index, quota in enumerate(allocation):
        channel = CHANNELS[index // program_count]
        program = PROGRAMS[index % program_count]
        channel_used[channel] += quota
        program_used[program] += quota
        allocation_rows.append({
            "channel": channel,
            "program": program,
            "quota": quota,
            "monthly_rates": [
                {"month": period, "rate_text": _fraction_text(table[period][index]["rate"]),
                 "missing_sample": table[period][index]["missing_sample"]}
                for period in months
            ],
        })

    worst = min(month_totals) if month_totals else ZERO_RATE
    month_estimates = [
        {"month": period,
         "expected_confirmed": _fraction_text(month_totals[offset]),
         "allocated_quota": sum(allocation),
         "is_worst": month_totals[offset] == worst}
        for offset, period in enumerate(months)
    ]
    rate_evidence = []
    for period in months:
        cells = []
        for cell in table[period]:
            cells.append({**{key: value for key, value in cell.items() if key != "rate"},
                          "rate_text": _fraction_text(cell["rate"])})
        rate_evidence.append({"month": period, "cells": cells})
    return {
        "headline": "下月补招名额内部分配方案",
        "note": "沿用月报学员归属与确认口径，按批内各月实际转化率分别估算，缺样按零；名额为整数且不超渠道接待上限与项目待补人数。",
        "months": months,
        "allocation": allocation_rows,
        "month_estimates": month_estimates,
        "rate_evidence": rate_evidence,
        "channel_summary": [
            {"name": name, "cap": caps[name], "used": channel_used[name]} for name in CHANNELS],
        "program_summary": [
            {"name": name, "need": needs[name], "used": program_used[name]} for name in PROGRAMS],
        "metrics": [
            {"label": "最差月份预计确认（人）", "value": _fraction_text(worst),
             "detail": "各月预计确认总人数的最小值，已按字典序最大化"},
            {"label": "使用名额总数（人）", "value": sum(allocation),
             "detail": "最差月打平时，取名额最少的方案"},
            {"label": "渠道接待上限合计（人）", "value": sum(channel_caps)},
            {"label": "项目待补人数合计（人）", "value": sum(program_needs)},
        ],
        "sections": [
            {"title": "内部使用范围", "text":
                "补招分配与逐月估算仅在登录后的内部分析页面查看，不进入公开交叉表、复核、交付与导出流程。"},
            {"title": "缺样处理", "text":
                "某渠道 × 项目在某月没有去重受理样本时，该月转化率按零参与估算，证据表保留「缺样按零」标记。"},
        ],
    }
