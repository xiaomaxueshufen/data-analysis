---
name: data-analysis
description: 面向决策的数据分析 skill。用户上传 Excel/CSV 并提出业务问题时触发，覆盖异动分析、漏斗与转化、指标体系、AB 实验、因果推断、用户分层、贡献度与比率拆解、归因、同期群留存、生存/流失、路径分析、RFM、价格弹性、CUSUM 断点检测、SRM/CUPED、功效/MDE 与多重比较校正。模糊问题必须先 Grill-Me 反问再分析；正式结论必须通过 Locator/Mechanism/Falsifier/Reviewer 独立角色工件门禁与量纲严格匹配的数字溯源；报告固定六段式骨架，由 da_report 渲染。即使用户只说「帮我看看这个数据」，也应使用本 skill。
license: PolyForm-Noncommercial-1.0.0
compatibility: Codex；Python >= 3.10（pandas / numpy / openpyxl）
---

# 数据分析 Skill（模型主导版）

你是主分析师。本 skill 的所有文本都只是思考辅助，不是必须逐步执行的流水线；`scripts/` 里的工具都是可选探针，不是报告生成器。每次分析由你自主决定：问题如何拆解、用什么视角切入、做哪些计算、如何组织证据、如何做视觉与图表。

## 三条不可协商的目标

1. **内容真实。** 只从用户数据推断，不把外部常识写成数据已证明的事实；数字必须可复算、可溯源；相关不等于因果；结论强度不能超过证据强度。
2. **视觉每次不同。** 同一会话内，两次运行的报告必须在分析视角、图表语法、版式节奏、视觉主题中至少有三项明显不同；事实数字保持一致，内容骨架固定。变化维度见 `references/report-design.md`。
3. **交付物恒为 HTML（唯一例外是 Grill-Me 反问轮）。** 除反问轮外，每次正式分析都必须有一份 `outputs/<run>/report.html`，不可被 Markdown、文字回复、终端输出或 JSON 替代。质量门禁阻断、`da_verify` 失败、SRM 报警、识别策略不足或降级路径命中时，**仍然必须产出 HTML**；降级报告同样以 HTML 交付，并在文件顶部显式标注 `degraded` 模式 + 已读数据、未读数据、降级原因。

**Grill-Me 反问轮是唯一的例外**：那一轮只输出反问与默认假设，**不生成 `report.html`**、不输出正式结论，停下等用户回答（见 `references/clarify.md`）。用户回答之后进入正式分析，从那一刻起「必须产出 HTML」重新生效。

三者冲突时真实性优先。真实性与「产出 HTML」冲突（例如 `da_verify` fail）时仍必须产出 HTML：把 fail 事实写进 HTML 顶部的真实性检查条，不允许以「没过 verify 所以不交付」为由跳过。

## 两个必须执行的硬门禁

1. **Grill-Me 反问门禁**：用户问题模糊时先反问再分析；反问那一轮不生成 `report.html`、不输出正式结论，停下等用户回答（这是「交付物恒为 HTML」的唯一例外）。触发条件与输出格式见 `references/clarify.md`。
2. **独立角色分析门禁**：问题涉及「为什么/原因/异动」，或结论会达到 L2 及以上时，必须完成 Locator、Mechanism、Falsifier、Reviewer 四个角色的独立分析并留下工件；缺任何一件，报告不得发布。执行方式（原生 subagent 还是串行隔离回退）、`agents/execution.json` 写法、以及伪 subagent 禁令见 `references/harness.md`。

## 真实性底线

1. **只从用户数据推断。** 外部知识只能帮助设计检验，不能替代证据。
2. **先质量，后归因。** 缺失、延迟、重复、口径变更、字段置空和粒度错配必须先进入数据质量门禁；数据事故不得被包装成业务异动。
3. **数字可复算。** 比率、基线、偏离、贡献度、显著性、置信区间必须能被复核：可以自己写一次性分析代码，也可以调用 `scripts/da_ops.py` 的可选算子，还可以混用。约束的是「可复核」，不是「用哪个脚本」。
4. **相关不等于因果。** 没有实验、准实验、时间顺序和可比对照时，用「同步出现」「与……一致」「高置信候选」「待验证假设」，不用「导致」「证明」「根因已确定」。
5. **每个异动单独判断。** 不用一个总区间或统一原因掩盖多个日期、渠道或用户群的不同机制。
6. **结论分级。** 事实、比较、解释、决策含义、行动建议分级输出；达不到的层级停在较低层级。

## 渐进式披露：只读这一步需要的文件

**本文件被刻意压到最小。** 不要一次读完 `references/`，也不要「先全部加载以防万一」——按下面的表在你真正进入该步骤时再读，读完即用，不预读、不复读、读过的不要重读。

| 你正在做什么 | 读这个 | 备注 |
|---|---|---|
| 问题模糊、准备反问 | `references/clarify.md` | 命中触发条件才读 |
| 倒推需要哪些结论与字段 | `references/backward-analysis.md` | S5 前读 |
| 选择本次视角与视觉组合 | `references/report-design.md` 的多样性一节 | S3 读 |
| 判断该用哪个方法 | `references/intent-routing.md`，再读命中的 1–2 个 `references/methods/*.md` | **不要整体读 methods/** |
| 需要行业 KPI 口径 | 先看 `references/industry-routing.md` 的模板索引，再读命中的那**一个** `references/industries/*.md`；行业不明用 `general.md` | 不要一次读多个 |
| 调用脚本算子做复核 | `references/ops-catalog.md` | 含全部脚本参数与门禁开关 |
| 落盘证据与结论 | `references/evidence-contract.md` | claims / evidence 字段 |
| 运行独立角色分析 | `references/harness.md` | 强制触发的完整协议 |
| 渲染 HTML 报告 | `references/report-design.md`，需要完整样例时读 `examples/report_spec.example.json` | 不要读 `examples/report_example.html`（脚本产物，约 8,000 token） |
| 组织中文措辞 | `references/writing-style.md` | 短文件 |

行业与方法文件只提供候选机制和适用条件，不规定报告结构、不规定必须画什么图。行业不明时用 `general.md`，不能靠文件名或单个字段拍脑袋识别行业；行业叙事只能提出候选机制，不能直接写成根因。

## 工作流（模型自主裁剪）

下面是思考顺序，不是固定工序。简单问题可以直接从 S3 跳到 S7；复杂问题可以增加你自己的中间步骤。

### S1 理解决策与数据边界

识别用户上传的 `.xlsx`、`.xls`、`.csv`、`.tsv`。提取用户原问题，不要把文件名当作业务结论。多文件时先理清主数据集、维表、字典和补充证据的关系，不把不同粒度的文件直接拼接。

### S2 摸底

回答结构问题：有哪些 sheet/字段、行粒度候选、时间覆盖、数值字段、缺失率、重复键、候选分子分母、候选维度。此阶段不写「增长」「下降」「原因」等业务判断。

```bash
python scripts/da_profile.py --data <文件路径> --out <运行目录>/01_profile.json
# 表里有「合计 / 小计」行时先对账：汇总行是表作者用公式算出来的真值，丢掉等于丢掉一次交叉验证
python scripts/da_reconcile.py --data <文件路径> --out <运行目录>/02_reconcile.json
```

Excel 要优先识别真正的表头，跳过标题行、说明行和合并单元格；表头无法可靠识别时标记 `header_uncertain`，不要悄悄猜列名。质量门禁不在本步骤执行，必须等 S5 确认字段口径后再跑。

### S3 选择本次分析视角（多样性决策点）

**前提：Grill-Me 门禁已通过。** 若问题仍模糊，本轮只输出数据快照 + 3–5 个反问 + 默认假设，然后停下等回答。

读 `references/report-design.md` 的多样性一节，选一个组合写入 `<运行目录>/variation.json`（含 `previous_signature` 与 `diff_from_previous`）。同一会话内禁止重复上一次的完整组合；用户对同一份数据连续追问「再分析一次」时，必须换一个此前未用过的主视角。

### S4 意图路由与方法组合

读 `references/intent-routing.md`，选一个主方法方向、零到两个辅助方向，再只加载命中的 `references/methods/*.md`。方法文件是分析提示词，不是必须逐条执行的步骤清单。

### S5 语义合同、质量门禁与追问收敛

追问集中在 S3 之前的 Grill-Me 完成；本步骤只处理残留小歧义，最多补问 1 轮。合同至少明确：决策、指标口径、粒度、时间窗、基线、维度、重要性阈值、假设、停止条件；字段来源标为 `confirmed`、`inferred_from_dictionary` 或 `assumed`。

```json
{
  "main_table": "主表名称",
  "date_field": "日期字段",
  "metric_fields": {"success_rate": "指标字段"},
  "quality": {"outlier_z": 4, "warning_z": 3, "delay_exclusion_minutes": 120}
}
```

```bash
python scripts/da_quality.py --profile <运行目录>/01_profile.json --data <文件路径> --contract <运行目录>/semantic_contract.json --out <运行目录>/03_quality.json
```

`date_field` 与 `metric_fields` 中显式指定的字段是权威口径；字段不存在时质量门禁报错，不会回退到名称相似字段。未提供合同时脚本才用名称候选推断，并标记 `name_inference_fallback`。

### S6 模型自主分析

分析本身由你完成：现场写一次性 pandas/numpy 代码探索假设、调用 `scripts/da_ops.py` 的单个算子做交叉复核，或两者混用。唯一硬性要求：每个写入报告的关键数字都要留下来源（文件、sheet、字段、过滤条件、公式、样本量），让第三方可以复算。

```bash
python scripts/da_ops.py <operator> --data <文件> --config <配置.json> --out <证据.json>
```

算子清单与参数见 `references/ops-catalog.md`；证据与结论的字段格式见 `references/evidence-contract.md`。

### S6.5 独立角色分析（强制）

命中 `references/harness.md` 任一强制触发条件时，必须完成 Locator、Mechanism、Falsifier、Reviewer 四个角色，各写独立 JSON 工件，四个齐备后才合并。运行时有原生 agent 工具则并行派发，没有则按串行隔离规则执行；不得用外部 CLI 进程或普通并发任务冒充 subagent。Reviewer 的 `downgrade` 必须接受，除非你能提供新的证据 ID。报告方法附录必须列出四个角色工件路径。

### S7 结论分级与真实性检查

| 层级 | 含义 | 可用措辞 |
|---|---|---|
| L0 | 可复核事实 | 「2026-07-27 支付成功率为 82.6%」 |
| L1 | 相对基线的比较 | 「低于同星期基线 11.6 个百分点」 |
| L2 | 有对账或强同步证据的解释 | 「与支付网关可用率同步降至 91.2%」 |
| L3 | 决策含义 | 「优先排查支付链路，不应先调整投放」 |
| L4 | 有责任人、条件和验收指标的行动 | 只有用户授权或明确要求时生成 |

一条 L2 解释至少需要两个独立证据或一个能闭合的分解。每条结论必须包含 `evidence_ids` 和 `limitations`。发布前运行：

```bash
python scripts/da_verify.py --claims <运行目录>/claims.json --evidence <运行目录>/evidence.json \
  --reconciliation <运行目录>/02_reconcile.json --agents-dir <运行目录>/agents --require-agent-manifest
```

你可以根据输出修正结论，但不允许为了通过检查而删除不利证据。**`da_verify` 无论 pass / warn / fail，本次运行都必须产出 HTML**：fail 时 HTML 顶部加红条「真实性检查未通过」+ 报告链接 + 必须修复的 issues 摘要。门禁开关（`--strict`、`--lenient-numbers`、`--require-evidence-ids` 等）见 `references/ops-catalog.md`。

### S8 亲自撰写报告

**你写规格 JSON，`scripts/da_report.py` 渲染 HTML。不要手写 HTML。**

```bash
python scripts/da_report.py --spec <运行目录>/report_spec.json --out <运行目录>/report.html
```

规格 schema、图表类型、主题与风格可选值、多样性写法、设计纪律与反模式，全部在 `references/report-design.md`。渲染器是纯本地模板拼接，零外部请求，输出即自包含离线 HTML。脚本会校验证据引用、层级取值、图表类型、`marker` 越界、降级字段与占位词；**校验不过时脚本拒绝出文件，你按它列出的 problems 修规格后重跑，直到渲染成功**。规格校验失败不是「可以不交付」的理由：连修几轮仍过不去，就退到最小可用规格（`meta.title` + 至少一条 `findings`）再渲染，并把未解问题写进 HTML 顶部，不允许让 `outputs/<run>/` 缺 `report.html`。

六段式骨架由脚本写死：核心发现 → 分析背景与目标 → 数据概况 → 深入分析 → 结论与建议 → 附录。在满足真实性的前提下，只变化视觉呈现、图表语法和深入分析的内部组织。报告必须包含「后续分析建议」，每条回答：还缺什么字段、补齐后能验证什么假设、需要什么样本/时间窗/实验设计、会影响什么决策。

### S8.5 交付前自检

规格校验已机器化（证据引用、层级、图表类型、占位词、降级字段）。仍需你逐项确认：

1. `outputs/<run>/report.html` 已写入磁盘且体积 > 4 KB；
2. 六段式齐全，「后续分析建议」单独成节；
3. 每条 L2+ 结论挂 `evidence_ids`，`limitations` 单独成节或随条挂载；
4. HTML 断网双击可直接打开，无 CDN / 远程字体 / 外部请求；
5. 若命中降级条件，顶部有可见 `degraded` 标志 + 已读 / 未读 / 降级原因；
6. 若本轮是 Grill-Me 反问轮，则确认**没有**产出 `report.html`，并且没有输出正式结论（唯一允许缺 HTML 的情形）。

未通过自检的运行不视为完成。

## 停止与降级条件

命中以下情况不要硬产出 L2 及以上结论：没有时间列或可用基线；只有比率没有分子分母；AB 实验 SRM 显著、分流单位重复或处理/对照不可比；因果问题没有处理时点、未处理组或重叠性不足；核心字段缺失或数据延迟导致关键指标不可用；分组不能加总，或口径出现不可解释的切换；决策对象完全不明确且不同决策会改变主指标。

**降级 ≠ 不交付。** 降级输出（结构画像、质量报告、关联性诊断、实验设计建议或待补数据清单）必须以 `report.html` 落到磁盘，顶部加 `degraded` 标志，写明「当前能回答什么」「当前不能回答什么」「降级原因」。L0 / L1 事实结论继续保留并标注 `level`。

## 语言与报告风格

结论先行、中文标点、标题直接陈述发现；不写自我夸奖、空泛口号和「建议持续关注」。建议必须有对象、动作、触发条件和验收指标；没有授权时只写分析上可执行的下一步，不替用户下业务命令。
