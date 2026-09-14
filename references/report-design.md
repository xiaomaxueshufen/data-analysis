# 报告设计与渲染协议

报告由 `scripts/da_report.py` 渲染：**你只写紧凑的规格 JSON，脚本负责排版、图表、主题和动效**。不要手写 HTML——手写一份等价报告实测 7,810 token（`o200k_base`）/ 8,134（`cl100k_base`），写规格实测 2,736 / 3,043，约 1:2.9（口径与复算命令见 `README.md`「自检 · 测量口径」）。

```bash
python scripts/da_report.py --spec <运行目录>/report_spec.json --out <运行目录>/report.html
python scripts/da_report.py --emit-example <运行目录>/spec_example.json   # 需要模板时
```

渲染是纯本地模板拼接，零外部请求，输出即自包含离线 HTML。

完整示例看 `examples/report_spec.example.json`（那份 JSON 才是可读示例）；`examples/report_example.html` 是它的产物，**不要读**，读它拿不到规格写法还白费约 8,000 token。

## 固定六段式骨架

脚本按下面六段渲染，顺序由代码写死，你无法新增顶层章节：

1. **核心发现**：KPI 磁贴 + 3–5 条带证据 ID 的结论卡。
2. **分析背景与目标**：一段叙事。
3. **数据概况**：叙事 + 字段/质量表 + 脚注。
4. **深入分析**：每个机制一块，块内是 标题 + 解读 + 图表 + 表格。
5. **结论与建议**：结论列表 + 后续分析建议。
6. **附录**：证据索引表 + 口径与限制脚注。

## 规格 JSON

| 字段 | 必需 | 说明 |
|---|---|---|
| `meta.title` | 是 | 报告主标题 |
| `meta.decision` / `window` / `source` | 否 | 眉标、观察窗、来源 |
| `meta.subtitle` | 否 | 副标题，一句话写清报告边界 |
| `meta.quality` | 否 | `{"flag":"review","note":"..."}`，`review` 时页面显示质量告警胶囊 |
| `meta.degraded` | 降级时是 | `{"read":"...","unread":"...","reason":"..."}`，三者缺一校验报错 |
| `findings[]` | 是 | 每条 `{title, body, level, tone, evidence_ids[], limitations[]}` |
| `findings[].level` | — | `L0`–`L4`，写错校验报错 |
| `findings[].tone` | — | `positive` / `negative` / `neutral`，决定左侧色条 |
| `kpis[]` | 否 | `{label, value, unit, delta, direction, good_when_down}`；`unit` 取 `percent` / `pp` / 自由文本 |
| `background.narrative` | 否 | 第 2 段正文 |
| `data_overview` | 否 | `{narrative, table, notes[]}` |
| `analysis[]` | 否 | `{heading, narrative, charts[], tables[]}` |
| `conclusions[]` | 否 | `{text, evidence_ids[]}` |
| `next_steps[]` | 否 | `{question, data_needed}` |
| `appendix` | 否 | `{tables[], notes[]}` |
| `diversity` | 否 | 见下方「多样性」 |

图表对象：`{type, title, note, data[], ...}`，`type` 取 `line` / `bars` / `funnel` / `matrix` / `table`。

- `line`：`data[] = {label, value}`，可选 `baseline`（数值或 `{value,label}`）、`marker = {index, label}`（在某个数据点画竖线，`index` 从 0 起）。
- `bars`：`data[] = {label, value, display?, tone?, muted?}`；同号（全正或全负）统一**左端起笔、向右生长**，长度按 |value| 等比；只有正负混合时才画居中零线，正条向右、负条向左，两侧共用同一尺度。符号由数值标签与语义色承担，不靠几何方向表达。
- `funnel`：`data[] = {label, value}`，按占首阶段比例定条长，可选 `notes[]` 标阶段转化。
- `matrix`：`rows[]`、`columns[]`、`cells{"行|列": 数值}`，颜色深浅按全局极值映射，文字颜色按对比度自动切换。

脚本会拦截：缺 `evidence_ids`、未知 `theme`/`style`/图表类型、`marker.index` 越界、`degraded` 缺字段、正文里出现「待补/TODO/此处略」等占位词。**校验不过就不产出 HTML**，先修规格。

## 主题与风格

`diversity.theme` 默认 `apple-graphite`（墨色骨架 + 蓝色数据：标题、卡片、分隔线近黑，四类图表统一 Apple 蓝）；其余可选 `apple-light` 白底蓝、`apple-dark` 纯黑、`slate-amber`、`zinc-emerald`。`diversity.style`（`apple` 大留白大圆角 / `editorial` 紧凑衬线感）挑一个即可，不必每次全换。`diversity.motion` 设 `none` 可完全关闭进场动效。

主题切换不需要你改任何图表参数：着色、文字对比度、漏斗阶段标注位置都由脚本按主题自动处理。

需要在主题内部再分一层时，用两个可选键把「UI 强调色」和「图表数据色」拆开（写在 `THEMES` 里，模型日常不用碰）：

- `data`：折线 / 条形 / 漏斗的数据色，缺省等于该主题的 `accent`；
- `matrix_data`：矩阵格子的颜色，缺省等于 `data`。

默认主题 `apple-graphite` 就是这么配的：`accent` 保持墨色，只用于标题、卡片、分隔线和进度条；图表数据统一走 `data: "#0071e3"`。矩阵缺省跟随 `data`，所以折线 / 条形 / 漏斗 / 矩阵四类图都是蓝的；要让矩阵单独换色，再补 `matrix_data`。

正负语义色不受 `data` 影响：贡献图里数值为负的条形仍走 `neg`，不会被染成蓝色。

文字对比度会跟着新底色自动重算：达不到 4.5:1 时脚本把数值移到条形外。

## 多样性：同一会话内必须变化

两次报告的「主视角 × 视觉结构 × 图表语法 × 版式节奏」组合不得重复。事实数字保持一致，骨架固定，变的是切入角度与呈现。

- **主视角**：`decision` 决策 / `mechanism` 机制 / `structure` 结构 / `quality` 质量 / `opportunity` 机会 / `falsification` 反证。
- **视觉结构**：`pyramid` 结论先行 / `investigation` 现象→假设→检验→排除 / `contrast` 并列解释逐条裁决 / `layered-disclosure` 逐层展开 / `storyline` 时间线推进。
- **图表语法**：`baseline-overlay` 基线对照 / `decomposition` 缺口拆解 / `flow` 漏斗路径 / `distribution` 分布 / `matrix` 交叉 / `minimal-table` 只用表格。
- **版式节奏**：`dense-first` / `airy-narrative` / `card-based` / `longform`，写到 `diversity.density`（1–9）。
- **建议形态**：实验设计 / 补数清单 / 决策树 / 反证清单 / 监控口径。至少换一种，且不得写成「建议持续关注」。

生成前把本次选择写入 `variation.json`，含 `previous_signature` 与 `diff_from_previous`；差异要写具体，不能只写「换了个角度」。

## 视觉纪律

- 颜色分两层：UI 强调色（`accent`）+ 图表数据色（`data` / `matrix_data`）。每层各自只用一个色相；红绿仅用于涨跌/好坏，且必须同时有文字或箭头，不能只靠颜色。
- 图表文字必须真的能读：条内文字达不到 4.5:1 时，脚本把数值移到条外（暗色主题的亮强调色会命中这条）。
- 关键数字统一 `tabular-nums`；百分比、百分点、绝对量分开写。
- 每张图配一句「解读」，只回答一个问题。图注写清指标、时间窗、基线、单位、样本、排除区。
- 一两个头条数字用磁贴，不要画成一根柱子的柱状图；超过 7 个类目用排序表。
- 不用量值大小做彩虹渐变（改单一色相浅→深）；不用双 Y 轴（帕累托累计轴除外）。

### 反模式（会造成错误读数）

- **禁止对数值几何做动画**：条形生长、折线 draw-in、数字 count-up 都会在截图、打印、后台标签页里被冻结在中间态，读者看到的是错误数字。脚本已移除全部此类动效，只保留不改变几何的滚动显现，并在 1.5s 后强制全部显示。
- 不用大面积渐变、装饰插画、重阴影、emoji。
- 不用纯黑正文配霓虹紫蓝渐变；暗色主题只用 `apple-dark`。
- 不写「如图表所示」这类空转句，图下直接写结论。

## 交付前自检

规格校验已覆盖：证据引用、层级取值、图表类型、占位词、降级字段。仍需你自己确认：

- `outputs/<run>/report.html` 存在且体积 > 4 KB；
- 断网双击可打开；
- 每条 L2+ 结论的 `evidence_ids` 指向真实存在的证据，且 `da_verify` 已跑过；
- 降级运行时页面顶部有可见的 `degraded` 标志。
