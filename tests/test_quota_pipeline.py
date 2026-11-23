"""用演示受理数据端到端验证补招分配的口径与约束（python3 -I 运行）。"""

import sys

sys.path.insert(0, "/workspace/backend")

from src.domain.demo import demo_rows  # noqa: E402
from src.domain.quota import make_signature, monthly_rates, plan_quota  # noqa: E402
from src.domain.spec import CHANNELS, PROGRAMS  # noqa: E402
from src.services.quota_validation import normalize_quota_params  # noqa: E402

rows = demo_rows()
months, table = monthly_rates(rows)
assert months == ["2026-10", "2026-11"], months
print("批内月份:", months)

# 与 README 演示口径核对：2026-11 社区转介 × 养老照护为 12 / 20。
cell = table["2026-11"][0]
assert cell["channel"] == CHANNELS[0] and cell["program"] == PROGRAMS[0]
assert (cell["confirmed"], cell["intakes"]) == (12, 20), cell
print("月报口径核对 社区转介×养老照护 2026-11 =", cell["confirmed"], "/", cell["intakes"])

caps, needs = normalize_quota_params(
    {name: 30 for name in CHANNELS}, {name: 25 for name in PROGRAMS})
result = plan_quota(rows, caps, needs)

# 约束核对
channel_used = {row["name"]: row["used"] for row in result["channel_summary"]}
program_used = {row["name"]: row["used"] for row in result["program_summary"]}
assert all(channel_used[name] <= caps[name] for name in CHANNELS)
assert all(program_used[name] <= needs[name] for name in PROGRAMS)
assert all(row["quota"] >= 0 and isinstance(row["quota"], int) for row in result["allocation"])
print("渠道用量:", channel_used, "上限:", caps)
print("项目用量:", program_used, "待补:", needs)

# 逐月估算与最差月
worst_flags = [row["month"] for row in result["month_estimates"] if row["is_worst"]]
assert worst_flags, "必须标出最差月份"
for row in result["month_estimates"]:
    print("月份", row["month"], "预计确认", row["expected_confirmed"],
          "名额", row["allocated_quota"], "最差" if row["is_worst"] else "")
assert result["metrics"][1]["value"] == sum(r["quota"] for r in result["allocation"])

# 幂等签名：同批次同上限一致，改上限即变
sig1 = make_signature(7, caps, needs)
sig2 = make_signature(7, caps, needs)
sig3 = make_signature(7, {**caps, CHANNELS[0]: 29}, needs)
assert sig1 == sig2 and sig1 != sig3 and len(sig1) == 64
print("签名幂等核对通过:", sig1[:12], "…")

# 缺样按零：演示数据所有格都有样本，构造一个缺样批次验证
sparse = [r for r in rows if r["channel"] != CHANNELS[2]]
months2, table2 = monthly_rates(sparse)
for period in months2:
    missing = [c for c in table2[period] if c["missing_sample"]]
    assert missing and all(c["rate"] == 0 for c in missing), "就业服务站格应缺样按零"
print("缺样按零核对通过，缺样格数:",
      sum(sum(1 for c in table2[p] if c["missing_sample"]) for p in months2))

# 参数校验
for bad_caps, bad_needs in [({}, needs), (caps, {})]:
    try:
        normalize_quota_params(bad_caps, bad_needs)
        raise AssertionError("应拒绝不完整名册")
    except ValueError:
        pass
print("全部端到端断言通过")
