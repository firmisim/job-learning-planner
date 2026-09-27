# AGENTS.md

## Project Purpose

本项目是一个基于真实 JD 发现职业能力、研究学习内容，并结合用户当前能力与已完成实践持续生成个性化学习路线的个人学习规划工具。它不是招聘平台、求职证据管理平台或长期趋势预测系统。

## Repository Source Priority

重要开发任务开始前依次检查：

1. 当前 branch、`git status`、必要的 `git diff`、真实代码与测试；
2. `docs/PROJECT_STATUS.md`、`docs/ARCHITECTURE.md`、`docs/ROADMAP.md`、`docs/DECISIONS.md`；
3. 与任务直接相关的 `README.md`、`src/`、`schemas/`、`scripts/`、`tests/` 与 `.agents/skills/`。

真实代码、测试与 Git 状态优先于文档、旧对话和历史 Prompt。发现冲突时先报告，再以仓库事实为准修正文档或执行范围。

## Standard Stage Protocol

### Before

- 检查 branch、工作树状态和相关 diff，识别并保留已有修改。
- 恢复当前实现、目标架构、active roadmap 与长期决策。
- 将 Stage Prompt 视为本阶段 delta；不得把历史规划当作当前事实。

### During

- 严格限制在当前 Scope，复用既有入口，不建立平行实现。
- Python 负责确定性计算、验证、统计和持久化；Codex 负责语义分析、研究、推荐和编排。Python 不调用远程 LLM API。
- 统计和比例只能来自 Python 产物，Codex 不估算或改写数字。
- Planned 能力不得写成 Implemented；未经授权不得提前进入下一阶段。
- 无关问题只报告，不静默扩大范围，不覆盖长期配置或用户数据。
- 除非用户明确要求，不 commit、push、创建 branch 或 tag。

### Unexpected Issue Stop

出现以下情况时停止有风险的写操作，保留现场并报告：

- 真实代码、测试、文档或 Prompt 对关键边界相互冲突；
- 需要覆盖未知未提交修改；
- 需要删除、迁移或重写未明确授权的数据；
- 当前验证失败，或继续执行会扩大阶段 Scope。

可以继续进行不改变状态的诊断，但不得用临时兼容、静默迁移或绕过验证来掩盖问题。

### After

- 运行与影响范围相称的测试和必要回归；失败必须明确报告，不得声称完成。
- 只更新职责范围内且真正受影响的 canonical docs。
- 执行 `git diff --check`，检查最终 diff 与 `git status`，确认已有无关修改仍被保留。
- 最终报告实现、测试、文档同步、Git 状态、限制和未处理问题；本阶段完成即停止。

## Design and Execution Boundary

- 架构或版本切换、数据迁移、高风险重构必须先有明确授权和足够完整的目标合同。
- 普通阶段直接按 Prompt 与本协议执行；只有跨多层、长时间、需要可靠中断恢复的工作才建立轻量 ExecPlan。
- 不引入数据库、通用 Agent/Workflow/Migration/Ontology 框架或复杂异步平台，除非 active architecture 与阶段授权明确要求。
- UI 只能通过 Application-facing API 使用 Core；UI 不直接持久化业务数据或复制 Core 规则。
- 所有持久化修改必须遵守验证、stale/conflict 检查、幂等、原子写入、当前 immutable/retention 合同与破坏性确认等有效安全边界。
- Reset 必须使用正式入口，先精确 preview，再以匹配授权执行；不得手工模拟、由应用启动隐式触发，或越界删除。

## Strict Delta Prompt

- Stage Prompt 只描述当前目标、特殊约束、禁止提前实现的 Scope、测试和验收，不复述整个仓库。
- 准确性优先于执行效率和 Token 节省；不得为缩短 Prompt 删除会改变安全或架构判断的上下文。
- 当前阶段没有授权的设计或实现，只记录为 next stage，不顺手完成。

## Repository Memory and Documentation Minimalism

Repository documentation is current-state memory, not an append-only project transcript. Git 负责历史。

- `AGENTS.md`：长期 Codex 执行协议与仓库导航。
- `docs/PROJECT_STATUS.md`：当前实现、版本、阶段、测试状态、阻塞与下一步。
- `docs/ARCHITECTURE.md`：唯一当前目标架构。
- `docs/ROADMAP.md`：唯一 active future plan。
- `docs/DECISIONS.md`：当前仍有效的 durable decisions。

默认不得为普通 Stage 创建新的长期 `.md` 状态、规划、审计、refinement、checklist 或 closeout 文档。Stage 结果优先更新上述 canonical docs。已 superseded 设计只保留在 Git 历史中，不在 Repository Memory 重复保存。

只有一个主题长期跨越多个阶段、具有独立职责且无法合理归入 canonical docs 时，才可新增文档；如果目的只是记录某阶段执行过程，默认拒绝。不得在多个 canonical files 中完整重复同一原则，必要交叉引用应指向负责该事实的单一文件。

## Workspace and Data Safety

- 假设工作树含有用户修改；不得覆盖、清理或格式化无关变更。
- 不静默修改项目级配置，不展示密钥，不提交本地 `state/`、个人输入或生成产物。
- 受保护历史只能经正式 Store 修改；RoadmapVersion 在保留期间不可覆盖或编辑，只能按当前单份删除与固定 retention 合同移除。
- 用户长期状态只能经当前正式、验证过的入口修改；不得直接编辑文件绕过规则。

## Testing and Git Closure

- 执行任何 Python 或 pytest 命令前，将 `TEMP` 与 `TMP` 设为 `<项目根目录>\.tmp\codex`；不得使用 `.tmp\local`。
- 不为单次测试修改 `pytest.ini`，不删除 `.tmp` 根目录或其他执行环境的临时状态。
- 文档-only 阶段至少执行 `git diff --check`、链接/引用检查、最终 diff 与 status 检查；无需运行 Python 测试，除非文档结论依赖新的运行验证。
