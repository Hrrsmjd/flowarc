"""Serve the web dashboard and its state: `python -m flowarc.dashboard [--mock] [--port 8000]`.

GET  /api/state    run progress, samples with logs, diversity map, approvals
POST /api/approve  {"id": ..., "decision": "approved" | "rejected"}

With --mock, or when the registry is empty, the state comes from flowarc.mock.
"""

import argparse
import json
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

from flowarc import config, mock
from flowarc.sample import all_samples

WEB = Path(__file__).resolve().parent.parent / "web"


def _read_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def _log(sample_dir: Path) -> list[dict]:
    path = sample_dir / "log.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def live_state() -> dict | None:
    samples = all_samples()
    if not samples:
        return None
    rows = []
    for s in samples:
        rows.append(
            {
                "id": s.id,
                "title": s.concept.get("name") or s.concept.get("description", s.id),
                "bucket": s.concept.get("bucket", "unknown"),
                "stage": s.stage,
                "status": s.status,
                "concept": s.concept,
                "attempts": s.attempts,
                "gpu": s.meta.get("gpu"),
                "log": _log(s.dir),
                "convergence": s.meta.get("convergence"),
                "gpu_seconds": s.meta.get("gpu_seconds", 0),
            }
        )
    logs = [e["t"] for r in rows for e in r["log"]]
    started = min(logs) if logs else time.time()
    hours = max((time.time() - started) / 3600, 1e-6)
    done = sum(r["status"] == "done" for r in rows)
    return {
        "mode": "live",
        "generated_at": time.time(),
        "run": {
            "phase": config.PHASE.name,
            "cells_per_length": list(config.PHASE.cells_per_length),
            "target_samples": config.PHASE.max_samples,
            "started_at": started,
            "gpus": len(config.GPUS),
            "samples_per_hour": round(done / hours, 2),
            "gpu_hours": round(sum(r["gpu_seconds"] for r in rows) / 3600, 2),
            "featured": rows[-1]["id"],
        },
        "samples": rows,
        "diversity": _read_json(config.DATA / "diversity.json", {"points": []}),
        "approvals": _read_json(config.DATA / "approvals.json", []),
    }


class Handler(SimpleHTTPRequestHandler):
    use_mock = False
    mock_approvals: ClassVar[dict] = {}

    def _send(self, body: dict, code: int = 200) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _state(self) -> dict:
        st = None if self.use_mock else live_state()
        if st is None:
            st = mock.state()
            for a in st["approvals"]:
                a.update(self.mock_approvals.get(a["id"], {}))
        return st

    def do_GET(self):
        if self.path.split("?")[0] == "/api/state":
            return self._send(self._state())
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/approve":
            return self._send({"error": "not found"}, 404)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if body.get("decision") not in ("approved", "rejected"):
            return self._send({"error": "decision must be approved or rejected"}, 400)
        update = {"status": body["decision"], "decided_at": time.time()}
        st = self._state()
        if st["mode"] == "mock":
            self.mock_approvals[body.get("id")] = update
        else:
            path = config.DATA / "approvals.json"
            approvals = _read_json(path, [])
            for a in approvals:
                if a["id"] == body.get("id"):
                    a.update(update)
            path.write_text(json.dumps(approvals, indent=2))
        return self._send({"ok": True, **update})


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--mock", action="store_true", help="always serve mock data")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--write-mock", type=Path, help="write the mock state to this file and exit")
    args = p.parse_args()
    if args.write_mock:
        args.write_mock.write_text(json.dumps(mock.state(now=1792800000.0), indent=1))
        return
    Handler.use_mock = args.mock
    server = ThreadingHTTPServer(("", args.port), partial(Handler, directory=str(WEB)))
    print(f"dashboard on http://localhost:{args.port} ({'mock' if args.mock else 'registry'})")
    server.serve_forever()


if __name__ == "__main__":
    main()
