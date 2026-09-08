---
name: data-analysis
description: 面向决策的数据分析 skill。用户上传 Excel/CSV 并提出业务问题时触发，覆盖异动分析、漏斗与转化、指标体系、AB 实验、因果推断、用户分层、贡献度与比率拆解、归因、同期群留存、生存/流失、路径分析、RFM、价格弹性、CUSUM 断点检测、SRM/CUPED、功效/MDE 与多重比较校正。模糊问题必须先 Grill-Me 反问再分析；正式结论必须通过 Locator/Mechanism/Falsifier/Reviewer 独立角色工件门禁与量纲严格匹配的数字溯源；模型在固定六段式内容骨架内自主变化视觉、图表和深入分析内部组织，真实性由 da_verify 约束。即使用户只说“帮我看看这个数据”，也应使用本 skill。
---

# 数据分析 Skill

你是主分析师。本 skill 的所有文本都只是思考辅助，不是必须逐步执行的流水线；`scripts/` 里的工具都是可选探针，不是报告生成器。每次分析由你自主决定：问题如何拆解、用什么视角切入、做哪些计算、如何组织证据、如何做视觉与图表。报告内容骨架固定为原版六段式。

## 三条不可协商的目标

1. **内容真实。** 只从用户数据推断，不把外部常识写成数据已证明的事实；数字必须可复算、可溯源；相关不等于因果；结论强度不能超过证据强度。
2. **视觉每次不同。** 同一会话内，两次运行的报告必须在分析视角、图表语法、版式节奏、视觉主题中至少有三项明显不同；事实数字保持一致，内容骨架固定。具体变化维度见 `references/report-diversity.md`。
3. **交付物恒为 HTML。** 每个 `outputs/<run>/` 必须有一份 `report.html`——单一交付物，不可被 Markdown、文字回复、终端输出或 JSON 替代。无论触发 Grill-Me 反问、数据质量门禁阻断、da_verify 失败、SRM 报警、识别策略不足、降级路径命中，**都必须产出 HTML**；降级报告同样以 HTML 形式交付，并在文件顶部显式标注 `degraded` 模式 + 已读数据、未读数据、降级原因。

如果这三个目标冲突（例如为了”每次不同”而夸大或编造，或为了”通过 da_verify”而删除不利证据），真实性优先；如果真实性和”产出 HTML”冲突（例如 da_verify 报 fail），仍必须产出 HTML——把 fail 事实写进 HTML 顶部的真实性检查条，不允许以”没过 verify 所以不交付”为由跳过。

## 两个必须执行的硬门禁

1. **Grill-Me 反问门禁。** 用户问题模糊时，必须先反问再分析；反问的那一轮不生成报告、不输出正式结论，停下等用户回答。协议见 `references/clarify.md`。
2. **独立角色分析门禁。** 只要问题涉及“为什么/原因/异动”或结论会达到 L2 及以上，必须完成 Locator、Mechanism、Falsifier、Reviewer 四个角色的独立分析并留下工件；缺任何一件，报告不得发布。协议见 `references/harness.md`。

## 真实性底线

1. **只从用户数据推断。** 外部知识只能帮助设计检验，不能替代证据；不把业务常识、行业经验、常见原因写成这份数据已经证明的事实。
2. **先质量，后归因。** 缺失、延迟、重复、口径变更、字段置空和粒度错配必须先进入数据质量门禁；数据事故不得被包装成业务异动。
3. **数字可复算。** 比率、基线、偏离、贡献度、显著性、置信区间等关键数字必须能被复核：你可以自己写一次性分析代码，也可以调用 `scripts/da_ops.py` 的可选算子，还可以两者混用。约束的是“可复核”，不是“必须用哪个脚本”。
4. **相关不等于因果。** 没有实验、准实验、时间顺序和可比对照时，使用“同步出现”“与……一致”“高置信候选”“待验证假设”，不要使用“导致”“证明”“根因已确定”。
5. **每个异动单独判断。** 不用一个总区间或一个统一原因掩盖多个日期、渠道或用户群的不同机制。
6. **结论分级。** 事实、比较、解释、决策含义、行动建议分级输出；达不到的层级停在较低层级。

## 脚本定位：可选探针，不是流水线

| 脚本 | 定位 | 是否必须 |
|---|---|---|
| `scripts/da_profile.py` | 快速摸清 sheet、字段、类型、缺失、时间覆盖 | 可选 |
| `scripts/da_quality.py` | 快速生成质量门禁 JSON | 可选 |
| `scripts/da_ops.py` | 单点复核算子（基线、漏斗、贡献、AB、分层、比率拆解、归因、留存、生存、路径、RFM、弹性、SRM、CUPED、功效/MDE、多重比较、断点检测） | 可选 |
| `scripts/da_stats.py` | 实验设计与统计算子（`power_mde`、`srm_check`、`multiple_testing`、`cuped`、`changepoint_scan`） | 可选 |
| `scripts/da_growth.py` | 增长与生命周期算子（`attribution`、`cohort_retention`、`survival`、`path_analysis`、`rfm`、`price_elasticity`） | 可选 |
| `scripts/da_verify.py` | 发布前真实性检查：证据引用、因果措辞、量纲严格的数字溯源、识别策略门禁、探索性结论警告 | 推荐运行 |

`da_ops.py` 注册了 17 个算子，分两类：
- **数据驱动算子**（`anomaly_scan`、`funnel_rates`、`contribution`、`ratio_decomp`、`ab_effect`、`segment_profile` + 11 个新增）需要 `--data`；
- **纯设计算子**（`power_mde`、`multiple_testing`）不需要数据，只看输入参数返回样本量 / 调整后 p 值。

`da_verify.py` 的硬规则（发布必跑）：
- **未传 `--evidence` 直接 fail**（默认开启；`--no-require-evidence` 显式关闭）；
- **数字溯源按量纲严格匹配**：raw / percent / 百分点（pp）三种量纲独立，反向不互换；
- **L2+ 因果措辞必须给合法 `identification_strategy`**（`randomized` / `did` / `matching` / `iv` / `rdd` / `synthetic_control` 等）；
- **探索性结论数 > `--max-exploratory-tests`（默认 5）触发 `multiple_comparison_risk`**；
- **同一时间窗被多条结论引用触发 `repeated_window_checks`**；
- **`--strict` 把数字溯源警告升级为 fail**。

没有任何脚本是强制路径。你可以现场编写一次性 pandas/Python 代码完成全部计算；这正是本 skill 鼓励的做法。确定性脚本只在两类场景使用：想快速摸底、想交叉复核某个关键数字。

## 工作流

下面是思考顺序，不是固定工序。简单问题可以直接从 S3 跳到 S7；复杂问题可以增加你自己的中间步骤。

### S1. 理解决策与数据边界

识别用户上传的 `.xlsx`、`.xls`、`.csv`、`.tsv`。提取用户原问题，不要把文件名当作业务结论。多文件时先理清主数据集、维表、字典和补充证据的关系，不把不同粒度的文件直接拼接。

### S2. 摸底（可用脚本，也可自己写代码）

目的是回答结构问题：有哪些 sheet/字段、行粒度候选、时间覆盖、数值字段、缺失率、重复键、候选分子分母、候选维度、样例值。此阶段不写“增长”“下降”“原因”等业务判断。

```bash
python scripts/da_profile.py --data <文件路径> --out <运行目录>/01_profile.json
```

Excel 需要优先识别真正的表头，跳过标题行、说明行和合并单元格；表头无法可靠识别时标记 `header_uncertain`，不要悄悄猜列名。质量门禁不在本步骤执行；它必须等 S5 的语义合同确认字段口径后再运行。

### S3. 选择本次分析视角（多样性决策点）

**进入本步骤的前提：Grill-Me 门禁已通过。** 若用户问题仍处于模糊状态（触发 `references/clarify.md` 的任一条件），本轮输出只包含数据快照 + 3–5 个反问 + 默认假设，然后停下等待用户回答；禁止直接进入分析。

在动手计算前，先读取 `references/report-diversity.md`，从“分析主视角、辅助视角、视觉结构、图表语法、版式节奏、建议形态”中为本次运行选一个组合，并写入运行清单：

```json
{
  "variation": {
    "primary_lens": "decision|mechanism|structure|quality|opportunity|falsification",
    "visual_structure": "pyramid|investigation|contrast|layered-disclosure|storyline",
    "chart_grammar": "baseline-overlay|decomposition|flow|distribution|matrix|minimal-table",
    "layout_rhythm": "dense-first|airy-narrative|card-based|longform",
    "previous_run_signature": "上次运行已用组合，本次必须避开"
  }
}
```

同一会话内禁止重复上一次的完整组合。如果用户在同一会话里对同一份数据连续追问“再分析一次”，必须换一个此前未用过的主视角（例如上次从决策视角切入，这次从反证视角切入），而不是只换几个词。

### S4. 意图路由与方法组合

阅读用户问题和摸底结果，从以下方法方向中选择一个主方向、零到两个辅助方向。方法文件（`references/methods/*.md`）是分析提示词，不是必须逐条执行的步骤清单。

- 异动定位（`anomaly.md`）；
- 漏斗与转化（`funnel.md`）；
- 指标体系（`metric-system.md`）；
- AB 实验与因果（`ab-test.md`、`causal.md`）；
- 用户分层（`segmentation.md`、`rfm.md`）；
- 贡献度与比率拆解（`contribution.md`、`ratio-decomp.md`）；
- 归因与触点（`attribution.md`）；
- 同期群留存（`cohort-retention.md`）；
- 生存与流失（`survival.md`）；
- 路径分析（`path-analysis.md`）；
- 价格弹性（`price-elasticity.md`）；
- 异动断点检测（`changepoint.md`）；
- 实验设计与统计（`experiment-design.md`、`multiple-testing.md`）。

路由前先读取 `references/backward-analysis.md`，从用户要做的决定倒推需要相信的结论、比较、基线/对照、字段粒度、质量状态、方法和图表。如果关键字段或对照不存在，先输出降级答案和补数方案，不为了完成图表而把结论升级。

### S5. 语义合同、质量门禁与追问收敛

追问集中在 S3 之前的 Grill-Me 门禁完成；本步骤只处理用户回答后仍残留的小歧义，最多补问 1 轮。合同至少明确：决策、指标口径、粒度、时间窗、基线、维度、重要性阈值、假设、停止条件。字段来源标为 `confirmed`、`inferred_from_dictionary` 或 `assumed`。

把确认结果保存为 `semantic_contract.json`。`date_field` 与 `metric_fields` 中显式指定的字段是权威口径；若字段不存在，质量门禁报错，不会回退到名称相似字段。未提供合同时，脚本才使用名称候选推断，并在输出中标记 `name_inference_fallback`。

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

### S6. 模型自主分析

这是本 skill 与旧版最大的区别：**分析本身由你完成**。你可以：

- 现场编写一次性 pandas/numpy 代码，探索任何你觉得值得检验的假设；
- 调用 `scripts/da_ops.py` 的单个算子做交叉复核；
- 两者混用。

唯一硬性要求：每个写入报告的关键数字都要留下来源（文件、sheet、字段、过滤条件、公式、样本量），让第三方可以复算。运行目录里保存你的分析代码和证据 JSON，但不要求固定的 00–07 文件名序列。

```bash
python scripts/da_ops.py <operator> --data <文件> --config <配置.json> --out <证据.json>
```

可选算子目录见 `references/ops-catalog.md`。

### S6.5 独立角色分析（强制）

只要命中 `references/harness.md` 的任一强制触发条件（用户问“为什么/原因/异动”、结论将达 L2 及以上、涉及两个以上方法方向等），必须执行 Locator、Mechanism、Falsifier、Reviewer 四个角色：

- 运行时有原生 agent 工具则分别派发；没有则由主模型串行执行，但每个角色只读自己的输入、独立写出 `agents/<role>.json`，四个工件齐备后才合并；
- Reviewer 的 `downgrade` 必须接受，除非主模型提供新的证据 ID；
- 报告方法附录必须列出四个角色工件路径。

### S7. 结论分级与真实性检查

结论对象使用以下层级：

| 层级 | 含义 | 可用措辞 |
|---|---|---|
| L0 | 可复核事实 | “2026-07-27 支付成功率为 82.6%” |
| L1 | 相对基线的比较 | “低于同星期基线 11.6 个百分点” |
| L2 | 有对账或强同步证据的解释 | “与支付网关可用率同步降至 91.2%” |
| L3 | 决策含义 | “优先排查支付链路，不应先调整投放” |
| L4 | 有责任人、条件和验收指标的行动 | 只有用户授权或明确要求时生成 |

一条 L2 解释至少需要两个独立证据或一个能闭合的分解。每条结论必须包含 `evidence_ids` 和 `limitations`。

发布前运行真实性检查：

```bash
python scripts/da_verify.py --claims <运行目录>/claims.json --agents-dir <运行目录>/agents --require-agent-manifest [--evidence <运行目录>/evidence.json] [--numeric-tolerance 0.051]
```

它会检查证据引用、因果措辞、L2 门槛、四个角色工件是否齐全和数字溯源量纲。你可以根据输出修正结论，但不允许为了通过检查而删除不利证据。**da_verify 无论 pass / warn / fail，本次运行都必须产出 HTML**：fail 时 HTML 顶部加红条"真实性检查未通过"+ `da_verify` 报告链接 + 必须修复的 issues 摘要。

### S8. 亲自撰写报告

**报告由你亲自编写，不套用固定模板，但交付物形态恒为 `outputs/<run>/report.html`。** 你直接生成离线 HTML 文件，自主决定：

- 标题怎么写、首屏强调什么、视觉节奏、图表语法；
- 用哪些图表类型（SVG/表格/文字卡片均可）、如何配色、如何排版；
- 哪些结论放首屏、哪些放附录、哪些只写一句话。

撰写前先读取 `references/html-report-design.md`，按其中的排版系统和**离线动效模式库**实现图表：折线 draw-in、条形 grow-up、磁贴 count-up、异常点脉冲、滚动显现。动效只做视觉进场，所有数字必须预先算好写死在标记里；命中 `prefers-reduced-motion` 或禁用 JS 时必须静态完整可读。

多样性约束（见 `references/report-diversity.md`）：

- 视觉主题、图表语法、版式节奏每次都要变化；章节顺序固定为六段式；
- 不使用”固定报告，不提供改变口径的控件”这类模板化语句；
- 不复用上一次运行的完整段落骨架，只复用经确认无误的事实数字；
- 报告必须包含”后续分析建议”，每条回答：还缺什么字段、补齐后能验证什么假设、需要什么样本/时间窗/实验设计、会影响什么决策。

### S8.5 交付前自检（不可省略）

写完 `report.html` 之后，必须逐项打勾后才能告诉用户”完成”：

1. 文件存在：`outputs/<run>/report.html` 已写入磁盘，体积 > 4 KB（小于 4 KB 通常是没图没表的占位 HTML，必须补内容）；
2. 结构完整：HTML 内含六段式骨架对应的 6 个一级 heading（或可视化卡片组），`后续分析建议` 单独成节；
4. 真实性标注：每条 L2+ 结论挂 `evidence_ids`；`limitations` 单独成节或随条挂载；
5. 自包含：HTML 在浏览器双击可直接打开，不依赖外部 CDN、本地资源或网络请求；
6. 降级标注：若命中”停止与降级条件”，HTML 顶部必须可见 `degraded` 标志 + 已读 / 未读 / 降级原因；不得隐藏降级事实只交付结论。
8. 占位文件检测：HTML 内不能出现”待补””TODO””此处略””图表待生成”等占位词。命中任意一条 → 必须补完再交付。

未通过 S8.5 自检的运行不视为完成；必须补完报告后再回复用户。

## 行业视角与方法文件：只是思考辅助

`references/industries/*.md` 帮你更快识别业务链路和常用 KPI，`references/methods/*.md` 帮你检查方法适用条件和降级路径。当前行业模板：

- `general.md`：通用口径；
- `internet-saas.md`、`retail-ecommerce.md`、`logistics-express.md`、`social-media-content.md`、`education-training.md`：既有五大行业；
- `growth-advertising.md`、`fintech.md`、`gaming.md`、`marketplace.md`、`local-services.md`：增长 / 互金 / 游戏 / 双边 / 本地生活 五大新增行业。

它们不规定报告结构、不规定必须画什么图、不规定必须输出哪些章节。行业不明时用 `general.md`，不能用文件名或单个字段拍脑袋识别行业。行业叙事只能提出候选机制，不能直接写成根因。你不用全部阅读，只需要找对应行业内容进行加载即可。

## 独立角色分析（强制门禁）

复杂问题**必须**完成独立角色分析：Locator（只找事实变化）、Mechanism（只找同步与被排除的解释）、Falsifier（主动找反例与数据事故）、Reviewer（发布前逐条审查）。每个角色输出独立 JSON 工件；运行时有原生 agent 工具则并行派发，没有则按隔离规则串行执行。纯描述性统计（行数、字段清单、缺失率）才允许跳过。协议见 `references/harness.md`。

### 四个 subagent 的启动规则

1. 只有 Codex 原生 subagent/agent-thread 机制创建的线程才能称为 subagent。不得用 shell 命令、普通并发任务、外部 Codex CLI 进程或普通用户新线程伪装成 subagent。
2. 原生模式必须按三段执行：先在同一轮连续派发 `locator`、`mechanism`、`falsifier`，三者彼此不读取输出；三者完成并落盘后再派发 `reviewer`；最后才允许合并与写报告。不要在每个角色之间穿插等待或主模型解释。
3. 原生 subagent 工具不存在、provider/model 无法发出工具调用、模型返回文本 `UNSUPPORTED`、或工具运行失败时，不得声称已经启动 subagent。Provider 能力失败不重试；真实工具调用错误每个角色最多重试一次。
4. 任一前置角色重试后仍失败，默认切换到 `references/harness.md` 的串行隔离回退；如果用户明确要求必须使用真实 subagent，则停止并说明失败原因，不能生成报告。
5. 串行回退仍必须生成四个独立 JSON 工件，并在最终报告中说明执行模式为“串行隔离回退”，不得把它包装成真实 subagent 运行。
6. 每次运行必须写 `agents/execution.json`，记录 `mode`、原生工具可用性、每个角色的 agent id 或失败原因、回退原因。发布校验时传入 `--require-agent-manifest`，防止把回退伪装成原生 subagent。

## 停止与降级条件

命中以下情况，不要硬产出 L2 及以上结论：

- 要求趋势/异动，但没有时间列或没有可用基线；
- 要求贡献度拆解，但只有比率没有分子分母；
- AB 实验 SRM 显著、分流单位重复或处理/对照无法比较；
- 因果问题没有处理时点、没有未处理组或重叠性不足；
- 核心字段缺失或数据延迟导致关键指标不可用；
- 分组不能加总，或指标口径在数据中出现不可解释的切换；
- 决策对象完全不明确，且不同决策会改变主指标或分析方向。

**降级 ≠ 不交付 HTML。** 降级输出（结构画像、质量报告、关联性诊断、实验设计建议或待补数据清单）必须以 `report.html` 形式落到磁盘，文件顶部加 `degraded` 标志，必须明确”当前能回答什么””当前不能回答什么””降级原因”。L0 / L1 事实结论继续保留并标注 `level`；不可跳过 HTML。

## 语言与报告风格

结论先行、中文标点、标题直接陈述发现；不写自我夸奖、空泛口号和“建议持续关注”。建议必须有对象、动作、触发条件和验收指标；若没有授权，只写分析上可执行的下一步，不擅自替用户下业务命令。报告内容骨架固定为原版六段式；在满足真实性的前提下，只变化视觉呈现、图表语法和深入分析的内部组织。
