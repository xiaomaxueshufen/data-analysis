# 独立角色分析 Harness（强制门禁）

独立角色分析不是可选优化。当问题需要解释“为什么”或结论会达到 L2 及以上时，单一视角容易把同步写成因果、把数据事故写成业务异动。因此正式报告发布前，必须完成独立角色分析并留下每个角色的工件。

## 强制触发条件（命中任意一条即必须启动）

1. 用户问题包含“为什么/原因/下降/上升/异动/变差/变好”；
2. 报告将包含 L2 及以上的解释性结论；
3. 分析计划涉及两个及以上方法方向（如异动 + 漏斗 + 拆解）；
4. 候选异动日期超过 3 个，或维度拆解超过 2 层；
5. 数据存在质量问题（缺失、置零、口径切换）且需要与业务异动区分；
6. 多个文件之间需要交叉对账。

只有纯描述性统计（如“这份数据有多少行、哪些字段”）才允许跳过。

## 必须的角色

| 角色 | 职责 | 是否必须 |
|---|---|---|
| Locator | 只回答“哪里发生了什么变化”，禁止写机制原因 | 必须 |
| Mechanism | 只回答“哪些可观测变量与异动同步，哪些解释被排除” | 必须 |
| Falsifier | 主动找反例：样本太小、分母变化、相反维度、数据事故、口径切换 | 必须 |
| Reviewer | 逐条审查结论的证据引用、基线一致性和因果措辞 | 必须（发布前） |

## 执行方式

### 启动前检查

主模型先判断当前运行环境是否实际暴露 Codex 原生 subagent/agent-thread 工具。判断依据是运行时工具清单中存在可用的原生 agent 派发能力（工具名可能随版本变化，例如 `spawn_agent` / `wait_agent`），而不是模型能否通过 shell 打印 JSON 或启动进程。

注意 provider 差异：在当前本地 Codex 版本中，OpenAI provider 会话可进入
`multi_agent_mode: explicitRequestOnly` 并暴露原生派发工具；自定义 provider
会话可能没有这些工具。若当前会话使用自定义 provider 且工具清单没有原生
agent 派发能力，直接判定为不可用，不要通过更强烈的提示词或额外重试解决。

把失败分成两类：

1. **Provider 能力失败**：模型没有发出原生工具调用，或只返回文本
   `UNSUPPORTED`/类似说明。这表示当前 provider/model 不能使用该工具表面，
   不重试，直接进入串行隔离回退。
2. **运行时调用失败**：确实发出了原生派发/等待工具调用，但
   Codex 返回错误。每个角色最多重试一次；仍失败则按用户要求停止或整体回退。

禁止以下伪 subagent 行为：

1. 用 `printf`、Python、Shell 或一次性脚本打印四个 JSON 后称为四个 agent；
2. 启动四个外部 Codex CLI 进程或普通并发任务来绕过原生 agent 管理；
3. 创建普通用户新线程后把它称为 subagent；
4. 在没有原生工具时声称“已启动四个 subagents”。

### 情况一：运行时提供原生 subagent 派发工具

执行顺序固定为三段：

1. **并行派发前三个角色。** 在同一轮连续调用三次当前运行时暴露的原生派发工具，分别创建
   `locator`、`mechanism`、`falsifier`。三次调用之间不要等待、不要总结、
   不要让后一个 prompt 依赖前一个结果。
2. **等待并落盘。** 三次派发完成后调用对应的原生等待工具等待全部完成；每个角色
   把结果写入 `<run>/agents/<role>.json`，并在最终消息中返回同一 JSON。若文件
   缺失但最终消息包含完整 JSON，主模型只能原样保存，不得改写分析内容。
3. **最后派发 `reviewer`。** 只有前三个工件都存在且可解析后，才把三者一并
   交给 `reviewer` 做发布前审查。Reviewer 不得提前启动。

前三个角色只收到用户问题、语义合同、质量报告、相关方法文件、只读证据包和
自己的输出路径，彼此不读取输出；`reviewer` 依赖前三个工件，必须最后执行。

如果某个 subagent 启动或返回失败，记录角色和错误原因，最多重试一次；再次失败则切换到串行隔离回退。用户明确要求必须使用真实 subagent 时，停止并说明失败原因，不得用回退结果冒充真实 subagent。

### 执行 manifest

无论原生模式还是回退模式，主模型都必须写 `<run>/agents/execution.json`：

```json
{
  "mode": "native_subagents",
  "native_tool_available": true,
  "requested_real_subagents": true,
  "spawn_attempts": [
    {"role": "locator", "agent_id": "…", "status": "ok", "error": null},
    {"role": "mechanism", "agent_id": "…", "status": "ok", "error": null},
    {"role": "falsifier", "agent_id": "…", "status": "ok", "error": null},
    {"role": "reviewer", "agent_id": "…", "status": "ok", "error": null}
  ],
  "fallback_reason": null
}
```

串行回退使用 `"mode": "serial_fallback"`，`spawn_attempts` 可为空，但必须写
`fallback_reason`（例如 `provider_unsupported`、`spawn_runtime_error`）。Manifest
只记录事实，不作为角色分析工件，也不能替代四个角色 JSON。

### 情况二：没有原生 agent 工具（默认回退）

主模型**串行执行**四个角色，但必须遵守隔离规则：

1. 每个角色开始前，只读取该角色允许的输入（见下表），不读取其他角色的输出；
2. 每个角色结束时，立即把自己的结果写入独立工件 `agents/<role>.json`；
3. 四个工件全部写完后，才进入合并阶段；
4. 合并阶段可以读取全部工件，但不得回改任何角色的原始工件——冲突在主模型的 `claims.json` 中解决。

串行不等于敷衍：每个角色必须用自己的视角独立检查数据，而不是把同一段话换四个说法。

串行回退的报告与方法附录必须写明 `mode: serial_fallback`。这满足独立视角工件门禁，但不满足“必须启动真实 subagent”的用户要求；后一种要求只有在原生工具可用时才能执行。

## 角色输入与输出

**原生 subagent 模式**

| 角色 | 允许读取 | 禁止读取 |
|---|---|---|
| Locator | 原始数据、语义合同、质量报告 | 其他三个角色输出 |
| Mechanism | 原始数据、语义合同、质量报告 | Locator/Falsifier/Reviewer 输出 |
| Falsifier | 原始数据、语义合同、质量报告 | Locator/Mechanism/Reviewer 输出 |
| Reviewer | 原始数据、语义合同、质量报告、前三个角色工件 | —（前三个完成后最后执行） |

**串行隔离回退模式**

| 角色 | 允许读取 | 禁止读取 |
|---|---|---|
| Locator | 原始数据、语义合同、质量报告 | Mechanism/Falsifier/Reviewer 输出 |
| Mechanism | 原始数据、语义合同、质量报告、Locator 工件 | Falsifier/Reviewer 输出 |
| Falsifier | 原始数据、语义合同、质量报告、Locator 工件 | Mechanism/Reviewer 输出 |
| Reviewer | 原始数据、语义合同、质量报告、前三个角色工件 | —（发布前最后执行） |

> 注：原生 subagent 模式下，Mechanism 和 Falsifier 不读取 Locator 输出，保证三者真正并行且视角独立；串行回退模式下，它们允许读 Locator 的事实清单，但仍必须独立形成解释与反证。

## 角色提示词

所有角色都收到：用户问题、语义合同、质量报告、相关方法文件。角色不得修改原始数据或其他角色工件，不得自行重新定义指标。

### Locator

只回答“哪里发生了什么变化”。检查时间序列、基线、分组规模、绝对缺口和正负抵消，禁止写机制原因。输出事实、比较和证据 ID。

### Mechanism

只回答“哪些可观测变量与异动同步，哪些解释被数据排除”。检查漏斗阶段、平台/环境、策略字段、渠道结构和时间顺序。每个机制标为 `supported_candidate`、`alternative` 或 `not_testable`。

### Falsifier

主动寻找反例：样本太小、分母变化、相反维度、数据延迟、字段缺失、口径切换、同样变化但无处理的日期。若找不到反例，仍输出“未发现可验证反例”，不升级为因果。

### Reviewer

逐条审查结论：数字是否能在证据中找到、比较基线是否一致、是否把同步写成导致、是否遗漏排除区、建议是否有对象和验收指标。只输出 `pass`、`downgrade` 或 `block` 及理由。

## 统一输出（每个角色一个文件）

运行目录结构：

```text
<run>/
├── agents/
│   ├── locator.json
│   ├── mechanism.json
│   ├── falsifier.json
│   └── reviewer.json
├── claims.json
└── report.html
```

每个工件格式：

```json
{
  "agent": "locator|mechanism|falsifier|reviewer",
  "status": "ok|degraded|blocked",
  "generated_at": "ISO-8601 时间",
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
5. 只允许主模型生成 `claims.json` 和报告文本；
6. 报告的方法附录必须列出四个角色工件的路径，证明独立分析确实发生过。

## 发布前校验

正式报告发布前运行：

```bash
python scripts/da_verify.py --claims <run>/claims.json --agents-dir <run>/agents --require-agent-manifest [--evidence <run>/evidence.json]
```

`--agents-dir` 会检查四个角色工件是否齐全且格式有效；`--require-agent-manifest`
会额外检查 `agents/execution.json`，并确认 `native_subagents` 模式确实记录了四个
角色的 agent id。缺失或与声明模式矛盾即视为未完成独立分析，报告不得发布。
