from __future__ import annotations

import hashlib
import contextlib
import csv
import io
import json
import math
import re
import sys
import warnings
from pathlib import Path
from typing import Any, Callable

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


class DataError(ValueError):
    """输入数据本身的问题：文件不存在、类型不支持、表读不出来、配置缺字段。

    继承 ValueError，这样既有调用方按 ValueError 兜底也不会被破坏；
    同时让 CLI 能把它和真正的程序缺陷（IndexError / KeyError / TypeError）
    区分开——后者应该继续抛栈，不能被伪装成「用户输入有问题」。
    """


SUPPORTED_SUFFIXES = {".csv", ".tsv", ".xlsx", ".xlsm"}


def ensure_readable(path: str | Path) -> Path:
    """把「这个路径能不能当数据读」的检查集中到一处，错误信息统一。"""
    source = Path(path)
    if not source.exists():
        raise DataError(f"文件不存在：{source}")
    if source.is_dir():
        raise DataError(f"这是一个目录，不是数据文件：{source}")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise DataError(f"不支持的文件类型：{suffix or '（无扩展名）'}；只支持 .xlsx / .xlsm / .csv / .tsv")
    if source.stat().st_size == 0:
        raise DataError(f"文件是空的：{source}")
    return source


@contextlib.contextmanager
def quiet_numeric():
    """屏蔽 numpy/pandas 在极端数值上的 RuntimeWarning（溢出、无效值转换等）。

    这些告警不是可执行的修复建议：数值会变成 inf/NaN，交给 write_json 转成 null。
    保留我们自己的 RuntimeWarning，只压第三方数值库的噪声。
    """
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, module=r"(numpy|pandas)")
        with np.errstate(all="ignore"):
            yield


def cli_guard(work: Callable[[], int]) -> int:
    """把可预期的输入错误转成结构化输出 + 退出码 2，不把 traceback 甩给用户。

    只兜输入/环境类问题；IndexError、KeyError、TypeError 这类程序缺陷继续抛栈，
    否则真正的 bug 会被伪装成「用户输入错」而长期潜伏。
    """
    with quiet_numeric():
        try:
            return work()
        except DataError as exc:
            print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 2
        except json.JSONDecodeError as exc:
            print(json.dumps({"status": "fail", "error": f"JSON 解析失败：{exc}"}, ensure_ascii=False), file=sys.stderr)
            return 2
        except OSError as exc:
            print(json.dumps({"status": "fail", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
            return 2


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


def sanitize_json(value: Any) -> Any:
    """把 inf / -inf / NaN 递归换成 null。

    json.dumps 默认会写 `Infinity` / `NaN`，那不是合法 JSON：JS 的 JSON.parse、
    jq、Go 等严格解析器都会拒绝，整条下游流水线会因此断掉。
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): sanitize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_json(item) for item in value]
    if isinstance(value, np.ndarray):
        return [sanitize_json(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        scalar = value.item()
        if isinstance(scalar, float) and not math.isfinite(scalar):
            return None
        return scalar
    return value


def write_json(path: str | Path, payload: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        # allow_nan=False 是兜底：万一还有非有限值漏过 sanitize_json，
        # 这里会立刻炸出来，而不是悄悄写出非法 JSON。
        json.dumps(sanitize_json(payload), ensure_ascii=False, indent=2, default=json_default, allow_nan=False),
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


def _header_cells(row: pd.Series) -> list[str]:
    return [str(v).strip() for v in row.tolist() if pd.notna(v) and str(v).strip()]


def _header_score(row: pd.Series) -> float:
    values = _header_cells(row)
    if len(values) < 2:
        return -1000
    unique = len(set(values))
    non_numeric = sum(not bool(re.fullmatch(r"[-+]?\d+(\.\d+)?", v)) for v in values)
    return len(values) * 2 + unique * 2 + non_numeric * 0.5


def _looks_like_header(row: pd.Series) -> bool:
    """真表头不会有一半以上是纯数值。

    参差行里，多出一格的数据行会凭「格子更多」在打分上压过真表头，
    结果整列错位。这里用「多数单元格是文字」把这类数据行排掉。
    """
    values = _header_cells(row)
    if len(values) < 2:
        return False
    text_like = sum(not bool(re.fullmatch(r"[-+]?\d+(\.\d+)?", v)) for v in values)
    return text_like * 2 > len(values)


def detect_header(raw: pd.DataFrame, scan_rows: int = 15) -> int:
    limit = min(scan_rows, len(raw))
    scored = [(idx, _header_score(raw.iloc[idx])) for idx in range(limit)]
    shaped = [item for item in scored if _looks_like_header(raw.iloc[item[0]])]
    pool = shaped or scored
    # 同分时取更靠上的行，避免把数据行当表头
    pool.sort(key=lambda item: (-item[1], item[0]))
    return pool[0][0] if pool and pool[0][1] > 0 else 0


def _read_csv(path: Path) -> tuple[dict[str, pd.DataFrame], list[str]]:
    encodings = ["utf-8-sig", "utf-8", "gb18030", "gbk"]
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            text = path.read_text(encoding=encoding)
            if not text.strip():
                raise DataError(f"文件里没有任何内容：{path}")
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
            # 参差行（某行格子比表头多）会让 pandas 把多出来的第一格当索引，
            # 整列错位。index_col=False 固定列映射，代价是被丢弃的多余格子只发
            # ParserWarning——这里记录下来，交给画像/质量门禁去提示，不静默吞掉。
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", pd.errors.ParserWarning)
                frame = pd.read_csv(
                    path, header=header, encoding=encoding, sep=delimiter,
                    engine="python", index_col=False,
                )
            notices = [
                str(item.message) for item in caught
                if issubclass(item.category, pd.errors.ParserWarning)
            ]
            frame.columns = unique_columns(frame.columns.tolist())
            return {path.stem: frame.dropna(how="all")}, notices
        except DataError:
            raise
        except Exception as error:
            last_error = error
    raise DataError(f"无法读取 CSV：{path}；最后错误：{type(last_error).__name__}: {last_error}")


def load_tables(path: str | Path) -> dict[str, dict[str, Any]]:
    source = ensure_readable(path)
    if source.suffix.lower() in {".csv", ".tsv"}:
        tables, parse_notices = _read_csv(source)
        output = {
            name: {"frame": frame, "header_row": 0, "source": name, "parse_notices": parse_notices}
            for name, frame in tables.items()
        }
        if not output or all(table["frame"].shape[1] == 0 for table in output.values()):
            raise DataError(f"没能从文件里解析出任何列：{source}")
        return output
    try:
        raw_book = pd.ExcelFile(source)
    except DataError:
        raise
    except Exception as error:
        raise DataError(f"无法打开 Excel：{source}；{type(error).__name__}: {error}") from error
    output: dict[str, dict[str, Any]] = {}
    for sheet in raw_book.sheet_names:
        raw = pd.read_excel(source, sheet_name=sheet, header=None, nrows=20)
        header = detect_header(raw)
        frame = pd.read_excel(source, sheet_name=sheet, header=header)
        frame.columns = unique_columns(frame.columns.tolist())
        frame = frame.dropna(how="all").reset_index(drop=True)
        output[sheet] = {"frame": frame, "header_row": int(header), "source": sheet, "parse_notices": []}
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
    with quiet_numeric():
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
    with quiet_numeric():
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
    if explicit is not None:
        return explicit if explicit in table["frame"].columns else None
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
