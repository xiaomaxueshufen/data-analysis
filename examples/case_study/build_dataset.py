#!/usr/bin/env python3
"""把公开的真实交易明细聚合成案例用的日粒度二维表。

数据来源
--------
UCI Machine Learning Repository, *Online Retail II*（真实交易数据，CC BY 4.0）：
https://archive.ics.uci.edu/dataset/502/online+retail+ii
本仓库不附带原始明细（约 90MB / 106.7 万行），只提交聚合后的 `data/retail_daily.csv`。

原始文件是公开数据，但**不是**任何客户的内部数据；它本身已经不含姓名、地址等
直接标识，客户编号是原数据集自带的匿名编号。本脚本进一步只输出日 × 区域粒度，
不输出任何单笔订单或客户粒度信息。

口径（与报告「数据概况」一节一致）
--------------------------------
1. 只保留 `Quantity != 0` 且 `Price > 0` 的行：去掉零价赠品、补录行与退款占位行；
2. 再剔除**非商品/服务类代码**（`NON_PRODUCT_CODES`：邮费、手工调整、坏账、人工折扣等），
   它们是账务调整而不是商品销售，混进来会让金额口径不可比；
3. 再剔除**完全重复行**：发票号、商品码、数量、时间戳、单价、客户编号六列全部一致的行
   视为采集重复（真实的两条相同行会合并成一条并累加数量）。原数据里这类行占 6.3%，
   去重会让总额下降；`--keep-duplicates` 可以关掉这一步做敏感性对比，影响会打印出来；
4. 销售金额 = Σ(Quantity × Price)，Quantity > 0；
5. 退货金额 = |Σ(Quantity × Price)|，Quantity < 0（原数据用负数量表示退货/取消）；
6. 净收入 = 销售金额 − 退货金额；
7. 订单数 = 当日该区域去重 Invoice 数；
8. 活跃客户数 = 当日该区域去重 Customer ID 数（缺失客户 ID 的行不计入）。它是去重计数，
   **不可加总**，因此合计行该列留空——留空会被 da_reconcile 跳过，写成求和值反而会变成假的校验和；
9. 缺客户ID行数 = 当日该区域 Customer ID 为空的行数；
10. 维度 `区域` 只分「英国 / 非英国」：原数据 43 个国家里英国占约 85% 收入，
    再细分会让案例表变得很长而不增加结论价值；
11. 最后一行追加「合计」行，供 `da_reconcile.py` 当作表内校验和。

用法
----
    python examples/case_study/build_dataset.py --raw /path/to/online_retail_II.csv
    python examples/case_study/build_dataset.py --raw <路径> --out examples/case_study/data/retail_daily.csv
    python examples/case_study/build_dataset.py --download      # 从镜像下载原始 CSV

依赖：pandas（`pip install -r requirements.txt`）。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
import urllib.request
from pathlib import Path

import pandas as pd

CASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUT = CASE_DIR / "data" / "retail_daily.csv"
MIRROR = "https://huggingface.co/datasets/attik/Online-Retail-II-UCI/resolve/main/online_retail_II.csv"
# 2026-09-14 实际使用的原始文件校验和；换镜像或换版本时这里会不一致，
# 不一致就应该重新核对口径，而不是静默沿用。
RAW_SHA256 = "32569a66f3842a82b0d8c4d63b263c5d98a76bde5d1f65c6c01bf457e541d3a9"
RAW_ROWS = 1_067_371
DATE_COLUMN = "InvoiceDate"

COLUMNS = ["日期", "区域", "订单数", "销售件数", "销售金额", "退货金额", "净收入", "活跃客户数", "缺客户ID行数"]

# 这些 StockCode 不是商品：邮费、手工调整、坏账、人工折扣、样品、慈善等。
# 集合是显式写死的，不用正则猜，避免把 85123A 这种正常商品码误伤。
NON_PRODUCT_CODES = {
    "M", "D", "POST", "DOT", "C2", "BANK CHARGES", "AMAZONFEE", "CRUK",
    "PADS", "S", "B", "ADJUST", "ADJUST2", "TEST001", "TEST002",
}
# 注意：这里用的是重命名之后的列名（见 aggregate 里的 rename）
DUPLICATE_KEY = ["Invoice", "StockCode", "Quantity", "日期", "Price", "客户ID"]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(destination: Path) -> Path:
    if destination.exists():
        print(f"已存在，跳过下载：{destination}")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"从镜像下载原始明细（约 90MB）：{MIRROR}")
    urllib.request.urlretrieve(MIRROR, destination)
    return destination


def aggregate(raw_path: Path, keep_duplicates: bool = False) -> pd.DataFrame:
    frame = pd.read_csv(raw_path, parse_dates=[DATE_COLUMN])
    if len(frame) != RAW_ROWS:
        print(f"警告：原始文件 {len(frame)} 行，与记录的 {RAW_ROWS} 行不一致，请核对版本", file=sys.stderr)
    frame = frame.rename(columns={DATE_COLUMN: "日期", "Country": "国家", "Customer ID": "客户ID"})
    frame["日期"] = frame["日期"].dt.normalize()

    original = frame
    non_product = frame[frame["StockCode"].astype(str).isin(NON_PRODUCT_CODES)]
    frame = frame[~frame["StockCode"].astype(str).isin(NON_PRODUCT_CODES)]
    print(f"剔除非商品/服务类代码：{len(non_product)} 行，金额影响 {(non_product['Quantity'] * non_product['Price']).sum():,.2f}")

    zero_value = frame[(frame["Quantity"] == 0) | (frame["Price"] <= 0)]
    frame = frame[(frame["Quantity"] != 0) & (frame["Price"] > 0)].copy()
    print(f"剔除零价/零数量行：{len(zero_value)} 行，金额影响 {(zero_value['Quantity'] * zero_value['Price']).sum():,.2f}")

    before_dedupe = len(frame)
    duplicate_rows = frame[frame.duplicated(subset=DUPLICATE_KEY, keep="first")]
    if not keep_duplicates:
        frame = frame.drop_duplicates(subset=DUPLICATE_KEY, keep="first").copy()
    print(
        f"完全重复行：{len(duplicate_rows)} 行（占去重前的 {len(duplicate_rows) / max(before_dedupe, 1):.2%}），"
        f"金额影响 {(duplicate_rows['Quantity'] * duplicate_rows['Price']).sum():,.2f}"
        f"{'（已剔除）' if not keep_duplicates else '（--keep-duplicates，未剔除）'}"
    )
    print(f"清洗后明细行：{len(frame):,} / 原始 {len(original):,}")

    frame["区域"] = frame["国家"].where(frame["国家"] == "United Kingdom", "非英国").map(
        {"United Kingdom": "英国", "非英国": "非英国"}
    )
    frame["金额"] = frame["Quantity"] * frame["Price"]
    frame["客户ID缺失"] = frame["客户ID"].isna()

    rows = []
    for (date, region), group in frame.groupby(["日期", "区域"], sort=True):
        sales = group[group["Quantity"] > 0]
        returns = group[group["Quantity"] < 0]
        rows.append({
            "日期": date.strftime("%Y-%m-%d"),
            "区域": region,
            "订单数": int(group["Invoice"].nunique()),
            "销售件数": int(sales["Quantity"].sum()),
            "销售金额": round(float(sales["金额"].sum()), 2),
            "退货金额": round(abs(float(returns["金额"].sum())), 2),
            "净收入": round(float(sales["金额"].sum()) - abs(float(returns["金额"].sum())), 2),
            "活跃客户数": int(group["客户ID"].nunique()),
            "缺客户ID行数": int(group["客户ID缺失"].sum()),
        })
    table = pd.DataFrame(rows)
    total = {
        "日期": "合计",
        "区域": "全部",
        "订单数": int(table["订单数"].sum()),
        "销售件数": int(table["销售件数"].sum()),
        "销售金额": round(float(table["销售金额"].sum()), 2),
        "退货金额": round(float(table["退货金额"].sum()), 2),
        "净收入": round(float(table["净收入"].sum()), 2),
        # 去重计数不可加总：合计行留空，避免制造一个对不上的校验和
        "活跃客户数": "",
        "缺客户ID行数": int(table["缺客户ID行数"].sum()),
    }
    table = pd.concat([table, pd.DataFrame([total])], ignore_index=True)[COLUMNS]
    print(f"输出 {len(table) - 1} 行明细 + 1 行合计；窗口 {table['日期'].iloc[0]} ~ {table['日期'].iloc[-2]}")
    print(f"净收入合计 {total['净收入']:,.2f}；缺客户 ID 行数 {total['缺客户ID行数']:,} / {len(frame):,} = {total['缺客户ID行数'] / len(frame):.2%}")
    return table


def main() -> int:
    parser = argparse.ArgumentParser(description="聚合 Online Retail II 到日 × 区域粒度")
    parser.add_argument("--raw", help="原始 online_retail_II.csv 路径")
    parser.add_argument("--download", action="store_true", help="从镜像下载原始 CSV 到 --raw 指定的位置")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help=f"输出 CSV（默认 {DEFAULT_OUT}）")
    parser.add_argument("--skip-checksum", action="store_true", help="跳过原始文件 sha256 校验（不推荐）")
    parser.add_argument("--keep-duplicates", action="store_true", help="保留完全重复行（做敏感性对比用）")
    args = parser.parse_args()

    if not args.raw:
        parser.error("必须提供 --raw <online_retail_II.csv 路径>；没有原始文件时先加 --download")
    raw = Path(args.raw).expanduser()
    if args.download and not raw.exists():
        download(raw)
    if not raw.is_file():
        print(f"读不到原始明细：{raw}", file=sys.stderr)
        return 2
    if not args.skip_checksum:
        digest = sha256_of(raw)
        if digest != RAW_SHA256:
            print(f"sha256 不一致：\n  实际 {digest}\n  记录 {RAW_SHA256}", file=sys.stderr)
            print("口径可能已经变化，先确认版本再重跑（确认无误可加 --skip-checksum）", file=sys.stderr)
            return 2

    table = aggregate(raw, keep_duplicates=args.keep_duplicates)
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out, index=False, quoting=csv.QUOTE_MINIMAL, encoding="utf-8")
    print(f"已写出 {out}（{out.stat().st_size:,} 字节）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
