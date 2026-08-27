"""Performance attribution for standard quant research runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
