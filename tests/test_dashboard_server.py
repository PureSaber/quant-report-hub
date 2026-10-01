from __future__ import annotations

import functools
import threading
from http.client import HTTPConnection

import pytest

from quant_report_hub.dashboard_server import (
    DashboardHandler,
    DashboardHTTPServer,
    published_files,
    serve_dashboard,
)


@pytest.fixture
def publication(tmp_path):
    run = tmp_path / "decisions" / "run-1"
    run.mkdir(parents=True)
    decision = run / "decision.json"
    decision.write_text('{"scope":"paper_simulation_only"}', encoding="utf-8")
    dashboard = tmp_path / "reports" / "dashboard.html"
    dashboard.parent.mkdir()
    dashboard.write_text("<h1>Research</h1>", encoding="utf-8")
    status = dashboard.with_suffix(".html.status.json")
    status.write_text('{"build_id":"one"}', encoding="utf-8")
    snapshot = {
        "sources": [{"root": str(run.parent), "current": {"path": str(decision)}, "history": []}],
        "experiments": [],
    }
    return dashboard, status, decision, snapshot


@pytest.fixture
def http_server(tmp_path, publication):
    dashboard, status, _, snapshot = publication
    handler = functools.partial(DashboardHandler, directory=str(tmp_path))
    with DashboardHTTPServer(("127.0.0.1", 0), handler) as server:
        server.published_files = published_files(snapshot, dashboard, [status])
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=5)


def request(server, path, *, method="GET", hosts=None):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.putrequest(method, path, skip_host=True)
        for host in hosts if hosts is not None else [f"127.0.0.1:{server.server_port}"]:
            connection.putheader("Host", host)
        connection.endheaders()
        response = connection.getresponse()
        return response.status, response.read(), dict(response.getheaders())
    finally:
        connection.close()


def test_dashboard_status_and_explicit_evidence_remain_accessible(http_server):
    for path in (
        "/reports/dashboard.html",
        "/reports/dashboard.html.status.json?refresh=1",
        "/decisions/run-1/decision.json",
    ):
        status, body, headers = request(http_server, path)
        assert status == 200
        assert body
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert request(http_server, "/reports/dashboard.html", method="HEAD")[:2] == (200, b"")
    assert (
        request(
            http_server, "/reports/dashboard.html", hosts=[f"localhost:{http_server.server_port}"]
        )[0]
        == 200
    )


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_common_parent_does_not_publish_other_files(http_server, tmp_path, method):
    for relative in ("secrets.txt", "reports/experiments.db", "decisions/run-1/private.txt"):
        (tmp_path / relative).write_text("private", encoding="utf-8")
        assert request(http_server, "/" + relative, method=method)[0] == 404
    for path in ("/", "/reports/", "/decisions/", "/reports/%2e%2e/secrets.txt"):
        assert request(http_server, path, method=method)[0] == 404


@pytest.mark.parametrize(
    "hosts", [[], ["untrusted.invalid"], ["localhost:1"], ["localhost:80", "untrusted.invalid"]]
)
def test_missing_spoofed_or_duplicate_host_is_rejected(http_server, hosts):
    assert request(http_server, "/reports/dashboard.html", hosts=hosts)[0] == 403


def test_replaced_evidence_symlink_is_rejected(http_server, publication, tmp_path):
    _, _, decision, _ = publication
    secret = tmp_path / "secret.json"
    secret.write_text('"private"', encoding="utf-8")
    decision.unlink()
    try:
        decision.symlink_to(secret)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this host")
    assert request(http_server, "/decisions/run-1/decision.json")[0] == 404


def test_only_indexed_evidence_is_published_and_refresh_removes_old_runs(publication, tmp_path):
    dashboard, status, decision, snapshot = publication
    indexed = tmp_path / "indexed"
    indexed.mkdir()
    experiment = indexed / "experiment.json"
    experiment.write_text("{}", encoding="utf-8")
    private = indexed / "private.json"
    private.write_text("{}", encoding="utf-8")
    snapshot["experiments"] = [{"run_path": str(indexed)}]
    paths = published_files(snapshot, dashboard, [status])
    assert {dashboard, status, decision, experiment} == paths
    snapshot["sources"] = []
    assert decision not in published_files(snapshot, dashboard, [status])
    snapshot["sources"] = [
        {"root": str(tmp_path / "elsewhere"), "current": {"path": str(decision)}, "history": []}
    ]
    assert decision not in published_files(snapshot, dashboard, [status])


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "example.com", "192.168.1.1"])
def test_network_binding_is_rejected_before_writing(tmp_path, host):
    out = tmp_path / "dashboard.html"
    with pytest.raises(ValueError, match="host must be"):
        serve_dashboard([], out, host=host)
    assert not out.exists()
