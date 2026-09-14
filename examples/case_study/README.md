# 案例：真实公开数据的收入异动复盘

这个目录是一次**完整跑通**的分析运行：从原始交易明细出发，经过清洗、表内对账、异动与断点检测、
风险角色审查、真实性门禁，最后渲染出一份离线 HTML 报告。它和 `examples/` 下那份示例报告的区别是：
**数据是真实的公开交易流水，不是合成数据**；每个数字都能沿 `run/evidence.json` 回溯到文件、字段与算子。

## 数据来源与"脱敏"的确切含义

- 来源：UCI Machine Learning Repository, **Online Retail II**（<https://archive.ics.uci.edu/dataset/502/online+retail+ii>），
  许可 **CC BY 4.0**，欢迎引用。
- 内容：一家英国线上零售商 2009-12-01 至 2011-12-09 的 1,067,371 行真实交易明细（发票号、商品码、
  数量、单价、客户编号、国家）。
- **脱敏口径**：本仓库只提交**聚合到「日 × 区域」的派生表**（`data/retail_daily.csv`，66KB），
  不提交原始明细，也不包含任何单笔订单或客户级记录。原始数据集本身已不含姓名、地址等直接标识，
  客户编号是原数据集自带的匿名编号。
- 这份数据是**公开数据集，不是任何客户的内部数据**。它不能替代"真实业务脱敏案例"：如果要用自家数据
  复现同样的流程，把 `--raw` 换成自己的明细、按 `build_dataset.py` 里的口径改写聚合逻辑即可。

## 怎么复现

```bash
# 1. 原始明细（90MB，不在仓库里）：按 build_dataset.py 里记录的地址获取，sha256 必须一致
python examples/case_study/build_dataset.py --raw /path/to/online_retail_II.csv
#    没有原始文件时：--download 会从镜像拉取

# 2. 表内对账（表里带「合计」行，可以当校验和）
python scripts/da_reconcile.py --data examples/case_study/data/retail_daily.csv \
  --out examples/case_study/run/02_reconcile.json

# 3. 一次性分析代码 + 算子复核
python examples/case_study/run/analysis.py > examples/case_study/run/analysis_output.json
python scripts/da_ops.py anomaly_scan --data examples/case_study/data/retail_daily.csv \
  --config examples/case_study/run/anomaly_config.json --out examples/case_study/run/anomaly_scan.json
python scripts/da_ops.py changepoint_scan --data examples/case_study/data/retail_daily.csv \
  --config examples/case_study/run/changepoint_config.json --out examples/case_study/run/changepoint_scan.json
python scripts/da_ops.py contribution --data examples/case_study/run/window_table.csv \
  --config examples/case_study/run/contribution_config.json --out examples/case_study/run/contribution.json

# 4. 发布前门禁（四角色工件 + 对账联动 + 数字溯源）
python scripts/da_verify.py --claims examples/case_study/run/claims.json \
  --evidence examples/case_study/run/evidence.json \
  --reconciliation examples/case_study/run/02_reconcile.json \
  --agents-dir examples/case_study/run/agents --require-agent-manifest

# 5. 渲染报告
python scripts/da_report.py --spec examples/case_study/run/report_spec.json \
  --out examples/case_study/run/report.html
```

CI 会跑第 2、4、5 步：案例的结论一旦不再能溯源、或报告不再能逐字节复现，流水线直接失败。

## 这次运行得出的结论

| 结论 | 等级 | 证据 |
|---|---|---|
| 11 月比 8–10 月月均高 54.26%（1,426,587.54 对 924,820.11），但同比只高 2.29% | L1 | E005 / E006 |
| 增量集中在英国：占缺口 98.08%，英国在全期占 85.43% | L1 | E009 / E008 |
| 12 月上旬的"断崖"是数据截断 + 一笔被取消的订单（168,469.60 当日冲回 168,789.07） | L2 | E010 / E011 |
| 日异动第一名 2011-09-20 不是单笔大单（77 个订单、1,718 行、最大单笔 7,144.72） | L1 | E012 |
| 水平位移落在 2011-09-21（62.08%，t 9.28），但位移后仅 69 天且与旺季重叠 | L1 | E013 |
| 22.24% 的行缺客户 ID，用户级漏斗/留存/复购在这份数据上不可做 | L0 | E004 |

Reviewer 把两条原本写成 L2 的解释降级为 L1（`run/agents/reviewer.json` 的 verdict 字段），
`claims.json` 里保留的是降级后的版本——这是门禁生效的证据，不是缺陷。

## 三个值得注意的真实数据陷阱

1. **毛销售额会被取消订单骗到**：2011-12-09 毛销售额里有一笔 168,469.60 的单笔，同日就被冲回。
   用毛销售额做异动检测，会把"取消"读成"暴涨"。
2. **完全重复行占 3.23%**：按发票号+商品码+数量+时间+单价+客户编号六列全等判定。去重让总额下降
   456,811.41（2.41%），但也让"单日最高值"从 110,623.68 变成另一个数——单日极值对口径敏感。
3. **日历日 ≠ 交易日**：739 个日历日里 135 天没有任何记录，其中 104 天是周六。任何"日均"都必须按
   交易日算；异动基线也不能把缺失日补 0。

## 数字的测量口径

这份案例里出现的效能数字（token、覆盖率）只有一套口径，写在 `README.md` 的「自检 · 测量口径」，这里不重复定义：

- **token**：`pip install tiktoken && python scripts/da_measure.py`。按编码器分别给（同一份文本在 `o200k_base` 与 `cl100k_base` 下差 20% 以上，只报一个数等于没报口径）。
- **覆盖率**：`COVERAGE_PROCESS_START=$PWD/.coveragerc python -m pytest tests/ -q --cov=scripts --cov-report=term`，统计 `scripts/` 整仓，当前合计 **81%**。`COVERAGE_PROCESS_START` 不能省——测试是 subprocess 调用 CLI 的，不打开它 `da_verify` / `da_reconcile` / `da_report` 会记成 0%。
- **案例自身的业务数字**：全部来自 `data/retail_daily.csv` 的聚合口径，清洗规则与每一步影响的记录数/金额写在 `build_dataset.py` 的 `CLEANING` 输出里；加 `--keep-duplicates` 可复现未去重版本（总额 19,385,363.27，比去重后的 18,928,551.86 高 2.41%）。
- **报告可复现**：`report.html` 是 `report_spec.json` 的确定性渲染产物，CI 会逐字节比对；改了规格却不重新渲染，流水线直接失败。

## 运行目录里的工件

| 文件 | 作用 |
|---|---|
| `01_profile.json` | 表头、字段、缺失、时间覆盖（da_profile） |
| `02_reconcile.json` | 表内对账：合计行 vs 明细，6 项一致（da_reconcile） |
| `analysis.py` / `analysis_output.json` | 一次性分析代码与它的输出 |
| `anomaly_scan.json` / `changepoint_scan.json` / `contribution.json` | 算子复核证据 |
| `window_table.csv` / `contribution_config.json` | 贡献度算子的窗口过滤输入（基线月均 vs 当前月） |
| `evidence.json` | 证据条目 E001–E016，每条带文件、字段、口径 |
| `claims.json` | 15 条结论，含 level、evidence_ids、limitations |
| `agents/*.json` | Locator / Mechanism / Falsifier / Reviewer 四个角色工件 + 执行留痕 |
| `da_verify.json` | 发布前真实性检查结果（status: pass） |
| `report_spec.json` / `report.html` | 报告规格与渲染产物（自包含离线 HTML） |

> 执行模式：`agents/execution.json` 记录为 `serial_fallback`。本次是仓库维护时重建案例工件，
> 原生 subagent 工具可用但没有派发，四个角色按 `references/harness.md` 的**串行隔离**规则依次执行、
> 各自落盘。想验证真实 subagent 模式，请在有原生派发工具的会话里按 harness 重跑。
