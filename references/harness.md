# 多方向分析 Harness

多 agent 是可选的运行时编排，不是默认步骤，也不是让多个模型投票。主模型先锁定语义合同、质量门禁和分析计划，再将只读证据包分发给独立角色。

## 启动门槛

满足至少一项才并行：问题涉及两个以上方法、异动日期超过 3 个、维度超过 2 层、或需要独立反证。简单单表描述性统计不启动。

## 角色提示词

所有角色都收到：用户问题、`02_contract.json`、`03_quality.json`、`04_plan.json`、`04_analysis.json`、相关方法文件。角色不得读取未授权原始文件，不得修改工件，不得自行重新定义指标。

### Locator

只回答“哪里发生了什么变化”。检查时间序列、基线、分组规模、绝对缺口和正负抵消，禁止写机制原因。输出事实、比较和证据 ID。

### Mechanism

只回答“哪些可观测变量与异动同步，哪些解释被数据排除”。检查漏斗阶段、平台/环境、策略字段、渠道结构和时间顺序。每个机制标为 `supported_candidate`、`alternative` 或 `not_testable`。

### Falsifier

主动寻找反例：样本太小、分母变化、相反维度、数据延迟、字段缺失、口径切换、同样变化但无处理的日期。若找不到反例，仍输出“未发现可验证反例”，不升级为因果。

### Reviewer

逐条审查结论：数字是否能在证据中找到、比较基线是否一致、是否把同步写成导致、是否遗漏排除区、建议是否有对象和验收指标。只输出 `pass`、`downgrade` 或 `block` 及理由。

## 统一输出

```json
{
  "agent": "locator|mechanism|falsifier|reviewer",
  "status": "ok|degraded|blocked",
  "findings": [
    {
      "statement": "只包含一件事的事实或判断",
      "level": "L0|L1|L2|L3",
      "evidence_ids": ["E001"],
      "limitations": ["尚无处理组"],
      "confidence": "high|medium|low"
    }
  ],
  "conflicts": [],
  "missing_data": []
}
```

## 合并规则

1. 先合并同一 `evidence_id` 的事实，再合并解释；
2. 任何角色发现质量风险，都回写排除区并阻止相关结论升级；
3. 解释冲突时保留多个候选，按证据覆盖和可证伪性排序，不按 agent 票数选真相；
4. `Reviewer` 的 `downgrade` 必须被接受，除非主模型能提供新的证据 ID；
5. 只允许主模型生成 `06_claims.json` 和报告文本。

