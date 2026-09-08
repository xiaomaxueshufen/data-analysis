## 欢迎关注

本项目由小马学数分开发完成

- [小红书主页](https://www.xiaohongshu.com/user/profile/6535d6c9000000000d005c77)
- [Bilibili 主页](https://space.bilibili.com/503535342)

本项目遵循 [PolyForm Noncommercial License 1.0.0](LICENSE)：非商用目的可自由使用、修改与分享，未经授权不得用于商业用途。王狗不得入内！

# Data Analysis Skill

这是一个多行业数据分析skill。用户上传 Excel 或 CSV 并提出问题后，模型自主识别决策意图、选择分析视角与方法组合、编写或调用计算、并撰写离线 HTML 报告。skill 只约束真实性边界，不固定视觉模板。确定性脚本仅作为可选的单点复核探针。


## 能力

- **异动定位**：稳健基线、异常日期、趋势断点、维度定位和机制候选。
- **漏斗分析**：阶段分母、转化率、流失量、瓶颈和可回收空间。
- **指标体系**：北极星、结果、过程、诊断、护栏、口径和看板最小集合。
- **AB 实验**：SRM、分流单位、效应、区间、显著性、异质性、护栏、功效/MDE 与 CUPED 方差缩减。
- **因果推断**：识别策略、处理/对照、可比性、增量估计和关联性降级。
- **用户分层**：动作前特征、分层规则、价值、规模、稳定性和动作映射；RFM 分位切点 + 8 段标签。
- **贡献度与比率拆解**：组内变化、结构变化、缺口对账、正负抵消和分子分母重算。
- **归因与触点**：多模型（last_touch / linear / time_decay / position_based / shapley / first_touch）渠道归因 + 对账 + 模型分歧度。
- **同期群留存**：仅用成熟 cohort 计算平均曲线，左截断披露。
- **生存与流失**：Kaplan-Meier 曲线 + log-rank 分组比较 + 删失披露。
- **路径分析**：转移矩阵、入口/出口、自环、高频路径与终点到达率。
- **价格弹性**：log-log 回归 + 反事实测算 + 识别策略门禁（无随机化最多 L1）。
- **异动断点检测**：季节性调整 + CUSUM + 水平切点（断点位置是数据挑选出来的，实际显著性弱于该数值）。
- **多重比较校正**：Bonferroni / Holm / BH-FDR；与 `da_verify.py` 的探索性结论警告联动。
- **报告交付**：单文件离线 HTML，恒为唯一交付物；触发 Grill-Me / 质量门禁 / SRM / da_verify 失败 / 降级时仍必须产出 `report.html`（降级报告同样以 HTML 形式落地）。

## 设计原则

1. 意图识别由模型完成，不用关键词硬编码替代业务判断。
2. 关键数字必须可复算：模型可以现场编写一次性分析代码，也可以调用可选算子复核；约束的是“可复核”，不是“必须用哪个脚本”。
3. 数据质量是分析门禁。缺失、延迟、字段置空和口径切换会进入排除区。
4. 相关不等于因果；无法验证的解释写成高置信候选或待验证假设。
5. 复杂问题优先由 Codex 原生 subagent 机制启动 Locator、Mechanism、Falsifier、Reviewer 四个独立 agent；前三个并行派发，Reviewer 最后执行。自定义 provider 或无原生工具时自动降级为串行隔离回退，绝不伪造 subagent。
6. 报告必须说明补充什么数据后可以回答什么当前回答不了的问题。
7. 报告多样性：内容骨架固定为原版六段式；同一会话内两次运行只变化视角、图表语法、版式节奏和深入分析的内部组织，事实数字保持一致。
8. Grill-Me 硬门禁：用户问题模糊时必须先反问再分析，反问轮不生成报告，停下等待回答；用户说“直接分析”才允许带默认假设继续。
9. 独立角色硬门禁：涉及“为什么/原因/异动”或 L2 及以上解释时，必须完成 Locator/Mechanism/Falsifier/Reviewer 四个角色的独立工件，缺一不可发布。
10. 执行留痕：每次运行写 `agents/execution.json`，标明 `native_subagents` 或 `serial_fallback`；原生模式必须记录四个 agent id，回退模式必须记录原因。
11. 离线动效报告：图表用纯 SVG/CSS/原生 JS 实现折线 draw-in、条形 grow-up、数字 count-up 与滚动显现，零外部请求，reduced-motion 与无 JS 均可完整阅读。

## 工作流

```
  文件与问题
    → 理解决策与数据边界
    → 摸底（可选 profile 脚本，也可自己写代码）
    → Grill-Me 反问硬门禁（模糊问题先反问，停下等回答）
    → 语义合同与数据质量门禁
    → 选择本次分析视角（多样性决策点）
    → 意图路由与方法组合
    → 模型自主分析（现场代码 + 可选算子复核）
    → 独立角色分析（Locator/Mechanism/Falsifier/Reviewer 工件）
    → 结论分级与真实性检查（da_verify）
    → 模型亲自撰写离线 HTML 报告（outputs/<run>/report.html）
    → 交付前自检：文件存在 + 体积 + 六段式 + 后续建议 + limitations + 降级标注 + 无占位词
```

交付物恒为 `outputs/<run>/report.html`。即使触发 Grill-Me 反问、质量门禁阻断、SRM 报警、识别策略不足、da_verify 失败或降级路径命中，也必须产出 HTML——降级报告以 HTML 形式交付并在文件顶部标注 `degraded` 模式 + 已读 / 未读 / 降级原因。

运行工件保存为：

```text
outputs/<run>/
├── 01_profile.json
├── semantic_contract.json
├── 03_quality.json
├── analysis.py（模型现场编写的分析代码）
├── agents/
│   ├── locator.json
│   ├── mechanism.json
│   ├── falsifier.json
│   ├── reviewer.json
│   └── execution.json
├── evidence.json
├── claims.json
├── variation.json
├── da_verify.json（发布前真实性检查结果）
└── report.html（必交交付物；降级 / 失败模式下也必须存在）
```

文件名只是建议，不是固定流水线；模型按本次分析的需要增删工件。但 `report.html` 与 `da_verify.json` 不可省略。

## 在 Codex 中安装

本 skill 已发布到 GitHub，仓库根目录包含 `SKILL.md`：

- 仓库地址：[https://github.com/xiaomaxueshufen/data-analysis](https://github.com/xiaomaxueshufen/data-analysis)

### 方式一：在 Codex 中直接安装（推荐）

1. 打开 Codex（桌面版、CLI 或 IDE 扩展均可），新建一个会话。
2. 让 Codex 用内置安装器安装，直接发送：

   > 请安装 data-analysis skill，仓库来源是 https://github.com/xiaomaxueshufen/data-analysis

   也可以先输入 `$skill-installer`，再把上面的仓库地址交给它。
3. 等待安装完成。Codex 通常会自动识别新 skill；如果输入 `$data-analysis` 时没有出现，请重启 Codex 或新建一个会话。

### 方式二：手动安装

如果当前版本的内置安装器不可用，可以把仓库内容手动放到 Codex 的 user skills 目录：

1. 下载或克隆仓库：`https://github.com/xiaomaxueshufen/data-analysis`
2. 将仓库根目录（包含 `SKILL.md`、`scripts/`、`references/`）放到 Codex 的 user skills 目录下，目录名保持为 `data-analysis`。
3. 重启 Codex 或新建会话。

user skills 目录的具体位置以当前 Codex 版本为准，可参考 [OpenAI 官方 Skills 文档](https://developers.openai.com/codex/skills)。

> 注意：`outputs/`、`__pycache__/` 属于运行缓存，不要把目录中的运行结果复制进 skill。

### 环境依赖

脚本依赖 `pandas>=2.0`、`numpy>=1.24`、`openpyxl>=3.1`。如果 Codex 提示缺少 Python 依赖，先在本地 Python 环境执行：

```bash
pip install -r requirements.txt
```

## 在 Codex 中使用

安装后有两种触发方式：

### 1. 显式调用

在新会话中输入 `$data-analysis`（或直接提到“用 data-analysis skill”），然后上传 Excel/CSV 或给出文件路径并描述业务问题。例如：

> 用 $data-analysis 分析这份电商支付数据，帮我定位主要异动。

### 2. 自动触发

上传或拖入 Excel/CSV 后直接提问即可，当任务匹配 skill 描述时 Codex 会自动加载本技能：

- “帮我看看这个数据”
- “这份支付成功率为什么下降，做一下漏斗和渠道拆解”
- “对这份用户数据进行分层，并说明还需要补什么字段”

分析完成后，Codex 会在运行目录 `outputs/<run>/` 中生成逐字段证据 JSON 和离线 HTML 报告（`report.html`），报告可直接用浏览器打开。报告遵循“结论先行、证据可回溯”的原则：数据质量问题会进入排除区，未经验证的同步关系只写成候选解释，不会冒充根因。

## 目录说明

- `SKILL.md`：主流程、停止条件、证据层级和报告要求。
- `references/intent-routing.md`：由模型完成的任务路由提示词。
- `references/clarify.md`：模糊问题的必要追问和默认假设协议。
- `references/harness.md`：多 agent 的角色提示词、输入隔离、JSON 输出和合并规则。
- `references/evidence-contract.md`：L0-L4 结论层级和发布门禁。
- `references/methods/`：异动、漏斗、指标体系、AB、因果、分层、贡献度、比率拆解、归因、同期群留存、生存/流失、路径分析、价格弹性、断点检测、实验设计与多重比较校正方法包。
- `references/industries/`：行业口径模板。当前包含通用、零售电商、互联网 SaaS、物流快递、自媒体/内容创作、教育培训、增长与广告投放、互金、互联网游戏、双边平台与市场、本地生活与 O2O 共 11 套；每套都按”适用信号 → 业务链路与统计对象 → KPI（定义/必要字段/禁止推断）→ 数据门禁 → 分析主题 → 行业叙事 → **常见数据陷阱** → 图表 → 降级路径”组织。
- `scripts/`：表头识别、结构画像、质量门禁、通用分析算子（17 个：`anomaly_scan`、`funnel_rates`、`contribution`、`ratio_decomp`、`ab_effect`、`segment_profile` + `attribution` / `cohort_retention` / `survival` / `path_analysis` / `rfm` / `price_elasticity` / `power_mde` / `srm_check` / `multiple_testing` / `cuped` / `changepoint_scan`）和真实性校验器（`da_verify.py` 已升级：未传 evidence 直接 fail、量纲严格匹配、L2+ 因果措辞必须挂合法 `identification_strategy`、探索性结论警告）。
- `examples/`：不参与运行时的示例报告，用于展示交付形态。

## 验证与降级

项目不携带示例数据或运行缓存；`examples/` 仅保留不参与运行时的展示报告。

没有时间列、没有基线、没有分子分母、实验 SRM 失败、因果没有可比对照或核心字段被数据质量事故污染时，skill 会停止对应分析或降级为结构画像、质量报告、关联性诊断和实验设计建议。
