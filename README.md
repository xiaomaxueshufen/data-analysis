## 欢迎关注

本项目由小马学数分开发完成

- [小红书主页](https://www.xiaohongshu.com/user/profile/6535d6c9000000000d005c77)
- [Bilibili 主页](https://space.bilibili.com/503535342)

本项目遵循 [PolyForm Noncommercial License 1.0.0](LICENSE)：非商用目的可自由使用、修改与分享，未经授权不得用于商业用途。王狗不得入内！

# Data Analysis Skill

这是一个多行业数据分析skill。用户上传 Excel 或 CSV 并提出问题后，模型自主识别决策意图、选择分析视角与方法组合、编写或调用计算、并撰写离线 HTML 报告。skill 只约束真实性边界，不固定视觉模板。确定性脚本仅作为可选的单点复核探针。


## 能力

- **表内对账**：读原始单元格，用表格自带的「合计 / 小计」行交叉验证每一条明细汇总；对不上就不放行，退出码可直接当流水线闸门。
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
- **报告交付**：模型只写紧凑的规格 JSON，`da_report.py` 渲染单文件离线 HTML（苹果风设计系统、纯 SVG 图表、零外部请求）。

## 设计原则

1. 意图识别由模型完成，不用关键词硬编码替代业务判断。
2. 关键数字必须可复算、可对账：模型可以现场编写一次性分析代码，也可以调用可选算子复核；表里有「合计 / 小计」行时，先用 `da_reconcile.py` 拿表自己的校验和交叉验证一遍。约束的是“可复核”，不是“必须用哪个脚本”。
3. 数据质量是分析门禁。缺失、延迟、字段置空和口径切换会进入排除区。
4. 相关不等于因果；无法验证的解释写成高置信候选或待验证假设。
5. 复杂问题优先由 Codex 原生 subagent 机制启动 Locator、Mechanism、Falsifier、Reviewer 四个独立 agent；前三个并行派发，Reviewer 最后执行。自定义 provider 或无原生工具时自动降级为串行隔离回退，绝不伪造 subagent。
6. 报告必须说明补充什么数据后可以回答什么当前回答不了的问题。
7. 报告多样性：内容骨架固定为原版六段式；同一会话内两次运行只变化视角、图表语法、版式节奏和深入分析的内部组织，事实数字保持一致。
8. Grill-Me 硬门禁：用户问题模糊时必须先反问再分析，反问轮不生成报告，停下等待回答；用户说“直接分析”才允许带默认假设继续。
9. 独立角色硬门禁：涉及“为什么/原因/异动”或 L2 及以上解释时，必须完成 Locator/Mechanism/Falsifier/Reviewer 四个角色的独立工件，缺一不可发布。
10. 执行留痕：每次运行写 `agents/execution.json`，标明 `native_subagents` 或 `serial_fallback`；原生模式必须记录四个 agent id，回退模式必须记录原因。
11. 报告渲染与内容分离：模型写规格 JSON，`da_report.py` 负责排版、图表和主题；禁止对数值几何做动画（条形生长 / 折线 draw-in / 数字 count-up 会在截图、打印、后台标签页里冻结成错误读数），只保留不改变几何的滚动显现并带超时兜底。
12. 渐进式披露：`SKILL.md` 常驻正文压到 5,000 token 以内，并给出「哪一步读哪个文件」的加载表；`references/` 按需读取，`methods/` 与 `industries/` 明确禁止整体加载。

## 参考标准

对账与数字溯源的设计参考了公开的建模规范，而不是任何同类 skill 的实现：

- ICAEW《Financial Modelling Code》—— *Include a master check*（任一检查失败即报警）、*Build traceable references*（每个数字可追回来源）；
- Twyman's Law —— 看起来有趣或异常的数字，通常是错的。

`da_reconcile.py`、`da_verify.py` 与 `da_report.py` 均为本项目独立实现（与同类项目对照过，除 import 与标点外无相同代码行）。

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
    → 表内对账（da_reconcile：用合计/小计交叉验证明细）
    → 结论分级与真实性检查（da_verify：按条目绑定 + 对账联动）
    → 模型撰写报告规格 JSON，da_report 渲染离线 HTML（outputs/<run>/report.html）
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
├── reconcile.json（表内对账结果；表里有合计/小计行时生成）
├── claims.json
├── variation.json
├── da_verify.json（发布前真实性检查结果）
├── report_spec.json（模型写的报告规格；排版与图表由 da_report 渲染）
└── report.html
```

文件名只是建议，不是固定值；模型按本次分析的需要增删工件。但 `report.html` 与 `da_verify.json` 不可省略。

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

分析完成后，Codex 会在运行目录 `outputs/<run>/` 中生成逐字段证据 JSON、表内对账结果（表里有合计/小计行时）和离线 HTML 报告（`report.html`），报告可直接用浏览器打开。报告遵循“结论先行、证据可回溯”的原则：数据质量问题会进入排除区，未经验证的同步关系只写成候选解释，不会冒充根因。

## 目录说明

- `SKILL.md`：主流程、停止条件、证据层级和报告要求；常驻正文 ≈ 4,900 token，内含「哪一步读哪个文件」的渐进式披露加载表。
- `references/intent-routing.md`：由模型完成的任务路由提示词。
- `references/clarify.md`：模糊问题的必要追问和默认假设协议。
- `references/harness.md`：多 agent 的角色提示词、输入隔离、JSON 输出和合并规则。
- `references/evidence-contract.md`：L0-L4 结论层级和发布门禁。
- `references/report-design.md`：报告规格 JSON schema、主题与风格可选值、多样性维度、设计纪律与反模式。合并了原 `report-html.md` / `html-report-design.md` / `report-diversity.md`。
- `references/methods/`：异动、漏斗、指标体系、AB、因果、分层、贡献度、比率拆解、归因、同期群留存、生存/流失、路径分析、价格弹性、断点检测、实验设计与多重比较校正方法包。
- `references/industries/`：行业口径模板。当前包含通用、零售电商、互联网 SaaS、物流快递、自媒体/内容创作、教育培训、增长与广告投放、互金、互联网游戏、双边平台与市场、本地生活与 O2O 共 11 套；每套都按”适用信号 → 业务链路与统计对象 → KPI（定义/必要字段/禁止推断）→ 数据门禁 → 分析主题 → 行业叙事 → **常见数据陷阱** → 图表 → 降级路径”组织。
- `scripts/`：报告渲染器（`da_report.py`：规格 JSON → 自包含离线 HTML，五套主题、四种 SVG 图表、六段式骨架由代码写死，校验证据引用 / 层级 / 图表类型 / 占位词）、表头识别、结构画像、质量门禁、表内对账（`da_reconcile.py`：读原始单元格，用合计/小计行交叉验证明细，退出码可直接当流水线闸门）、通用分析算子（17 个：`anomaly_scan`、`funnel_rates`、`contribution`、`ratio_decomp`、`ab_effect`、`segment_profile` + `attribution` / `cohort_retention` / `survival` / `path_analysis` / `rfm` / `price_elasticity` / `power_mde` / `srm_check` / `multiple_testing` / `cuped` / `changepoint_scan`）和真实性校验器（`da_verify.py` 0.7.0：数字按 `evidence_ids` 绑定到具体证据条目、对账条目联动拦截、方向与符号一致的量纲匹配、负号与千分位可解析、序号不参与溯源、L2+ 因果措辞漏填识别策略即 fail），以及所有 CLI 共用的启动自检与输入防护（`da_envcheck.py`：缺 numpy / pandas 时给出可执行的安装指引，而不是裸 traceback；`da_common.py`：统一路径校验、坏输入结构化报错、非有限数值写成 `null` 保证 JSON 合法）。
- `tests/`：不参与运行时的回归测试，全部使用内存合成数据；运行方式和覆盖范围见下面「自检」一节。
- `examples/`：不参与运行时的示例报告，用于展示交付形态。

## 自检

仓库自带回归测试，全部用内存合成数据，不需要示例数据文件：

```bash
pip install -r requirements.txt pytest   # pytest 只用于自检，不是 skill 的运行依赖
python -m pytest tests/ -q               # 5 个模块，68 项
python tests/test_report.py              # 每个文件也能单独执行，打印逐项 PASS/FAIL
```

覆盖范围：算子性质（`test_operators`）、表内对账（`test_reconcile`）、报告渲染与规格校验（`test_report`）、
真实性门禁（`test_verify`）、CLI 健壮性（`test_cli_robustness`：坏输入不抛栈、缺依赖给安装指引、
17 个算子 × 8 种退化输入只允许「正常返回」或「DataError」）。

## 验证与降级

项目不携带示例数据、测试报告或运行缓存；`examples/` 仅保留不参与运行时的展示报告（可读的规格示例 + 它的渲染产物）。

没有时间列、没有基线、没有分子分母、实验 SRM 失败、因果没有可比对照或核心字段被数据质量事故污染时，skill 会停止对应分析或降级为结构画像、质量报告、关联性诊断和实验设计建议。
