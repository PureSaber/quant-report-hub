"""Source-bound, point-in-time order-arrival quotes for cash price attribution."""

from __future__ import annotations

import hashlib
import io
import json
import re
from pathlib import Path

import pandas as pd

from quant_report_hub.attribution import _decimal_from_fixed, _parse_utc
from quant_report_hub.cash_attribution import _check

REFERENCE_SCHEMA = "quant-report-hub.execution-references/v1"
QUOTE_COLUMNS = (
    "quote_id",
    "instrument_id",
    "currency",
    "observed_at",
    "available_at",
    "bid_price_units",
    "bid_price_scale",
    "ask_price_units",
    "ask_price_scale",
    "multiplier_units",
    "multiplier_scale",
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        _check(key not in result, f"JSON字段重复: {key}")
        result[key] = value
    return result


def _fields(value, expected, name):
    _check(isinstance(value, dict) and set(value) == set(expected), f"{name}字段不完整或未知")


def _text(value, name):
    _check(isinstance(value, str) and bool(value.strip()), f"{name}必须为非空文本")


def _quote_fixed(row, field):
    values = [row[field + suffix] for suffix in ("_units", "_scale")]
    _check(all(re.fullmatch(r"-?(0|[1-9][0-9]*)", v) for v in values), f"{field}必须为整数定点数")
    units, scale = (int(v) for v in values)
    _check(-(2**63) <= units < 2**63, f"{field}的units超出有符号64位整数")
    return _decimal_from_fixed(units, scale, field)


def fingerprint(paths):
    """Detect content, directory membership and metadata changes across a read."""
    result = {}
    for path in paths:
        _check(path.is_file() and not path.is_symlink(), f"来源必须为普通文件: {path.name}")
        before = path.stat()
        value = digest(path.read_bytes())
        after = path.stat()
        _check(
            (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
            f"读取期间来源变化: {path.name}",
        )
        result[path] = (value, after.st_size, after.st_mtime_ns)
    return result


def load_references(path: Path, expected_sha256: str, run_hash: str):
    """Read exactly the bytes whose external digest and quote digest are checked."""
    quote_path = path.parent / "quotes.csv"
    identity = fingerprint([path, quote_path])
    raw = path.read_bytes()
    _check(digest(raw) == expected_sha256 == identity[path][0], "参考价清单SHA-256不一致")
    metadata = json.loads(raw, object_pairs_hook=_object)
    _fields(
        metadata,
        ("schema_version", "source_run_manifest_sha256", "source", "policy", "quotes"),
        "参考价清单",
    )
    _check(metadata["schema_version"] == REFERENCE_SCHEMA, "参考价schema不受支持")
    _check(metadata["source_run_manifest_sha256"] == run_hash, "参考价绑定了其他原生运行")
    source = metadata["source"]
    _fields(source, ("evidence_kind", "provider", "dataset_id", "description"), "报价来源")
    _check(
        source["evidence_kind"] in ("synthetic", "model", "independently_observed"),
        "报价证据性质未知",
    )
    for field in ("provider", "dataset_id", "description"):
        _text(source[field], field)
    policy = metadata["policy"]
    _fields(policy, ("clock", "price", "price_basis", "max_quote_age_ms"), "参考价口径")
    _check(policy["clock"] == "first_order_acceptance", "参考时钟必须为订单首次接受")
    _check(policy["price"] == "last_available_midquote", "参考价格必须为最新可得报价中点")
    _check(policy["price_basis"] == "unadjusted_trade_currency", "报价必须为成交币种未复权价格")
    age = policy["max_quote_age_ms"]
    _check(type(age) is int and 0 <= age <= 86_400_000, "报价最大年龄须为0至86400000毫秒整数")
    _fields(metadata["quotes"], ("path", "sha256"), "报价文件")
    _check(metadata["quotes"]["path"] == "quotes.csv", "报价文件必须为同目录quotes.csv")
    raw_quotes = quote_path.read_bytes()
    _check(
        digest(raw_quotes) == metadata["quotes"]["sha256"] == identity[quote_path][0],
        "报价文件SHA-256不一致",
    )
    frame = pd.read_csv(io.BytesIO(raw_quotes), dtype=str, keep_default_na=False)
    _check(tuple(frame.columns) == QUOTE_COLUMNS, "报价CSV字段或顺序不符合契约")
    quotes, ids, clocks = [], set(), set()
    for row in frame.to_dict("records"):
        for field in ("quote_id", "instrument_id", "currency"):
            _text(row[field], field)
        _check(row["quote_id"] not in ids, "quote_id重复")
        ids.add(row["quote_id"])
        for field in ("observed_at", "available_at"):
            row[field] = _parse_utc(row[field], field)
        _check(row["observed_at"] <= row["available_at"], "报价available_at早于observed_at")
        clock = (row["instrument_id"], row["currency"], row["available_at"])
        _check(clock not in clocks, "同证券、币种和可得时点有歧义报价")
        clocks.add(clock)
        bid, ask, multiplier = (
            _quote_fixed(row, f) for f in ("bid_price", "ask_price", "multiplier")
        )
        _check(0 < bid <= ask and multiplier == 1, "报价须为正、买价不高于卖价且单位乘数为1")
        row.update(bid=bid, ask=ask, midpoint=(bid + ask) / 2)
        quotes.append(row)
    _check(fingerprint(identity) == identity, "读取期间参考价来源变化")
    return metadata, sorted(quotes, key=lambda q: q["available_at"]), identity


def select_quote(quotes, instrument, currency, accepted_at, max_age_ms):
    eligible = [
        quote
        for quote in quotes
        if quote["instrument_id"] == instrument
        and quote["currency"] == currency
        and quote["available_at"] <= accepted_at
    ]
    _check(bool(eligible), f"订单接受时缺少已可得报价: {instrument}")
    quote = eligible[-1]
    _check(
        accepted_at - quote["observed_at"] <= pd.Timedelta(milliseconds=max_age_ms),
        "参考报价已过期",
    )
    return quote
