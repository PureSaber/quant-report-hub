"""Local watch server for a continuously refreshed research dashboard."""

from __future__ import annotations

import functools
import hashlib
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from quant_report_hub.dashboard import write_dashboard_bundle
from quant_report_hub.dashboard_exports import write_runtime_sidecars


def source_fingerprint(roots: list[Path], db: Path | None) -> str:
    """Hash source file metadata cheaply enough for a polling watch loop."""
    records: list[tuple[str, int, int]] = []
    patterns = (
        "latest.json",
        "*/decision.json",
        "*/standard/v2/run_manifest.json",
        "*/standard/v2/*.parquet",
        "*/standard/v2/*.json",
    )
    for root in sorted({path.resolve() for path in roots}, key=str):
        for pattern in patterns:
            for path in root.glob(pattern) if root.is_dir() else []:
                if path.is_file():
                    stat = path.stat()
                    records.append((str(path.resolve()), stat.st_size, stat.st_mtime_ns))
    if db and db.is_file():
        stat = db.stat()
        records.append((str(db.resolve()), stat.st_size, stat.st_mtime_ns))
    payload = json.dumps(sorted(set(records)), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def default_serve_root(roots: list[Path], out: Path, db: Path | None = None) -> Path:
    paths = [out.resolve().parent, *(root.resolve() for root in roots)]
    if db:
        paths.append(db.resolve().parent)
    common = Path(paths[0])
    for path in paths[1:]:
        while common != common.parent and not path.is_relative_to(common):
            common = common.parent
    if common == common.parent:
        return out.resolve().parent
    return common


class DashboardHandler(SimpleHTTPRequestHandler):
    """Static handler with no-cache headers for dashboard runtime files."""

    def log_message(self, _format: str, *_args: object) -> None:
        # The browser polls the status sidecar every five seconds.  Suppress
        # per-request access logs so an unattended local server stays quiet.
        return

    def end_headers(self) -> None:
        if self.path.endswith((".html", ".json")):
            self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()


def serve_dashboard(
    roots: list[Path],
    out: Path,
    *,
    db: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8767,
    poll_seconds: float = 2.0,
    serve_root: Path | None = None,
) -> str:
    """Generate, serve, and regenerate the dashboard when inputs change."""
    roots = [root.resolve() for root in roots]
    out = out.resolve()
    db = db.resolve() if db else None
    serve_root = (serve_root or default_serve_root(roots, out, db)).resolve()
    if not out.is_relative_to(serve_root):
        raise ValueError("Dashboard output must be inside the HTTP serve root")

    destination, snapshot = write_dashboard_bundle(roots, out, db=db)
    write_runtime_sidecars(snapshot, destination)
    fingerprint = source_fingerprint(roots, db)
    handler = functools.partial(DashboardHandler, directory=str(serve_root))
    relative = destination.relative_to(serve_root).as_posix()
    url = f"http://{host}:{port}/{relative}"
    with ThreadingHTTPServer((host, port), handler) as server:
        server.timeout = poll_seconds
        print(f"serving research dashboard -> {url}", flush=True)
        try:
            while True:
                server.handle_request()
                current = source_fingerprint(roots, db)
                if current == fingerprint:
                    continue
                destination, snapshot = write_dashboard_bundle(roots, out, db=db)
                write_runtime_sidecars(snapshot, destination)
                fingerprint = current
                print(f"refreshed research dashboard -> {destination}", flush=True)
        except KeyboardInterrupt:
            pass
    return url
