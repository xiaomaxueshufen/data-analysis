# HTML 报告视觉与动效指南（离线自包含）

本文件是给模型的报告设计提示词。它提供排版系统、图表纪律和**纯 SVG/CSS/原生 JS 的动效模式库**，不依赖 ECharts、Tailwind 或任何 CDN。所有动效必须服务于理解——进场、强调、引导阅读顺序；不做装饰性动画。**内容骨架必须保持 `report-html.md` 的原版六段式**，本文件只负责视觉与图表。

## 底线

1. **离线自包含**：单个 HTML 文件，零外部请求，断网可打开。
2. **动效可选**：`prefers-reduced-motion` 命中时关闭全部动效；无 JS 时图表静态完整可见。
3. **叙事优先**：图表达一个明确问题，图下必须有一句“解读”；没有解读的图删掉。
4. **数字可读**：所有指标数字用 `font-variant-numeric: tabular-nums`，对齐易比较。
5. **结构固定**：视觉模块只能嵌入六段式内部，不得新增顶层章节或改变顺序。

## 排版系统

下面的样式值是可用基线，不是唯一视觉主题；可以在满足对比度和可访问性的前提下替换色板、间距和强调方式。

```css
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
               "Hiragino Sans GB", "Microsoft YaHei", Arial, sans-serif;
  font-size: 16px; line-height: 1.75; color: #1f2428;
  background: #eef6fb;
}
.page { max-width: 1080px; margin: 34px auto; background: #ffffff;
        border-top: 6px solid #4b9dcc; padding: 48px 56px;
        box-shadow: 0 24px 60px -30px rgba(31,42,54,.24); }
.narrative { max-width: 68ch; }
td.num, .metric-value { font-variant-numeric: tabular-nums; text-align: right; }
```

层级约定：章节头 = 强调色方块 + 序号 + 标题；桌面端可加旁置粘性目录；每张图 = 标题 + 回答的问题 + 编号 + “解读”行。

## 图表纪律（画图前先过这张表）

| 数据本身 | 交付形式 | 不要做成 |
|---|---|---|
| 一个头条数字 | 磁贴（label / 动效数值 / note） | 一根柱子的柱状图 |
| 几个头条数字 | 磁贴行 | 三个孤零零数值的分组柱 |
| 一个比率对照目标 | 一句话 + 两个加粗数字 | 两片的饼图 |
| 超过 7 个有意义的类目 | 排序表格，可选 TOP 几名配图 | 8 色循环的图 |

选型按问题来：随时间变化→折线；类目对比→排序条形；构成≤6 类→环形/堆叠；关系→散点；分布→直方图；转化→漏斗；集中异常→热力。

**主角高亮模式**：叙事只讲一条系列时，主角用强调色，其余系列统一压灰 `#b8b8b8`；只给主角做末点标注。颜色跟实体走——同一实体在报告所有图里保持同一颜色。

**反模式**：双 Y 轴（唯一豁免：帕累托的 0–100% 累计轴）；数值大小用彩虹渐变（改单一色相浅→深）；有序类目用分类色板（改单色渐变）；中性系列穿语义红/绿；数值相近还用饼图。

## 动效模式库（可直接复制的最小实现）

所有模式共用一个开关：进入视口时给容器加 `.on`，由 IntersectionObserver 触发；`prefers-reduced-motion` 时直接加 `.on` 且禁用 transition。

```js
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
const io = new IntersectionObserver(es => es.forEach(e => {
  if (e.isIntersecting) { e.target.classList.add('on'); io.unobserve(e.target); }
}), { rootMargin: '0px 0px -8% 0px' });
document.querySelectorAll('.anim').forEach(el => {
  reduce ? el.classList.add('on') : io.observe(el);
});
```

### 1. 折线 draw-in（基线对比图首选）

```html
<svg viewBox="0 0 640 220" class="anim chart">
  <path class="line" d="M20 120 L100 96 L180 108 L260 70 L340 84 L420 50 L500 66 L580 30"/>
  <line class="baseline" x1="20" y1="88" x2="580" y2="88"/>
  <circle class="anomaly" cx="420" cy="50" r="5"/>
</svg>
```

```css
.chart .line { fill: none; stroke: #4b9dcc; stroke-width: 3;
  stroke-dasharray: 1200; stroke-dashoffset: 1200;
  transition: stroke-dashoffset 1.1s cubic-bezier(.3,.7,.2,1) .15s; }
.chart .baseline { stroke: #df6b72; stroke-dasharray: 6 5; stroke-width: 2; }
.chart .anomaly { fill: #df6b72; opacity: 0; transition: opacity .3s 1.2s; }
.chart.on .line { stroke-dashoffset: 0; }
.chart.on .anomaly { opacity: 1; animation: pulse 1.8s ease-out infinite 1.4s; }
@keyframes pulse { 0%,100% { r: 5; } 50% { r: 7; } }
```

要点：`stroke-dasharray` 设为路径总长（估大一点即可）；基线用虚线红；异常点等主线画完再浮现并脉冲。**不要**让数据点逐帧重算位置——动画只做视觉进场，数字必须预先算好写死在标记里。

### 2. 条形 grow-up（类目对比首选）

```html
<div class="anim bars">
  <div class="bar" style="--h:.92"><span>信息流</span><i>3,214</i></div>
  <div class="bar" style="--h:.75; --d:.06s"><span>自然量</span><i>2,630</i></div>
  <div class="bar" style="--h:.51; --d:.12s"><span>应用商店</span><i>1,790</i></div>
</div>
```

```css
.bars { display: grid; gap: 12px; }
.bar { height: 34px; position: relative; }
.bar::before { content: ""; position: absolute; inset: 0; width: calc(var(--h) * 100%);
  background: #4b9dcc; transform: scaleX(0); transform-origin: left;
  transition: transform .8s cubic-bezier(.2,.7,.2,1) var(--d); }
.bars.on .bar::before { transform: scaleX(1); }
.bar span, .bar i { position: relative; z-index: 1; font-style: normal; }
```

要点：条形按数值降序；用 `scaleX` 从左生长；`--d` 做逐条错峰（stagger，间隔 ≤80ms）。主角条用强调色，其余压灰。

### 3. 数字 count-up（磁贴）

```html
<div class="anim tile"><b class="count" data-to="35.8" data-dec="1">0.0</b><span>%</span>
  <small>加购→支付转化率</small></div>
```

```js
document.querySelectorAll('.anim .count').forEach(el => {
  if (reduce) { el.textContent = (+el.dataset.to).toFixed(+el.dataset.dec || 0); return; }
  const to = +el.dataset.to, dec = +el.dataset.dec || 0, t0 = performance.now(), dur = 900;
  const step = t => { const p = Math.min(1, (t - t0) / dur);
    el.textContent = (to * (1 - Math.pow(1 - p, 3))).toFixed(dec);
    if (p < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
});
```

要点：`data-to` 里的最终值必须是脚本预先算好的结果；动画只改变显示过程，不参与计算。负数/货币同理，前缀写在标签外。

### 4. 环形 sweep（占比 ≤6 类）

```css
.donut circle { fill: none; stroke-width: 22; stroke-dasharray: 0 999; transition: stroke-dasharray .9s ease .1s; }
.donut.on circle { stroke-dasharray: var(--len) 999; }
```

每段 `<circle>` 用 `stroke-dasharray: 弧长 周长` 与 `stroke-dashoffset` 定位；有序类目用同一色相浅→深。

### 5. 滚动显现（章节/卡片）

```css
.reveal { opacity: 0; transform: translateY(10px);
  transition: opacity .55s ease, transform .55s cubic-bezier(.2,.7,.2,1); }
.reveal.on { opacity: 1; transform: none; }
@media (prefers-reduced-motion: reduce) { .reveal { opacity: 1; transform: none; transition: none; } }
```

同一屏内多个元素用 `transition-delay` 错峰 60–80ms；首屏元素不加 reveal，避免打开空白。

### 6. 目录 scroll-spy（桌面端）

```js
const links = [...document.querySelectorAll('.toc a')];
const spy = new IntersectionObserver(es => es.forEach(e => {
  if (e.isIntersecting) links.forEach(a =>
    a.classList.toggle('active', a.hash === '#' + e.target.id));
}), { rootMargin: '-15% 0px -60% 0px' });
document.querySelectorAll('section[id]').forEach(s => spy.observe(s));
```

## 检查清单

- [ ] 断网打开正常，DevTools Network 零请求；
- [ ] `prefers-reduced-motion` 下无任何位移动画；
- [ ] 禁用 JS 后正文、表格、图表静态可见；
- [ ] 每张图有一句“解读”，且只回答一个明确问题；
- [ ] 同一实体跨图颜色一致；语义红绿只用于涨跌/好坏；
- [ ] 打印时隐藏目录与动效，图表完整落在分页内。
