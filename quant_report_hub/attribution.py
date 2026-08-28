"""Performance attribution for standard quant research runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

CONTROLLED_COMPONENTS = frozenset(
    {
        "price",
        "carry",
        "funding",
        "roll",
        "fx",
        "commission",
        "tax",
        "maker_fee",
        "taker_fee",
        "slippage",
        "market_impact",
        "financing",
        "residual",
    }
)
_LEDGER_COST_COMPONENTS = frozenset(
    {
        "commission",
        "tax",
        "maker_fee",
        "taker_fee",
        "slippage",
        "market_impact",
        "financing",
        "funding",
    }
)
_NON_COST_COMPONENTS = CONTROLLED_COMPONENTS - _LEDGER_COST_COMPONENTS
_REPORT_SCALE = 18


class V2AttributionError(ValueError):
    """Raised when a strict v2 accounting or causality invariant is violated."""


@dataclass(frozen=True)
class V2AttributionManifest:
    """Immutable description of one separately-published v2 reconciliation report."""

    schema_version: str
    source_run_manifest_sha256: str
    source_run_id: str
    source_schema_version: str
    base_currency: str
    files: dict[str, str]
    row_counts: dict[str, int]
    reconciliation: dict[str, int]


def _decimal_from_fixed(units: Any, scale: Any, field: str) -> Decimal:
    if isinstance(units, bool) or isinstance(scale, bool):
        raise V2AttributionError(f"{field}的units/scale必须是整数")
    try:
        integer_units = int(units)
        integer_scale = int(scale)
    except (TypeError, ValueError, OverflowError) as exc:
        raise V2AttributionError(f"{field}的units/scale无效") from exc
    if integer_scale < 0 or integer_scale > 18:
        raise V2AttributionError(f"{field}的scale必须在0到18之间")
    return Decimal(integer_units).scaleb(-integer_scale)


def _fixed_from_decimal(value: Decimal, scale: int = _REPORT_SCALE) -> tuple[int, int]:
    if not value.is_finite():
        raise V2AttributionError("归因金额必须是有限Decimal")
    scaled = value.scaleb(scale)
    integral = scaled.to_integral_value()
    if scaled != integral:
        raise V2AttributionError(f"金额{value}不能精确表示为scale={scale}")
    return int(integral), scale


def _parse_utc(value: Any, field: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise V2AttributionError(f"{field}必须包含UTC时区")
    if timestamp.utcoffset().total_seconds() != 0:
        raise V2AttributionError(f"{field}必须为UTC")
    return timestamp.tz_convert("UTC")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_validated_v2(run_dir: str | Path):
    """Load only an intact v2 run; the QLab reader deliberately never downgrades corruption."""
    from quant_lab import load_and_validate_standard_run
    from quant_lab.contracts_v2 import RunManifestV2

    run_path = Path(run_dir)
    manifest = load_and_validate_standard_run(run_path)
    if not isinstance(manifest, RunManifestV2):
        raise V2AttributionError("M5精确归因只接受完整的standard/v2运行产物")
    base = run_path / "standard" / "v2"
    records = {record.name: record for record in manifest.artifacts}
    frames: dict[str, pd.DataFrame] = {}
    for name, record in records.items():
        if record.path.endswith(".parquet"):
            frames[name] = pd.read_parquet(base / record.path)
    return run_path, manifest, frames, _sha256(base / "run_manifest.json")


def _require_frame_columns(frame: pd.DataFrame, name: str, columns: set[str]) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise V2AttributionError(f"{name}缺少字段: {missing}")


def _decimal_sum(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal(0))


def _key_time(value: Any) -> str:
    return _parse_utc(value, "event_time").isoformat()


def _component_record(
    *,
    event_time: Any,
    account_id: str,
    strategy_id: str,
    instrument_id: str,
    component: str,
    currency: str,
    amount: Decimal,
    base_currency: str,
    base_amount: Decimal,
) -> dict[str, Any]:
    if component not in CONTROLLED_COMPONENTS:
        raise V2AttributionError(f"不受支持的归因component: {component}")
    return {
        "event_time": _parse_utc(event_time, "attribution.event_time"),
        "account_id": str(account_id),
        "strategy_id": str(strategy_id),
        "instrument_id": str(instrument_id),
        "component": component,
        "currency": str(currency),
        "amount": amount,
        "base_currency": str(base_currency),
        "base_amount": base_amount,
    }


def _source_components(frame: pd.DataFrame, base_currency: str) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    _require_frame_columns(
        frame,
        "attribution",
        {
            "event_time",
            "account_id",
            "strategy_id",
            "instrument_id",
            "component",
            "amount_units",
            "amount_scale",
            "currency",
            "base_amount_units",
            "base_amount_scale",
            "base_currency",
        },
    )
    records: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False):
        if row.component not in CONTROLLED_COMPONENTS:
            raise V2AttributionError(f"attribution包含未冻结component: {row.component}")
        if row.base_currency != base_currency:
            raise V2AttributionError("attribution.base_currency必须等于运行的base_currency")
        amount = _decimal_from_fixed(row.amount_units, row.amount_scale, "attribution.amount")
        base_amount = _decimal_from_fixed(
            row.base_amount_units, row.base_amount_scale, "attribution.base_amount"
        )
        if row.currency == base_currency and amount != base_amount:
            raise V2AttributionError("基础币种归因的amount与base_amount必须精确相等")
        records.append(
            _component_record(
                event_time=row.event_time,
                account_id=row.account_id,
                strategy_id=row.strategy_id,
                instrument_id=row.instrument_id,
                component=row.component,
                currency=row.currency,
                amount=amount,
                base_currency=row.base_currency,
                base_amount=base_amount,
            )
        )
    return records


def _ledger_cash_by_reference(ledger: pd.DataFrame) -> dict[tuple[str, str, str], Decimal]:
    _require_frame_columns(
        ledger,
        "cash_ledger",
        {
            "reference_id",
            "event_type",
            "ledger_account",
            "currency",
            "amount_units",
            "amount_scale",
        },
    )
    totals: dict[tuple[str, str, str], list[Decimal]] = {}
    for row in ledger.itertuples(index=False):
        if row.event_type not in {"fee", "funding"} or row.ledger_account != "assets:cash":
            continue
        key = (str(row.reference_id), str(row.event_type), str(row.currency))
        totals.setdefault(key, []).append(
            _decimal_from_fixed(row.amount_units, row.amount_scale, "cash_ledger.amount")
        )
    return {key: _decimal_sum(values) for key, values in totals.items()}


def _reference_slippage(
    fills: pd.DataFrame,
    references: pd.DataFrame | None,
    base_currency: str,
) -> dict[str, tuple[Decimal, Decimal]]:
    """Return exact native/base slippage costs keyed by fill_id from causal references."""
    if references is None:
        return {}
    required = {
        "fill_id",
        "reference_time",
        "available_at",
        "reference_price_units",
        "reference_price_scale",
        "multiplier_units",
        "multiplier_scale",
        "fx_rate_units",
        "fx_rate_scale",
        "base_currency",
    }
    _require_frame_columns(references, "slippage_references", required)
    if references.duplicated(["fill_id"]).any():
        raise V2AttributionError("slippage_references.fill_id必须唯一")
    _require_frame_columns(
        fills,
        "fills",
        {
            "fill_id",
            "event_time",
            "side",
            "quantity_units",
            "quantity_scale",
            "price_units",
            "price_scale",
        },
    )
    indexed = references.set_index("fill_id", drop=False)
    result: dict[str, tuple[Decimal, Decimal]] = {}
    for fill in fills.itertuples(index=False):
        if fill.fill_id not in indexed.index:
            continue
        ref = indexed.loc[fill.fill_id]
        if isinstance(ref, pd.DataFrame):
            raise V2AttributionError("slippage_references.fill_id必须唯一")
        fill_time = _parse_utc(fill.event_time, "fills.event_time")
        if (
            _parse_utc(ref.reference_time, "reference_time") > fill_time
            or _parse_utc(ref.available_at, "available_at") > fill_time
        ):
            raise V2AttributionError("slippage reference在成交后才可得，违反PIT因果性")
        if ref.base_currency != base_currency:
            raise V2AttributionError("slippage reference的base_currency不匹配")
        quantity = _decimal_from_fixed(fill.quantity_units, fill.quantity_scale, "fills.quantity")
        fill_price = _decimal_from_fixed(fill.price_units, fill.price_scale, "fills.price")
        reference_price = _decimal_from_fixed(
            ref.reference_price_units, ref.reference_price_scale, "reference_price"
        )
        multiplier = _decimal_from_fixed(ref.multiplier_units, ref.multiplier_scale, "multiplier")
        fx_rate = _decimal_from_fixed(ref.fx_rate_units, ref.fx_rate_scale, "fx_rate")
        if multiplier <= 0 or fx_rate <= 0:
            raise V2AttributionError("slippage reference的multiplier与fx_rate必须为正")
        direction = Decimal(1) if fill.side == "buy" else Decimal(-1)
        native_cost = direction * (fill_price - reference_price) * quantity * multiplier
        if native_cost < 0:
            raise V2AttributionError("slippage reference给出了有利成交，不能记为成本")
        result[str(fill.fill_id)] = (native_cost, native_cost * fx_rate)
    return result


def _cost_records(
    costs: pd.DataFrame,
    ledger: pd.DataFrame,
    source: list[dict[str, Any]],
    fills: pd.DataFrame,
    references: pd.DataFrame | None,
    base_currency: str,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    _require_frame_columns(
        costs,
        "costs",
        {
            "event_time",
            "cost_id",
            "account_id",
            "strategy_id",
            "instrument_id",
            "fill_id",
            "cost_type",
            "amount_units",
            "amount_scale",
            "currency",
        },
    )
    cash_by_reference = _ledger_cash_by_reference(ledger)
    slippage_by_fill = _reference_slippage(fills, references, base_currency)
    source_costs: dict[tuple[str, str, str, str, str, str], list[dict[str, Any]]] = {}
    for record in source:
        if record["component"] in _LEDGER_COST_COMPONENTS:
            key = (
                record["event_time"].isoformat(),
                record["account_id"],
                record["strategy_id"],
                record["instrument_id"],
                record["component"],
                record["currency"],
            )
            source_costs.setdefault(key, []).append(record)

    result: list[dict[str, Any]] = []
    seen_slippage = False
    for row in costs.itertuples(index=False):
        component = str(row.cost_type)
        if component not in _LEDGER_COST_COMPONENTS:
            raise V2AttributionError(f"costs.cost_type未被M5受控: {component}")
        if component == "market_impact" and not config.get("market_impact_model_version"):
            raise V2AttributionError("market_impact必须声明冻结的market_impact_model_version")
        amount = _decimal_from_fixed(row.amount_units, row.amount_scale, "costs.amount")
        if amount < 0:
            raise V2AttributionError("costs.amount必须是非负费用绝对值")
        ledger_type = "funding" if component == "funding" else "fee"
        cash_amount = cash_by_reference.get((str(row.cost_id), ledger_type, str(row.currency)))
        if cash_amount is None:
            raise V2AttributionError(f"costs.{row.cost_id}缺少对应的cash_ledger现金分录")
        if component == "funding":
            if abs(cash_amount) != amount:
                raise V2AttributionError(f"funding {row.cost_id}与cash_ledger不精确相等")
            signed_amount = cash_amount
        else:
            if cash_amount != -amount:
                raise V2AttributionError(f"费用{row.cost_id}与cash_ledger不精确相等")
            signed_amount = -amount
        if component == "slippage":
            seen_slippage = True
            if pd.isna(row.fill_id) or str(row.fill_id) not in slippage_by_fill:
                raise V2AttributionError("slippage必须具备同一fill_id的因果reference")
            expected_native, _ = slippage_by_fill[str(row.fill_id)]
            if amount != expected_native:
                raise V2AttributionError("slippage成本与因果reference/fill价格不精确一致")
        key = (
            _key_time(row.event_time),
            str(row.account_id),
            str(row.strategy_id),
            str(row.instrument_id),
            component,
            str(row.currency),
        )
        matching_source = source_costs.get(key, [])
        if row.currency == base_currency:
            base_amount = signed_amount
            if (
                matching_source
                and _decimal_sum([item["base_amount"] for item in matching_source]) != base_amount
            ):
                raise V2AttributionError("attribution成本明细与costs/cash_ledger不精确一致")
        else:
            if not matching_source:
                raise V2AttributionError("非基础币种成本必须提供对应的base_amount归因明细")
            if _decimal_sum([item["amount"] for item in matching_source]) != signed_amount:
                raise V2AttributionError("非基础币种attribution成本金额与现金账本不一致")
            base_amount = _decimal_sum([item["base_amount"] for item in matching_source])
        result.append(
            _component_record(
                event_time=row.event_time,
                account_id=row.account_id,
                strategy_id=row.strategy_id,
                instrument_id=row.instrument_id,
                component=component,
                currency=row.currency,
                amount=signed_amount,
                base_currency=base_currency,
                base_amount=base_amount,
            )
        )
    if references is not None and not seen_slippage and not references.empty:
        raise V2AttributionError("提供slippage_references时必须有对应的slippage成本")
    return result


def _aggregate(
    records: list[dict[str, Any]], keys: tuple[str, ...]
) -> dict[tuple[Any, ...], Decimal]:
    result: dict[tuple[Any, ...], list[Decimal]] = {}
    for record in records:
        key = tuple(record[key] for key in keys)
        result.setdefault(key, []).append(record["base_amount"])
    return {key: _decimal_sum(values) for key, values in result.items()}


def _snapshot_deltas(
    snapshots: pd.DataFrame, base_currency: str
) -> dict[tuple[pd.Timestamp, str], Decimal]:
    _require_frame_columns(
        snapshots,
        "portfolio_snapshots",
        {"event_time", "account_id", "base_currency", "nav_units", "nav_scale"},
    )
    expected: dict[tuple[pd.Timestamp, str], Decimal] = {}
    for account_id, group in snapshots.groupby("account_id", sort=True):
        ordered = group.copy()
        ordered["_time"] = ordered["event_time"].map(
            lambda value: _parse_utc(value, "snapshot.event_time")
        )
        ordered = ordered.sort_values("_time", kind="stable")
        if not ordered["base_currency"].eq(base_currency).all():
            raise V2AttributionError("portfolio_snapshots.base_currency不一致")
        prior: Decimal | None = None
        for _, row in ordered.iterrows():
            nav = _decimal_from_fixed(row["nav_units"], row["nav_scale"], "portfolio_snapshots.nav")
            if prior is not None:
                expected[(row["_time"], str(account_id))] = nav - prior
            prior = nav
    return expected


def _strategy_deltas(
    returns: pd.DataFrame, base_currency: str
) -> dict[tuple[pd.Timestamp, str], Decimal]:
    _require_frame_columns(
        returns,
        "returns",
        {"event_time", "strategy_id", "nav_units", "nav_scale", "base_currency"},
    )
    expected: dict[tuple[pd.Timestamp, str], Decimal] = {}
    for strategy_id, group in returns.groupby("strategy_id", sort=True):
        ordered = group.copy()
        ordered["_time"] = ordered["event_time"].map(
            lambda value: _parse_utc(value, "returns.event_time")
        )
        ordered = ordered.sort_values("_time", kind="stable")
        if not ordered["base_currency"].eq(base_currency).all():
            raise V2AttributionError("returns.base_currency不一致")
        prior: Decimal | None = None
        for _, row in ordered.iterrows():
            nav = _decimal_from_fixed(row["nav_units"], row["nav_scale"], "returns.nav")
            if prior is not None:
                expected[(row["_time"], str(strategy_id))] = nav - prior
            prior = nav
    return expected


def _reconciliation_rows(
    records: list[dict[str, Any]],
    snapshots: pd.DataFrame,
    returns: pd.DataFrame,
    base_currency: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Check account/portfolio NAV, strategy NAV and instrument component identities."""
    by_account = _aggregate(records, ("event_time", "account_id"))
    by_strategy = _aggregate(records, ("event_time", "strategy_id"))
    by_instrument = _aggregate(records, ("event_time", "instrument_id"))
    account_deltas = _snapshot_deltas(snapshots, base_currency)
    strategy_deltas = _strategy_deltas(returns, base_currency)
    rows: list[dict[str, Any]] = []

    def append(
        level: str, event_time: pd.Timestamp, identity: str, expected: Decimal, actual: Decimal
    ):
        residual = expected - actual
        threshold = max(abs(expected) * Decimal("1e-8"), Decimal("0.01"))
        if abs(residual) > threshold:
            raise V2AttributionError(
                f"{level}归因残差{residual}超过阈值{threshold}: {identity}@{event_time.isoformat()}"
            )
        expected_units, expected_scale = _fixed_from_decimal(expected)
        actual_units, actual_scale = _fixed_from_decimal(actual)
        residual_units, residual_scale = _fixed_from_decimal(residual)
        threshold_units, threshold_scale = _fixed_from_decimal(threshold)
        rows.append(
            {
                "level": level,
                "event_time": event_time.isoformat(),
                "identity": identity,
                "base_currency": base_currency,
                "delta_nav_units": expected_units,
                "delta_nav_scale": expected_scale,
                "attributed_units": actual_units,
                "attributed_scale": actual_scale,
                "residual_units": residual_units,
                "residual_scale": residual_scale,
                "threshold_units": threshold_units,
                "threshold_scale": threshold_scale,
                "status": "pass",
            }
        )

    for key, expected in account_deltas.items():
        append("account", key[0], key[1], expected, by_account.get(key, Decimal(0)))
    by_portfolio_expected: dict[pd.Timestamp, list[Decimal]] = {}
    for (event_time, _), delta in account_deltas.items():
        by_portfolio_expected.setdefault(event_time, []).append(delta)
    for event_time, deltas in by_portfolio_expected.items():
        append(
            "portfolio",
            event_time,
            "__portfolio__",
            _decimal_sum(deltas),
            _decimal_sum(
                [amount for (time, _), amount in by_account.items() if time == event_time]
            ),
        )
    for key, expected in strategy_deltas.items():
        append("strategy", key[0], key[1], expected, by_strategy.get(key, Decimal(0)))
    for (event_time, instrument_id), amount in sorted(
        by_instrument.items(), key=lambda item: item[0]
    ):
        # v2 has no per-instrument NAV field; the invariant is exact roll-up to its source components.
        append("instrument", event_time, instrument_id, amount, amount)
    if not rows:
        raise V2AttributionError("没有可用于区间归因的连续NAV快照")
    frame = pd.DataFrame(rows).sort_values(["event_time", "level", "identity"], kind="stable")
    counts = {level: int((frame["level"] == level).sum()) for level in frame["level"].unique()}
    return frame.reset_index(drop=True), counts


def _report_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in records:
        amount_units, amount_scale = _fixed_from_decimal(record["amount"])
        base_units, base_scale = _fixed_from_decimal(record["base_amount"])
        rows.append(
            {
                "event_time": record["event_time"].isoformat(),
                "account_id": record["account_id"],
                "strategy_id": record["strategy_id"],
                "instrument_id": record["instrument_id"],
                "component": record["component"],
                "amount_units": amount_units,
                "amount_scale": amount_scale,
                "currency": record["currency"],
                "base_amount_units": base_units,
                "base_amount_scale": base_scale,
                "base_currency": record["base_currency"],
            }
        )
    return (
        pd.DataFrame(
            rows,
            columns=[
                "event_time",
                "account_id",
                "strategy_id",
                "instrument_id",
                "component",
                "amount_units",
                "amount_scale",
                "currency",
                "base_amount_units",
                "base_amount_scale",
                "base_currency",
            ],
        )
        .sort_values(
            ["event_time", "account_id", "strategy_id", "instrument_id", "component", "currency"],
            kind="stable",
        )
        .reset_index(drop=True)
    )


def reconcile_standard_run_v2(
    run_dir: str | Path,
    *,
    out_dir: str | Path | None = None,
    slippage_references: pd.DataFrame | None = None,
) -> V2AttributionManifest:
    """Publish an exact, separately-stored M5 attribution report from an immutable v2 run.

    The reader delegates all file, hash, schema and lineage checks to QLab before it opens a
    Parquet file. v2 corruption therefore raises immediately and never reaches the v1 reader.
    """
    run_path, manifest, frames, source_hash = _read_validated_v2(run_dir)
    required = {"returns", "portfolio_snapshots", "costs", "cash_ledger", "fills"}
    missing = sorted(required - set(frames))
    if missing:
        raise V2AttributionError(f"M5归因需要的v2 Parquet产物缺失: {missing}")
    config_path = run_path / "standard" / "v2" / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    source = _source_components(frames.get("attribution", pd.DataFrame()), manifest.base_currency)
    non_cost = [record for record in source if record["component"] in _NON_COST_COMPONENTS]
    costs = _cost_records(
        frames["costs"],
        frames["cash_ledger"],
        source,
        frames["fills"],
        slippage_references,
        manifest.base_currency,
        config,
    )
    records = non_cost + costs
    if not records:
        raise V2AttributionError("v2运行未提供任何可归因的价格、收益或成本组件")
    reconciliation, level_counts = _reconciliation_rows(
        records, frames["portfolio_snapshots"], frames["returns"], manifest.base_currency
    )
    detail = _report_frame(records)
    destination = Path(out_dir) if out_dir is not None else run_path / "reports" / "attribution-v2"
    if destination.exists():
        raise FileExistsError(f"归因报告目录已存在，拒绝改写: {destination}")
    destination.mkdir(parents=True, exist_ok=False)
    detail_path = destination / "attribution.csv"
    reconciliation_path = destination / "reconciliation.csv"
    detail.to_csv(detail_path, index=False, encoding="utf-8", lineterminator="\n")
    reconciliation.to_csv(reconciliation_path, index=False, encoding="utf-8", lineterminator="\n")
    files = {path.name: _sha256(path) for path in (detail_path, reconciliation_path)}
    result = V2AttributionManifest(
        schema_version="2.0",
        source_run_manifest_sha256=source_hash,
        source_run_id=manifest.run_id,
        source_schema_version=manifest.schema_version,
        base_currency=manifest.base_currency,
        files=files,
        row_counts={detail_path.name: len(detail), reconciliation_path.name: len(reconciliation)},
        reconciliation=level_counts,
    )
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


@dataclass(frozen=True)
class AttributionManifest:
    schema_version: str
    run_dir: str
    position_timing: str
    files: dict[str, str]
    row_counts: dict[str, int]


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{name}缺少字段: {missing}")


def _normalise_dates(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="raise").dt.normalize()
    return out


def _active_weights(
    positions: pd.DataFrame,
    asset_returns: pd.DataFrame,
    *,
    allow_same_day_positions: bool,
) -> pd.DataFrame:
    """Align complete position snapshots to later asset-return periods without look-ahead."""
    _require_columns(positions, {"date", "strategy", "symbol", "weight"}, "positions")
    _require_columns(asset_returns, {"date", "symbol", "return"}, "asset_returns")
    pos = _normalise_dates(positions)
    ret = _normalise_dates(asset_returns)
    pos["weight"] = pd.to_numeric(pos["weight"], errors="coerce")
    ret["return"] = pd.to_numeric(ret["return"], errors="coerce")
    if pos.duplicated(["date", "strategy", "symbol"]).any():
        raise ValueError("positions在date/strategy/symbol上必须唯一")
    if ret.duplicated(["date", "symbol"]).any():
        raise ValueError("asset_returns在date/symbol上必须唯一")

    return_dates = np.array(sorted(ret["date"].unique()), dtype="datetime64[ns]")
    rows: list[pd.DataFrame] = []
    for strategy, strategy_pos in pos.groupby("strategy", sort=False):
        snapshot_dates = np.array(sorted(strategy_pos["date"].unique()), dtype="datetime64[ns]")
        side = "right" if allow_same_day_positions else "left"
        indices = np.searchsorted(snapshot_dates, return_dates, side=side) - 1
        for return_date, snapshot_idx in zip(return_dates, indices, strict=True):
            if snapshot_idx < 0:
                continue
            snapshot_date = pd.Timestamp(snapshot_dates[snapshot_idx])
            active = strategy_pos.loc[
                strategy_pos["date"].eq(snapshot_date), ["symbol", "weight"]
            ].copy()
            period_returns = ret.loc[
                ret["date"].eq(pd.Timestamp(return_date)), ["symbol", "return"]
            ]
            active = active.merge(period_returns, on="symbol", how="left", validate="one_to_one")
            active.insert(0, "date", pd.Timestamp(return_date))
            active.insert(1, "strategy", strategy)
            active.insert(2, "position_date", snapshot_date)
            rows.append(active)
    if not rows:
        return pd.DataFrame(
            columns=["date", "strategy", "position_date", "symbol", "weight", "return"]
        )
    return pd.concat(rows, ignore_index=True)


def holdings_attribution(
    positions: pd.DataFrame,
    asset_returns: pd.DataFrame,
    *,
    costs: pd.DataFrame | None = None,
    portfolio_returns: pd.DataFrame | None = None,
    allow_same_day_positions: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attribute gross and net portfolio return to held securities and transaction costs."""
    detail = _active_weights(
        positions,
        asset_returns,
        allow_same_day_positions=allow_same_day_positions,
    )
    if detail.empty:
        return detail, pd.DataFrame()
    detail["missing_return"] = detail["return"].isna()
    detail["contribution"] = detail["weight"] * detail["return"]
    summary = (
        detail.groupby(["date", "strategy"], as_index=False)
        .agg(
            gross_attributed_return=("contribution", lambda values: values.sum(min_count=1)),
            covered_weight=(
                "weight",
                lambda values: values[detail.loc[values.index, "return"].notna()].sum(),
            ),
            total_weight=("weight", "sum"),
            missing_return_count=("missing_return", "sum"),
        )
        .sort_values(["strategy", "date"])
    )
    if costs is not None and not costs.empty:
        _require_columns(costs, {"date", "strategy", "total_cost"}, "costs")
        cost_frame = _normalise_dates(costs)
        cost_frame["total_cost"] = pd.to_numeric(cost_frame["total_cost"], errors="coerce")
        cost_frame = cost_frame.groupby(["date", "strategy"], as_index=False)["total_cost"].sum()
        summary = summary.merge(cost_frame, on=["date", "strategy"], how="left")
    else:
        summary["total_cost"] = 0.0
    summary["total_cost"] = summary["total_cost"].fillna(0.0)
    summary["net_attributed_return"] = summary["gross_attributed_return"] - summary["total_cost"]

    if portfolio_returns is not None and not portfolio_returns.empty:
        _require_columns(
            portfolio_returns,
            {"date", "strategy", "gross_return", "net_return"},
            "portfolio_returns",
        )
        observed = _normalise_dates(portfolio_returns)[
            ["date", "strategy", "gross_return", "net_return"]
        ].copy()
        summary = summary.merge(observed, on=["date", "strategy"], how="left")
        summary["gross_residual"] = summary["gross_return"] - summary["gross_attributed_return"]
        summary["net_residual"] = summary["net_return"] - summary["net_attributed_return"]
    return detail, summary


def factor_attribution(
    exposures: pd.DataFrame,
    factor_returns: pd.DataFrame,
    *,
    portfolio_returns: pd.DataFrame | None = None,
    allow_same_day_exposures: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attribute portfolio returns to factor exposures, preserving unexplained residual."""
    _require_columns(exposures, {"date", "strategy", "name", "value"}, "exposures")
    _require_columns(factor_returns, {"date", "name", "return"}, "factor_returns")
    exp = _normalise_dates(exposures)
    exp = exp.loc[exp.get("exposure_type", "factor").eq("factor")].copy()
    fac = _normalise_dates(factor_returns)
    fac["return"] = pd.to_numeric(fac["return"], errors="coerce")
    if fac.duplicated(["date", "name"]).any():
        raise ValueError("factor_returns在date/name上必须唯一")

    rows: list[pd.DataFrame] = []
    factor_dates = np.array(sorted(fac["date"].unique()), dtype="datetime64[ns]")
    for strategy, strategy_exp in exp.groupby("strategy", sort=False):
        snapshot_dates = np.array(sorted(strategy_exp["date"].unique()), dtype="datetime64[ns]")
        side = "right" if allow_same_day_exposures else "left"
        indices = np.searchsorted(snapshot_dates, factor_dates, side=side) - 1
        for factor_date, snapshot_idx in zip(factor_dates, indices, strict=True):
            if snapshot_idx < 0:
                continue
            snapshot_date = pd.Timestamp(snapshot_dates[snapshot_idx])
            active = strategy_exp.loc[
                strategy_exp["date"].eq(snapshot_date), ["name", "value"]
            ].copy()
            period = fac.loc[fac["date"].eq(pd.Timestamp(factor_date)), ["name", "return"]]
            active = active.merge(period, on="name", how="left", validate="one_to_one")
            active.insert(0, "date", pd.Timestamp(factor_date))
            active.insert(1, "strategy", strategy)
            active.insert(2, "exposure_date", snapshot_date)
            rows.append(active)
    detail = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if detail.empty:
        return detail, pd.DataFrame()
    detail["factor_contribution"] = (
        pd.to_numeric(detail["value"], errors="coerce") * detail["return"]
    )
    summary = detail.groupby(["date", "strategy"], as_index=False).agg(
        explained_return=("factor_contribution", lambda values: values.sum(min_count=1)),
        missing_factor_count=("return", lambda values: int(values.isna().sum())),
    )
    if portfolio_returns is not None and not portfolio_returns.empty:
        _require_columns(
            portfolio_returns, {"date", "strategy", "gross_return"}, "portfolio_returns"
        )
        observed = _normalise_dates(portfolio_returns)[["date", "strategy", "gross_return"]].copy()
        summary = summary.merge(observed, on=["date", "strategy"], how="left")
        summary["specific_return"] = summary["gross_return"] - summary["explained_return"]
    return detail, summary


def brinson_fachler_attribution(
    portfolio_positions: pd.DataFrame,
    benchmark_positions: pd.DataFrame,
    asset_returns: pd.DataFrame,
    classifications: pd.DataFrame,
    *,
    allow_same_day_positions: bool = False,
) -> pd.DataFrame:
    """Compute Brinson-Fachler allocation, selection and interaction effects."""
    _require_columns(classifications, {"symbol", "group"}, "classifications")
    benchmark = benchmark_positions.copy()
    if "strategy" not in benchmark:
        benchmark["strategy"] = "benchmark"
    p_aligned = _active_weights(
        portfolio_positions,
        asset_returns,
        allow_same_day_positions=allow_same_day_positions,
    )
    b_aligned = _active_weights(
        benchmark,
        asset_returns,
        allow_same_day_positions=allow_same_day_positions,
    )
    if p_aligned.empty or b_aligned.empty:
        return pd.DataFrame()
    classes = classifications[["symbol", "group"]].drop_duplicates("symbol")
    p_aligned = p_aligned.merge(classes, on="symbol", how="left", validate="many_to_one")
    b_aligned = b_aligned.merge(classes, on="symbol", how="left", validate="many_to_one")
    p_aligned["group"] = p_aligned["group"].fillna("__unclassified__")
    b_aligned["group"] = b_aligned["group"].fillna("__unclassified__")

    def grouped(frame: pd.DataFrame, weight_name: str, return_name: str) -> pd.DataFrame:
        work = frame.copy()
        work["weighted_return"] = work["weight"] * work["return"]
        result = work.groupby(["date", "group"], as_index=False).agg(
            **{
                weight_name: ("weight", "sum"),
                "weighted": ("weighted_return", lambda values: values.sum(min_count=1)),
            }
        )
        result[return_name] = np.where(
            result[weight_name].abs() > 1e-15,
            result["weighted"] / result[weight_name],
            0.0,
        )
        return result.drop(columns="weighted")

    benchmark_strategy = str(b_aligned["strategy"].iloc[0])
    benchmark_group = grouped(b_aligned, "benchmark_weight", "benchmark_group_return")
    benchmark_total = (
        b_aligned.assign(weighted=lambda x: x["weight"] * x["return"])
        .groupby("date", as_index=False)["weighted"]
        .sum(min_count=1)
        .rename(columns={"weighted": "benchmark_return"})
    )
    outputs: list[pd.DataFrame] = []
    for strategy, strategy_frame in p_aligned.groupby("strategy", sort=False):
        portfolio_group = grouped(strategy_frame, "portfolio_weight", "portfolio_group_return")
        out = portfolio_group.merge(benchmark_group, on=["date", "group"], how="outer")
        out = out.merge(benchmark_total, on="date", how="left")
        for column in [
            "portfolio_weight",
            "benchmark_weight",
            "portfolio_group_return",
            "benchmark_group_return",
        ]:
            out[column] = out[column].fillna(0.0)
        out["allocation"] = (out["portfolio_weight"] - out["benchmark_weight"]) * (
            out["benchmark_group_return"] - out["benchmark_return"]
        )
        out["selection"] = out["benchmark_weight"] * (
            out["portfolio_group_return"] - out["benchmark_group_return"]
        )
        out["interaction"] = (out["portfolio_weight"] - out["benchmark_weight"]) * (
            out["portfolio_group_return"] - out["benchmark_group_return"]
        )
        out["active_contribution"] = out[["allocation", "selection", "interaction"]].sum(axis=1)
        out.insert(1, "strategy", strategy)
        out["benchmark_strategy"] = benchmark_strategy
        outputs.append(out.sort_values(["date", "group"]))
    return pd.concat(outputs, ignore_index=True)


def attribute_standard_run(
    run_dir: str | Path,
    asset_returns: pd.DataFrame,
    *,
    factor_returns: pd.DataFrame | None = None,
    benchmark_positions: pd.DataFrame | None = None,
    classifications: pd.DataFrame | None = None,
    out_dir: str | Path | None = None,
    allow_same_day_positions: bool = False,
) -> AttributionManifest:
    """Read schema-v1 standard artifacts and persist a reproducible attribution bundle."""
    run_path = Path(run_dir)
    standard = run_path / "standard"
    required = ["run_manifest.json", "positions.csv", "returns.csv", "costs.csv"]
    missing = [name for name in required if not (standard / name).is_file()]
    if missing:
        raise FileNotFoundError(f"标准运行产物缺失: {missing}")
    from quant_lab.contracts import load_and_validate_run

    load_and_validate_run(run_path)

    positions = pd.read_csv(standard / "positions.csv")
    returns = pd.read_csv(standard / "returns.csv")
    costs = pd.read_csv(standard / "costs.csv")
    holdings, summary = holdings_attribution(
        positions,
        asset_returns,
        costs=costs,
        portfolio_returns=returns,
        allow_same_day_positions=allow_same_day_positions,
    )
    outputs: dict[str, pd.DataFrame] = {
        "holdings": holdings,
        "summary": summary,
    }
    exposures_path = standard / "exposures.csv"
    if factor_returns is not None:
        if not exposures_path.is_file():
            raise FileNotFoundError("因子归因需要standard/exposures.csv")
        factor_detail, factor_summary = factor_attribution(
            pd.read_csv(exposures_path),
            factor_returns,
            portfolio_returns=returns,
            allow_same_day_exposures=allow_same_day_positions,
        )
        outputs["factors"] = factor_detail
        outputs["factor_summary"] = factor_summary
    if benchmark_positions is not None or classifications is not None:
        if benchmark_positions is None or classifications is None:
            raise ValueError("Brinson归因必须同时提供benchmark_positions和classifications")
        outputs["brinson"] = brinson_fachler_attribution(
            positions,
            benchmark_positions,
            asset_returns,
            classifications,
            allow_same_day_positions=allow_same_day_positions,
        )

    destination = Path(out_dir) if out_dir is not None else run_path / "attribution"
    destination.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    row_counts: dict[str, int] = {}
    for name, frame in outputs.items():
        target = destination / f"{name}.csv"
        frame.to_csv(target, index=False, encoding="utf-8-sig")
        files[target.name] = _sha256(target)
        row_counts[target.name] = len(frame)
    manifest = AttributionManifest(
        schema_version="1.0",
        run_dir=str(run_path.resolve()),
        position_timing="same_day" if allow_same_day_positions else "prior_snapshot",
        files=files,
        row_counts=row_counts,
    )
    (destination / "manifest.json").write_text(
        json.dumps(asdict(manifest), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest
