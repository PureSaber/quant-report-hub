"""Local watch server for a continuously refreshed research dashboard."""

from __future__ import annotations

import functools
import hashlib
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast

from quant_report_hub.dashboard import EVIDENCE_FILES, write_dashboard_bundle
from quant_report_hub.dashboard_exports import write_runtime_sidecars


def source_fingerprint(
    roots: list[Path],
    db: Path | None,
    *,
    paired_evidence: list[tuple[Path, str]] | None = None,
) -> str:
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
    for source, _sha in paired_evidence or []:
        root = Path(source).resolve().parent
        for path in root.rglob("*"):
            if path.is_file() and path.resolve().is_relative_to(root):
                stat = path.stat()
                records.append((str(path.resolve()), stat.st_size, stat.st_mtime_ns))
    payload = json.dumps(sorted(set(records)), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def default_serve_root(roots: list[Path], out: Path, db: Path | None = None) -> Path:
    """Choose a URL mount point, not a directory whose contents may be served."""
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


def published_files(snapshot: dict, dashboard: Path, sidecars: list[Path]) -> frozenset[Path]:
    """Publish the dashboard and explicit evidence, never entire directories."""
    paths = {dashboard.resolve(), *(path.resolve() for path in sidecars)}
    runs: list[tuple[Path, Path]] = []
    for source in snapshot["sources"]:
        root = Path(source["root"]).resolve()
        for item in [source["current"], *source["history"]]:
            if item.get("path"):
                runs.append((Path(item["path"]).absolute().parent, root))
    for row in snapshot["experiments"]:
        run = Path(row["run_path"]).absolute()
        runs.append((run, run))
    for run, root in runs:
        for name, _label in EVIDENCE_FILES:
            path = run / name
            # A linked file or directory must not broaden the publication boundary.
            if path.resolve() == path and path.is_relative_to(root) and path.is_file():
                paths.add(path)
    return frozenset(paths)


class DashboardHTTPServer(ThreadingHTTPServer):
    published_files: frozenset[Path] = frozenset()


class DashboardHandler(SimpleHTTPRequestHandler):
    """Loopback-only, file-allowlisted static HTTP handler."""

    def send_head(self):
        server = cast(DashboardHTTPServer, self.server)
        port = server.server_port
        authorities = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            authorities.update({"127.0.0.1", "localhost"})
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0].lower() not in authorities:
            self.send_error(403, "Untrusted Host")
            return None
        path = Path(self.translate_path(self.path)).absolute()
        if path not in server.published_files or path.resolve() != path or not path.is_file():
            self.send_error(404, "File not published")
            return None
        return super().send_head()

    def log_message(self, _format: str, *_args: object) -> None:
        # The browser polls the status sidecar every five seconds.  Suppress
        # per-request access logs so an unattended local server stays quiet.
        return

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
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
    paired_evidence: list[tuple[Path, str]] | None = None,
) -> str:
    """Generate, serve, and regenerate the dashboard when inputs change."""
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Dashboard host must be 127.0.0.1 or localhost")
    roots = [root.resolve() for root in roots]
    out = out.resolve()
    db = db.resolve() if db else None
    serve_root = (serve_root or default_serve_root(roots, out, db)).resolve()
    if not out.is_relative_to(serve_root):
        raise ValueError("Dashboard output must be inside the HTTP serve root")

    paired_options = {"paired_evidence": paired_evidence} if paired_evidence else {}
    destination, snapshot = write_dashboard_bundle(roots, out, db=db, **paired_options)
    sidecars = write_runtime_sidecars(snapshot, destination)
    fingerprint = source_fingerprint(roots, db, **paired_options)
    handler = functools.partial(DashboardHandler, directory=str(serve_root))
    relative = destination.relative_to(serve_root).as_posix()
    with DashboardHTTPServer((host, port), handler) as server:
        server.published_files = published_files(snapshot, destination, sidecars)
        url = f"http://{host}:{server.server_port}/{relative}"
        server.timeout = poll_seconds
        print(f"serving research dashboard -> {url}", flush=True)
        try:
            while True:
                server.handle_request()
                current = source_fingerprint(roots, db, **paired_options)
                if current == fingerprint:
                    continue
                destination, snapshot = write_dashboard_bundle(roots, out, db=db, **paired_options)
                sidecars = write_runtime_sidecars(snapshot, destination)
                server.published_files = published_files(snapshot, destination, sidecars)
                fingerprint = current
                print(f"refreshed research dashboard -> {destination}", flush=True)
        except KeyboardInterrupt:
            pass
    return url
