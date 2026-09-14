# 示例报告

这组文件演示**新流程**：模型写规格 JSON，`scripts/da_report.py` 渲染 HTML。

- `report_spec.example.json`：报告规格。要了解结构、字段和多样性写法，**读这个文件**，它是唯一的可读示例。
- `report_example.html`：上面那份规格的渲染结果，用于展示交付形态。**不要读它**——它是脚本产物，读它既拿不到规格写法，还会白白消耗约 8,000 token（实测 7,810，`o200k_base`）。

想生成自己的示例：

```bash
python scripts/da_report.py --spec examples/report_spec.example.json --out /tmp/example.html
python scripts/da_report.py --emit-example /tmp/minimal_spec.json
```

示例里的数据是合成数据，只用于演示结构，不代表任何真实业务结论。示例不参与 skill 运行时。
