"""Local mock inference server for offline OpenAI-compatible benchmarking and testing.

Runs strictly on local loopback (127.0.0.1). Never initiates or forwards external network traffic.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from customer360.agent.adapter import (
    AdapterPacket,
    LocalDeterministicAdapter,
)
from customer360.agent.local_model import assert_local_endpoint


class _MockOpenAIHandler(BaseHTTPRequestHandler):
    """Handler implementing OpenAI-compatible /v1/chat/completions over loopback."""

    server_version = "Customer360-LocalMock/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy standard HTTP access logs unless quiet is False
        server: LocalInferenceServer = getattr(self.server, "app_server", None)
        if server and not server.quiet:
            super().log_message(format, *args)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def do_GET(self) -> None:
        if self.path in {"/health", "/healthz"}:
            self._send_json(200, {"status": "ok", "service": "c360-local-mock"})
        elif self.path in {"/v1/models", "/models"}:
            server: LocalInferenceServer = getattr(self.server, "app_server", None)
            model_name = server.model if server else "local-model"
            self._send_json(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": model_name,
                            "object": "model",
                            "created": int(time.time()),
                            "owned_by": "customer360-local",
                        }
                    ],
                },
            )
        else:
            self._send_json(404, {"error": f"Not found: {self.path}"})

    def do_POST(self) -> None:
        if self.path not in {"/v1/chat/completions", "/chat/completions"}:
            self._send_json(404, {"error": f"Unknown endpoint: {self.path}"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length).decode("utf-8")
        try:
            req_data = json.loads(raw_body)
        except Exception:
            self._send_json(400, {"error": "Invalid JSON body"})
            return

        server: LocalInferenceServer = getattr(self.server, "app_server", None)
        if server and server.simulated_latency_s > 0:
            time.sleep(server.simulated_latency_s)

        if server and server.force_error:
            self._send_json(500, {"error": "Simulated local inference service error"})
            return

        # Extract user content
        messages = req_data.get("messages", [])
        user_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_content = msg.get("content", "")
                break

        intent_dict = self._resolve_intent_dict(user_content)
        json_content = json.dumps(intent_dict, ensure_ascii=False, indent=2)
        assistant_text = f"```json\n{json_content}\n```"

        model_name = req_data.get("model") or (server.model if server else "local-model")
        response_payload = {
            "id": f"chatcmpl-mock-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": assistant_text,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": len(user_content.split()),
                "completion_tokens": len(assistant_text.split()),
                "total_tokens": len(user_content.split()) + len(assistant_text.split()),
            },
        }
        self._send_json(200, response_payload)

    def _resolve_intent_dict(self, user_content: str) -> dict[str, Any]:
        """Parse the structured packet JSON in user_content and compute the intent."""
        try:
            payload = json.loads(user_content)
        except Exception:
            payload = {"question": user_content, "anchor_date": "2025-06-30"}

        if not isinstance(payload, dict):
            payload = {"question": str(user_content), "anchor_date": "2025-06-30"}

        question = str(payload.get("question") or "")
        anchor_str = str(payload.get("anchor_date") or "2025-06-30")
        try:
            anchor_date = date.fromisoformat(anchor_str)
        except Exception:
            anchor_date = date(2025, 6, 30)

        history_items = []
        raw_history = payload.get("conversation_history")
        if isinstance(raw_history, list):
            for h in raw_history:
                if isinstance(h, dict):
                    role = h.get("role", "user")
                    content = h.get("content", "")
                    history_items.append((role, content))

        raw_metrics = payload.get("candidate_metrics")
        candidate_metrics = (
            tuple(m for m in raw_metrics if isinstance(m, dict))
            if isinstance(raw_metrics, list)
            else ()
        )

        raw_joins = payload.get("available_join_paths")
        available_joins = (
            tuple(j for j in raw_joins if isinstance(j, dict))
            if isinstance(raw_joins, list)
            else ()
        )

        packet = AdapterPacket(
            question=question,
            conversation=tuple(history_items),
            anchor_date=anchor_date,
            metrics=candidate_metrics,
            columns=(),
            joins=available_joins,
            glossary=(),
        )

        planner = LocalDeterministicAdapter()
        intent = planner._parse(packet)

        # Serialize Intent to match LocalModelAdapter expected JSON schema
        out: dict[str, Any] = {
            "action": intent.action,
            "metric_name": intent.metric_name,
        }
        if intent.action == "refuse":
            out["reason_code"] = intent.reason_code or "UNSUPPORTED_QUERY"
            out["reason"] = intent.reason or "请求被拒绝。"
            out["alternative"] = intent.alternative
        elif intent.action == "clarify":
            out["missing_slots"] = list(intent.missing_slots)
            out["questions"] = list(intent.questions)
        else:  # answer
            out["time_kind"] = intent.time_kind or "none"
            if intent.days is not None:
                out["days"] = intent.days
            if intent.time_date is not None:
                out["time_date"] = intent.time_date.isoformat()
            if intent.join_path:
                out["join_path"] = intent.join_path
            if intent.group_by:
                out["group_by"] = list(intent.group_by)
            if intent.limit is not None:
                out["limit"] = intent.limit
            if intent.order_by:
                out["order_by"] = list(intent.order_by)
            if intent.order_direction:
                out["order_direction"] = intent.order_direction
            if intent.having_operator:
                out["having_operator"] = intent.having_operator
            if intent.having_threshold is not None:
                out["having_threshold"] = intent.having_threshold
            if intent.ratio_alias:
                out["ratio_alias"] = intent.ratio_alias
            filters_list = []
            for f in intent.filters:
                filters_list.append(
                    {
                        "field": f.field,
                        "operator": f.operator,
                        "values": list(f.values),
                    }
                )
            out["filters"] = filters_list

        return out

    def _send_json(self, status: int, data: dict[str, Any]) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True


class LocalInferenceServer:
    """Threaded local loopback server mimicking an OpenAI-compatible model endpoint."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        model: str = "local-model",
        *,
        quiet: bool = True,
        simulated_latency_s: float = 0.0,
        force_error: bool = False,
    ) -> None:
        assert_local_endpoint(f"http://{host}:{port or 80}/")
        self.host = host
        self.port = port
        self.model = model
        self.quiet = quiet
        self.simulated_latency_s = simulated_latency_s
        self.force_error = force_error
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.bound_port: int = port

    @property
    def endpoint_url(self) -> str:
        """Return the v1 base endpoint URL."""
        return f"http://{self.host}:{self.bound_port}/v1"

    def start(self) -> LocalInferenceServer:
        """Start the server in a daemon background thread."""
        if self._server is not None:
            return self

        self._server = ThreadingHTTPServer((self.host, self.port), _MockOpenAIHandler)
        self._server.app_server = self  # type: ignore[attr-defined]
        self.bound_port = self._server.server_port

        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        """Shut down the server cleanly."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def __enter__(self) -> LocalInferenceServer:
        return self.start()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
