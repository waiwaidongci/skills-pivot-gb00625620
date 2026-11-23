"""补招名额方案的参数规范化。"""

from src.domain.quota import normalize_limits
from src.domain.spec import CHANNELS, PROGRAMS


def normalize_quota_params(channel_caps, program_needs):
    caps = normalize_limits(channel_caps, CHANNELS, "渠道接待上限")
    needs = normalize_limits(program_needs, PROGRAMS, "项目待补人数")
    if sum(caps.values()) == 0 or sum(needs.values()) == 0:
        raise ValueError("渠道接待上限与项目待补人数均须至少有一个名额。")
    return caps, needs
