from __future__ import annotations

import hashlib
import csv
import io
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROLE_PATTERNS = {
    "date": ["日期", "时间", "date", "datetime", "timestamp", "day"],
    "visitors": ["访问用户", "访客", "访问量", "uv", "visitor", "visit"],
    "registered": ["注册用户", "注册数", "register", "signup"],
    "browse": ["浏览用户", "商品浏览", "浏览数", "browse", "view"],
    "cart": ["加购用户", "加购数", "购物车", "cart"],
    "pay_start": ["发起支付用户", "发起支付人数", "支付发起用户", "pay_start_count", "checkout_count"],
    "pay_success": ["支付成功用户", "支付成功人数", "付款成功用户", "pay_success_count", "paid_count"],
    "pay_fail": ["支付失败用户", "支付失败人数", "付款失败", "pay_fail", "failed"],
    "success_rate": ["支付成功率", "付款成功率", "success_rate", "payment_success_rate"],
    "register_rate": ["注册转化率", "注册率", "register_rate", "signup_rate"],
    "browse_rate": ["浏览转化率", "browse_rate", "view_rate"],
    "cart_rate": ["加购转化率", "加购率", "cart_rate"],
    "pay_start_rate": ["发起支付率", "支付发起率", "pay_start_rate", "checkout_rate"],
    "gateway_availability": ["支付网关可用率", "网关可用率", "gateway", "availability"],
    "inventory_availability": ["库存可售率", "库存可用率", "inventory"],
    "peak_index": ["订单峰值指数", "峰值指数", "peak_index", "peak"],
    "delay_minutes": ["数据延迟", "链路延迟", "延迟分钟", "delay", "latency"],
    "missing_rate": ["字段缺失率", "缺失率", "missing_rate", "null_rate"],
    "missing_count": ["字段缺失数", "缺失数", "missing_count", "null_count"],
    "risk_block_rate": ["风控拦截率", "拦截率", "risk_block", "block_rate"],
    "route": ["支付路由", "路由", "route"],
    "activity": ["活动", "版本", "策略", "活动/版本", "campaign", "version", "strategy"],
    "channel": ["渠道", "channel", "来源", "source", "投放渠道"],
    "device": ["设备", "device", "终端"],
    "region": ["地区", "区域", "region", "城市", "city"],
    "user_id": ["用户id", "用户 ID", "userid", "user_id", "uid"],
    "variant": ["实验组", "对照组", "分组", "variant", "treatment", "control"],
}


def json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return str(value)


def write_json(path: str | Path, payload: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=json_default),
        encoding="utf-8",
    )


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_column_name(name: Any, position: int) -> str:
    if name is None or (isinstance(name, float) and math.isnan(name)):
        return f"unnamed_{position + 1}"
    text = str(name).replace("\n", " ").replace("\r", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text or f"unnamed_{position + 1}"


def unique_columns(columns: list[Any]) -> list[str]:
    seen: dict[str, int] = {}
    output = []
    for position, raw in enumerate(columns):
        name = clean_column_name(raw, position)
        count = seen.get(name, 0) + 1
        seen[name] = count
        output.append(name if count == 1 else f"{name}__{count}")
    return output


def _header_score(row: pd.Series) -> float:
    values = [str(v).strip() for v in row.tolist() if pd.notna(v) and str(v).strip()]
    if len(values) < 2:
        return -1000
    unique = len(set(values))
    non_numeric = sum(not bool(re.fullmatch(r"[-+]?\d+(\.\d+)?", v)) for v in values)
    return len(values) * 2 + unique * 2 + non_numeric * 0.5


def detect_header(raw: pd.DataFrame, scan_rows: int = 15) -> int:
    limit = min(scan_rows, len(raw))
    scores = [(idx, _header_score(raw.iloc[idx])) for idx in range(limit)]
    scores.sort(key=lambda item: item[1], reverse=True)
    return scores[0][0] if scores and scores[0][1] > 0 else 0


def _read_csv(path: Path) -> dict[str, pd.DataFrame]:
    encodings = ["utf-8-sig", "utf-8", "gb18030", "gbk"]
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            text = path.read_text(encoding=encoding)
            sample = text[:10000]
            if path.suffix.lower() == ".tsv":
                delimiter = "\t"
            else:
                try:
                    delimiter = csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
                except csv.Error:
                    delimiter = ","
            rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))[:20]
            raw = pd.DataFrame(rows)
            header = detect_header(raw)
            frame = pd.read_csv(path, header=header, encoding=encoding, sep=delimiter, engine="python")
            frame.columns = unique_columns(frame.columns.tolist())
            return {path.stem: frame.dropna(how="all")}
        except Exception as error:
            last_error = error
    raise ValueError(f"无法读取 CSV：{path}；最后错误：{last_error}")


def load_tables(path: str | Path) -> dict[str, dict[str, Any]]:
    source = Path(path)
    if source.suffix.lower() in {".csv", ".tsv"}:
        tables = _read_csv(source)
        return {name: {"frame": frame, "header_row": 0, "source": name} for name, frame in tables.items()}
    if source.suffix.lower() not in {".xlsx", ".xls", ".xlsm"}:
        raise ValueError("仅支持 Excel、CSV 或 TSV 文件")
    raw_book = pd.ExcelFile(source)
    output: dict[str, dict[str, Any]] = {}
    for sheet in raw_book.sheet_names:
        raw = pd.read_excel(source, sheet_name=sheet, header=None, nrows=20)
        header = detect_header(raw)
        frame = pd.read_excel(source, sheet_name=sheet, header=header)
        frame.columns = unique_columns(frame.columns.tolist())
        frame = frame.dropna(how="all").reset_index(drop=True)
        output[sheet] = {"frame": frame, "header_row": int(header), "source": sheet}
    return output


def role_matches(column: str, role: str) -> bool:
    text = str(column).lower().replace(" ", "")
    if role in {"visitors", "registered", "browse", "cart", "pay_start", "pay_success", "pay_fail"} and "率" in text:
        return False
    patterns = ROLE_PATTERNS.get(role, [])
    return any(pattern.lower().replace(" ", "") in text for pattern in patterns)


def infer_roles(columns: list[str]) -> dict[str, list[str]]:
    return {role: [column for column in columns if role_matches(column, role)] for role in ROLE_PATTERNS}


def parse_date_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")
    return pd.to_datetime(series, errors="coerce", format="mixed")


def is_numeric_series(series: pd.Series) -> bool:
    if pd.api.types.is_numeric_dtype(series):
        return True
    converted = pd.to_numeric(series, errors="coerce")
    return converted.notna().mean() >= 0.8 and converted.notna().sum() >= 2


def to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def robust_stats(values: pd.Series) -> dict[str, float | None]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return {"median": None, "mad": None, "mean": None, "std": None, "n": 0}
    median = float(numeric.median())
    mad = float((numeric - median).abs().median())
    return {
        "median": median,
        "mad": mad,
        "mean": float(numeric.mean()),
        "std": float(numeric.std(ddof=1)) if len(numeric) > 1 else 0.0,
        "n": int(len(numeric)),
    }


def metric_field(table: dict[str, Any], role: str, contract: dict[str, Any] | None = None) -> str | None:
    contract = contract or {}
    fields = contract.get("fields", {}) if isinstance(contract, dict) else {}
    explicit = fields.get(role) if isinstance(fields, dict) else None
    if explicit and explicit in table["frame"].columns:
        return explicit
    roles = infer_roles([str(c) for c in table["frame"].columns])
    candidates = roles.get(role, [])
    if candidates:
        return candidates[0]
    return None


def choose_date_field(frame: pd.DataFrame) -> str | None:
    for column in frame.columns:
        if role_matches(str(column), "date"):
            parsed = parse_date_series(frame[column])
            if parsed.notna().mean() >= 0.5:
                return str(column)
    best = None
    best_rate = 0.0
    for column in frame.columns:
        parsed = parse_date_series(frame[column])
        rate = float(parsed.notna().mean())
        if rate > best_rate and rate >= 0.8:
            best, best_rate = str(column), rate
    return best


def choose_main_table(tables: dict[str, dict[str, Any]]) -> str:
    scored = []
    for name, table in tables.items():
        frame = table["frame"]
        date_field = choose_date_field(frame)
        numeric_count = sum(is_numeric_series(frame[column]) for column in frame.columns)
        date_score = 5 if date_field else 0
        unique_ratio = 0.0
        if date_field and len(frame):
            dates = parse_date_series(frame[date_field]).dt.normalize()
            unique_ratio = float(dates.nunique(dropna=True) / max(dates.notna().sum(), 1))
        daily_bonus = 8 if date_field and unique_ratio >= 0.8 and len(frame) >= 14 else 0
        detail_penalty = -4 if date_field and unique_ratio < 0.5 and len(frame) > 100 else 0
        scored.append((date_score + daily_bonus + detail_penalty + numeric_count + min(len(frame), 100) / 10000, name))
    if not scored:
        raise ValueError("文件没有可读取的表")
    return sorted(scored, reverse=True)[0][1]


def source_ref(sheet: str, header_row: int, row_number: int | None = None) -> dict[str, Any]:
    result = {"sheet": sheet, "header_row": int(header_row) + 1}
    if row_number is not None:
        result["data_row"] = int(row_number) + int(header_row) + 2
    return result
