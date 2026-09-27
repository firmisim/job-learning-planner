from __future__ import annotations

from schemas.core import CapabilityKnowledge


GENERIC_LEVEL_CRITERIA: tuple[str, ...] = (
    "无法解释该能力解决什么问题，并且没有真实使用经验。",
    "能解释基本用途和核心概念，能理解简单示例或文档，但尚不能独立完成实际任务。",
    "能依靠文档、示例或明确步骤完成常见基础任务，知道主要操作方式；条件明显变化时仍高度依赖参考。",
    "能独立完成常见真实任务，能根据需求调整实现，并能定位和解决常见问题。",
    "能处理复杂或非典型场景，理解关键机制、边界和主要取舍，并能设计较可靠方案、解决较困难问题。",
    "能在复杂或陌生场景下系统性应用该能力，进行架构、性能、可靠性或工程取舍，并形成方法、最佳实践或指导他人。",
)


def applicable_level_criteria(
    knowledge: CapabilityKnowledge | None,
) -> tuple[str, tuple[str, ...]]:
    if knowledge is not None and knowledge.level_criteria:
        return "capability-specific", tuple(
            item.text for item in knowledge.level_criteria
        )
    return "generic", GENERIC_LEVEL_CRITERIA
