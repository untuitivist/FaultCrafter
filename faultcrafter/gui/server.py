from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from typing import Any
from urllib.parse import parse_qs, urlsplit
import webbrowser

from faultcrafter.services.application import RuntimeApplication
from faultcrafter.services.paths import package_root


class WebApplication(RuntimeApplication):
    def __init__(self, *arguments: Any, **keywords: Any) -> None:
        super().__init__(*arguments, **keywords)
        assets = package_root() / "gui/assets"
        self.html = (assets / "faultcrafter-jit-deployment.html").read_bytes()
        self.javascript = (assets / "deployment-app.js").read_bytes()
        self.unit_javascript = (assets / "condition-units.js").read_bytes()
        self.onboarding_html = (assets / "device-onboarding.html").read_bytes()
        self.onboarding_javascript = (assets / "device-onboarding.js").read_bytes()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FaultCrafter local browser GUI")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--model-root", "--compact-root", dest="compact_root", type=Path)
    parser.add_argument("--compute-device", choices=("cpu", "cuda"))
    parser.add_argument("--user-data-root", type=Path)
    return parser.parse_args(argv)

def handler_for(application: WebApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "FaultCrafterJiT/1.1"

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
            self._send(status, body, "application/json; charset=utf-8")

        def _read_json(self, maximum_size: int = 1_048_576) -> dict[str, Any]:
            content_length = int(self.headers.get("Content-Length", "0"))
            if not 0 < content_length <= maximum_size:
                raise ValueError("invalid request size")
            value = json.loads(self.rfile.read(content_length).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("request body must be an object")
            return value

        def _send_file(self, path: Path, download_name: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(path.stat().st_size))
            self.send_header(
                "Content-Disposition", f'attachment; filename="{download_name}"'
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            with path.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    self.wfile.write(block)

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.path in {"/", "/index.html"}:
                self._send(200, application.html, "text/html; charset=utf-8")
            elif parsed.path == "/deployment-app.js":
                self._send(
                    200,
                    application.javascript,
                    "text/javascript; charset=utf-8",
                )
            elif parsed.path == "/condition-units.js":
                self._send(200, application.unit_javascript, "text/javascript; charset=utf-8")
            elif parsed.path == "/onboarding":
                self._send(200, application.onboarding_html, "text/html; charset=utf-8")
            elif parsed.path == "/device-onboarding.js":
                self._send(200, application.onboarding_javascript, "text/javascript; charset=utf-8")
            elif parsed.path in {"/api/devices/jobs", "/api/devices/status", "/api/devices/download"}:
                try:
                    manager = application.device_jobs()
                    query = parse_qs(parsed.query)
                    if parsed.path.endswith("/jobs"):
                        self._json(200, {"jobs": manager.list_jobs()})
                    elif parsed.path.endswith("/status"):
                        self._json(200, manager.status(query["job_id"][0], wait=float(query.get("wait", [0])[0])))
                    else:
                        path, name = manager.archive(query["job_id"][0])
                        self._send_file(path, name)
                except (KeyError, IndexError, ValueError, RuntimeError) as error:
                    self._json(400, {"error": str(error)})
            elif parsed.path == "/api/manifest":
                self._json(200, application.public_manifest())
            elif parsed.path == "/api/health":
                self._json(200, {"ok": True, "model_id": application.manifest.model_id})
            elif parsed.path == "/api/batch/status":
                try:
                    job_id = parse_qs(parsed.query)["job_id"][0]
                    self._json(200, application.batch_jobs.status(job_id))
                except (KeyError, IndexError, ValueError) as error:
                    self._json(400, {"error": str(error)})
            elif parsed.path == "/api/batch/download":
                try:
                    job_id = parse_qs(parsed.query)["job_id"][0]
                    path, name = application.batch_jobs.archive(job_id)
                    self._send_file(path, name)
                except (KeyError, IndexError, ValueError, RuntimeError) as error:
                    self._json(400, {"error": str(error)})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            parsed = urlsplit(self.path)
            origin = self.headers.get("Origin")
            if origin is not None and origin != f"http://{self.headers.get('Host')}":
                self._json(403, {"error": "只接受本地应用页面发起的操作"})
                return
            if parsed.path.startswith("/api/devices/"):
                try:
                    manager = application.device_jobs()
                    if parsed.path == "/api/devices/upload":
                        query = parse_qs(parsed.query)
                        self._json(200, manager.upload(query["job_id"][0], query["file"][0], self.rfile,
                                                      int(self.headers.get("Content-Length", "0"))))
                        return
                    payload = self._read_json()
                    if parsed.path == "/api/devices/create":
                        result = manager.create(payload)
                    elif parsed.path == "/api/devices/validate":
                        result = manager.validate(payload["job_id"])
                    elif parsed.path == "/api/devices/train":
                        if application.batch_jobs.has_active_job():
                            raise ValueError("请先完成正在进行的批量生成")
                        result = manager.start(payload["job_id"])
                    else:
                        self._json(404, {"error": "not found"})
                        return
                    self._json(200, result)
                except (KeyError, IndexError, TypeError, ValueError, RuntimeError, OSError) as error:
                    self.close_connection = True
                    self._json(400, {"error": str(error)})
                except Exception as error:
                    self.close_connection = True
                    self._json(500, {"error": f"device onboarding failed: {error}"})
                return
            if parsed.path == "/api/shutdown":
                if application.batch_jobs.has_active_job() or (application.onboarding is not None and application.onboarding.has_active_job()):
                    self._json(409, {"error": "批量任务仍在运行，完成后才能退出应用。"})
                    return
                self._json(200, {"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if parsed.path not in {"/api/generate", "/api/batch/start"}:
                self._json(404, {"error": "not found"})
                return
            try:
                payload = self._read_json()
                if parsed.path == "/api/generate":
                    self._json(200, application.generate(payload))
                else:
                    self._json(202, application.start_batch(payload))
            except (KeyError, TypeError, ValueError, RuntimeError) as error:
                self._json(400, {"error": str(error)})
            except Exception as error:
                self._json(500, {"error": f"internal inference error: {error}"})

        def log_message(self, message: str, *args: Any) -> None:
            print(f"web {self.address_string()} {message % args}", flush=True)

    return Handler


def self_test(application: RuntimeApplication) -> None:
    reports = []
    for route in application.manifest.devices:
        payload = {
            "device_id": route.id,
            "fault_id": route.faults[0].id,
            "condition_parameters": {
                control.name: control.initial for control in route.parameters
            },
            "length": int(application.manifest.runtime["minimum_length"]),
            "seed": 42 + route.index,
        }
        result = application.generate(payload)
        reports.append(
            {
                "device_id": result["device_id"],
                "length": len(result["physical_signal"]),
                "finite": all(
                    value == value and abs(value) != float("inf")
                    for value in result["physical_signal"]
                ),
            }
        )
    print(
        json.dumps(
            {
                "ok": True,
                "routes": reports,
                "compute_device": result["compute_device"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    application = WebApplication(args.compact_root, compute_device=args.compute_device, user_data_root=args.user_data_root)
    if args.self_test:
        self_test(application)
        return
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(application))
    except OSError:
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(application))
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"FaultCrafter JiT Web: {url}", flush=True)
    print(f"Model: {application.manifest.model_id} ({application.compact_root})", flush=True)
    if not args.no_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
