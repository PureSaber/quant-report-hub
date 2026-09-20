"""Operational sidecars and portable daily packages for the dashboard."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path

from quant_report_hub.dashboard import render_dashboard


def _atomic_bytes(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as stream:
            temporary = stream.name
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()
    return path


def write_json(path: Path, value: object) -> Path:
    return _atomic_bytes(
        path.resolve(),
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def write_runtime_sidecars(snapshot: dict, dashboard: Path) -> list[Path]:
    """Write alert and refresh metadata beside a generated dashboard."""
    dashboard = dashboard.resolve()
    alerts = write_json(
        dashboard.with_suffix(".alerts.json"),
        {
            "schema_version": "quant-report-hub.alerts/v1",
            "generated_at": snapshot["generated_at"],
            "alerts": snapshot.get("alerts", []),
        },
    )
    status = write_json(
        dashboard.with_suffix(dashboard.suffix + ".status.json"),
        {
            "schema_version": "quant-report-hub.dashboard-status/v1",
            "build_id": snapshot["generated_at"],
            "generated_at": snapshot["generated_at"],
            "alert_counts": {
                severity: sum(row["severity"] == severity for row in snapshot.get("alerts", []))
                for severity in ("critical", "warning", "info")
            },
        },
    )
    return [alerts, status]


def _write_csv(path: Path, rows: Iterable[dict], fields: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="",
            dir=path.parent,
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = stream.name
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()
    return path


def _decision_rows(snapshot: dict) -> list[dict]:
    rows = []
    for source in snapshot["sources"]:
        item = source["current"]
        card = item.get("card", {})
        execution = item.get("execution", {})
        rows.append(
            {
                "source": Path(source["root"]).name,
                "project": item.get("identity", {}).get("project", ""),
                "run_id": item["run_id"],
                "status": item["status"],
                "as_of": card.get("as_of", ""),
                "valid_until": card.get("valid_until", ""),
                "strategies": ";".join(item.get("identity", {}).get("strategies", [])),
                "planned_orders": execution.get("planned_orders", 0),
                "matched_orders": execution.get("matched_orders", 0),
                "orders_with_fills": execution.get("orders_with_fills", 0),
                "observed_days": item.get("outcome", {}).get("observed_days", 0),
                "error": item.get("error", ""),
            }
        )
    return rows


def _execution_rows(snapshot: dict) -> list[dict]:
    rows = []
    for source in snapshot["sources"]:
        for item in [source["current"], *source["history"]]:
            for order in item.get("execution", {}).get("orders", []):
                rows.append(
                    {
                        "source": Path(source["root"]).name,
                        "decision_run_id": item["run_id"],
                        **order,
                        "evidence_runs": ";".join(
                            item.get("execution", {}).get("evidence_runs", [])
                        ),
                    }
                )
    return rows


def _outcome_rows(snapshot: dict) -> list[dict]:
    rows = []
    for source in snapshot["sources"]:
        for item in [source["current"], *source["history"]]:
            outcome = item.get("outcome", {})
            if not outcome:
                continue
            windows = {f"return_{row['days']}d": row.get("return") for row in outcome["windows"]}
            rows.append(
                {
                    "source": Path(source["root"]).name,
                    "run_id": item["run_id"],
                    "observed_days": outcome.get("observed_days"),
                    "observed_return": outcome.get("observed_return"),
                    "benchmark_return": outcome.get("benchmark_return"),
                    **windows,
                    "notice": outcome.get("notice", ""),
                }
            )
    return rows


def find_browser(explicit: Path | None = None) -> Path | None:
    candidates = [explicit] if explicit else []
    for name in ("msedge", "google-chrome", "chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    if os.name == "nt":
        candidates.extend(
            [
                Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
                Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            ]
        )
    return next((path.resolve() for path in candidates if path and path.is_file()), None)


def render_pdf(html: Path, pdf: Path, *, browser: Path | None = None) -> Path:
    executable = find_browser(browser)
    if executable is None:
        raise RuntimeError("No supported Chromium or Edge browser was found for PDF export")
    pdf = pdf.resolve()
    temporary = pdf.with_name(f".{pdf.stem}-{os.getpid()}.tmp.pdf")
    with tempfile.TemporaryDirectory(prefix="quant-report-browser-") as profile:
        result = subprocess.run(
            [
                str(executable),
                "--headless",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--user-data-dir={profile}",
                f"--print-to-pdf={temporary}",
                html.resolve().as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    if (
        result.returncode
        or not temporary.is_file()
        or not temporary.read_bytes().startswith(b"%PDF")
    ):
        temporary.unlink(missing_ok=True)
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"Browser PDF export failed: {detail or result.returncode}")
    os.replace(temporary, pdf)
    return pdf


def write_daily_package(
    snapshot: dict,
    out_dir: Path,
    *,
    browser: Path | None = None,
    include_pdf: bool = True,
) -> list[Path]:
    """Publish a self-contained HTML/PDF/CSV daily handoff package."""
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    html = out_dir / "index.html"
    _atomic_bytes(html, render_dashboard(snapshot, html).encode("utf-8"))
    outputs = [html, *write_runtime_sidecars(snapshot, html)]

    decisions = _decision_rows(snapshot)
    execution = _execution_rows(snapshot)
    outcomes = _outcome_rows(snapshot)
    csv_specs = [
        (
            "decisions.csv",
            decisions,
            list(decisions[0]) if decisions else ["source", "run_id", "status"],
        ),
        (
            "execution.csv",
            execution,
            list(execution[0]) if execution else ["source", "decision_run_id", "symbol"],
        ),
        (
            "outcomes.csv",
            outcomes,
            list(outcomes[0]) if outcomes else ["source", "run_id", "observed_days"],
        ),
        (
            "accounts.csv",
            snapshot.get("accounts", []),
            list(snapshot["accounts"][0])
            if snapshot.get("accounts")
            else ["source", "account_id", "status"],
        ),
        (
            "alerts.csv",
            snapshot.get("alerts", []),
            list(snapshot["alerts"][0])
            if snapshot.get("alerts")
            else ["alert_id", "severity", "code", "source", "run_id", "message"],
        ),
    ]
    outputs.extend(_write_csv(out_dir / name, rows, fields) for name, rows, fields in csv_specs)
    if include_pdf:
        outputs.append(render_pdf(html, out_dir / "daily-report.pdf", browser=browser))

    manifest = {
        "schema_version": "quant-report-hub.daily-package/v1",
        "generated_at": snapshot["generated_at"],
        "files": [
            {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in outputs
        ],
    }
    outputs.append(write_json(out_dir / "manifest.json", manifest))
    return outputs
