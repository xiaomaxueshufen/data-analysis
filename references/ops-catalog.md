# 可选验证算子目录

这些算子是**可选的单点复核工具**，不是分析流水线。模型可以现场编写一次性代码完成全部分析，也可以在需要交叉验证某个关键数字时调用其中某个算子。没有任何算子是必经路径。

各脚本入口：

```bash
python scripts/da_profile.py --data <文件路径> --out <profile.json>
python scripts/da_quality.py --profile <profile.json> --data <文件路径> --contract <semantic_contract.json> --out <quality.json>
python scripts/da_ops.py <operator> --data <文件路径> --config <配置.json> --out <证据.json>
python scripts/da_verify.py --claims <claims.json> --agents-dir <agents> --require-agent-manifest [--evidence <evidence.json>]
```

| 脚本/算子 | 用途 | 关键输入 |
|---|---|---|
| `da_profile.py` | 识别 sheet、表头、字段、类型、缺失和时间覆盖 | 文件路径 |
| `da_quality.py` | 检查合同字段缺失、日期重复、空值、极端值和异常延迟 | profile、原始文件、语义合同 |
| `anomaly_scan` | 计算同星期/滚动基线、偏离和 robust z | 日期、指标、`baseline_window_days` |
| `funnel_rates` | 由阶段计数重算阶段率、损失量 | 阶段字段顺序 |
| `ratio_decomp` | 将比率变化拆为组内与结构变化 | 分子、分母、维度、基线 |
| `contribution` | 将总量缺口按组对账 | 组、当前值、基线值 |
| `ab_effect` | 效应、标准误、置信区间和基本显著性 | 分流、指标、`confidence_level` |
| `segment_profile` | 分层规模、价值和覆盖 | 分层字段、指标 |

分母为 0、样本不足、日期不齐或基线不可用时返回结构化错误，不返回伪造数字。

## 发布前真实性检查（推荐必跑）

```bash
python scripts/da_verify.py --claims <claims.json> --agents-dir <agents> --require-agent-manifest [--evidence <evidence.json>] [--strict]
```

`da_verify.py` 检查每条结论是否有 `evidence_ids`、因果措辞是否越过 L2 门槛、statement 数字能否在证据中找到相近值，以及独立角色工件和执行 manifest 是否有效。它不生成报告、不做分析、不规定视觉格式。
