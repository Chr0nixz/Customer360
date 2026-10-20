"""Local offline model adapter. Connects only to local loopback inference endpoints.

Strictly blocks non-localhost addresses; no external network traffic permitted.
"""

from __future__ import annotations

import importlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from customer360.agent.adapter import (
    AdapterPacket,
    Intent,
    IntentFilter,
    ModelAdapter,
    _digest,
)
from customer360.agent.baseline import BaselineAgent
from customer360.contracts.adapter import AdapterParameters, ModelCallRecord

ALLOWED_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})
DEFAULT_LOCAL_ENDPOINT = "http://127.0.0.1:11434/v1"
DEFAULT_LOCAL_MODEL = "local-model"


def assert_local_endpoint(endpoint_url: str) -> None:
    """Validate that the given endpoint resolves strictly to local loopback."""
    urllib_parse = importlib.import_module("urllib.parse")
    parsed = urllib_parse.urlparse(endpoint_url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise ValueError(
            f"Invalid URL scheme: '{scheme}'. Only http/https local loopback endpoints permitted."
        )
    hostname = (parsed.hostname or "").lower()
    if not hostname or hostname not in ALLOWED_LOCAL_HOSTS:
        raise ValueError(
            f"External network connection prohibited: '{hostname}' is not in local loopback "
            f"whitelist {sorted(ALLOWED_LOCAL_HOSTS)}. External models are strictly fail-closed."
        )


SYSTEM_PROMPT = """你是一个专业的金融客户360度数据分析助手。
你只能通过调用受控只读工具或结构化回答来服务用户。
请根据用户问题、对话历史、锚点日期以及提供的公开指标和关联路径元数据，决定下一步动作。

请严格输出合法的 JSON 格式，不要输出任何额外的标记或解释说明：
{
  "action": "answer" | "clarify" | "refuse",
  "metric_name": "指标名称(英文ID，若action为answer或澄清缺失时间时必须提供)",
  "reason_code": "拒绝原因码(可选PERMISSION_DENIED, UNKNOWN_FIELD, UNSUPPORTED_QUERY)",
  "reason": "拒绝原因说明(若action为refuse)",
  "alternative": "合规替代方案说明(若action为refuse)",
  "missing_slots": ["缺失槽位列表，如 time_window(若action为clarify)"],
  "questions": ["向用户提出的澄清问题(若action为clarify)"],
  "time_kind": "none" | "rolling" | "point_in_time" | "latest_snapshot",
  "days": 窗口自然天数(整数，若time_kind为rolling),
  "time_date": "时点日期(YYYY-MM-DD，若time_kind为point_in_time)",
  "join_path": "可执行关联路径名(若需要跨表统计，如 customer_transactions 等)",
  "group_by": ["分组维度列名，如 region, customer_level 等(必须为指标允许的分组维度)"],
  "filters": [
    {
      "field": "字段名",
      "operator": "eq" | "neq" | "gt" | "gte" | "lt" | "lte" | "in" | "is_null",
      "values": ["条件取值列表"]
    }
  ]
}

安全与业务红线：
1. 涉及手机号、身份证等敏感字段，必须选择 action="refuse", reason_code="UNKNOWN_FIELD"；
2. 指标需要时间窗口但用户未提供明确天数，选 action="clarify", missing_slots=["time_window"]；
3. 单客 ID（如 customer_id）严禁作为 group_by 维度；
4. 只能从提供的候选指标中选择最匹配的一个。
"""


def _build_user_prompt(packet: AdapterPacket) -> str:
    payload = {
        "question": packet.question,
        "anchor_date": packet.anchor_date.isoformat(),
        "conversation_history": [
            {"role": role, "content": content} for role, content in packet.conversation
        ],
        "candidate_metrics": [
            {
                "metric_name": m.get("metric_name"),
                "business_name": m.get("business_name"),
                "time_semantics": m.get("time_semantics"),
                "source_table": m.get("source_table"),
                "allowed_group_dimensions": m.get("allowed_group_dimensions"),
                "allowed_filter_columns": m.get("allowed_filter_columns"),
                "fixed_filters": m.get("fixed_filters"),
                "definition": m.get("definition"),
            }
            for m in packet.metrics[:15]
        ],
        "available_join_paths": [
            {
                "path_name": j.get("path_name"),
                "target_table": j.get("target_table"),
                "description": j.get("description"),
            }
            for j in packet.joins
            if j.get("compile_status") == "executable"
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@dataclass
class LocalModelConfig:
    endpoint: str = DEFAULT_LOCAL_ENDPOINT
    model: str = DEFAULT_LOCAL_MODEL
    temperature: float = 0.0
    timeout: float = 30.0
    seed: int = 42


class LocalModelAdapter(ModelAdapter):
    """Offline adapter invoking a local OpenAI-compatible inference server."""

    adapter_id = "local_model"
    provider = "local"

    def __init__(
        self,
        config: LocalModelConfig | None = None,
        *,
        http_poster: Callable[[str, dict[str, Any], float], str] | None = None,
    ) -> None:
        self.config = config or LocalModelConfig()
        self.model = self.config.model
        assert_local_endpoint(self.config.endpoint)
        self._http_poster = http_poster or self._default_post

    def complete(self, packet: AdapterPacket) -> tuple[Intent, ModelCallRecord]:
        t0 = perf_counter()
        digest_val = _digest(packet)
        params = AdapterParameters(
            temperature=self.config.temperature,
            top_p=1.0,
            seed=self.config.seed,
            max_output_tokens=1024,
            max_retries=1,
        )

        user_content = _build_user_prompt(packet)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        request_body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "seed": self.config.seed,
        }

        url = self.config.endpoint.rstrip("/") + "/chat/completions"
        try:
            raw_response = self._http_poster(url, request_body, self.config.timeout)
            intent = self._parse_response(raw_response, packet)
            elapsed_ms = (perf_counter() - t0) * 1000
            record = ModelCallRecord(
                adapter_id=self.adapter_id,
                provider=self.provider,
                model=self.model,
                network_used=False,  # strictly local loopback
                cache_hit=False,
                retry_count=0,
                elapsed_ms=round(elapsed_ms, 2),
                prompt_digest=digest_val,
                parameters=params,
                outcome="intent",
            )
            return intent, record
        except Exception:
            elapsed_ms = (perf_counter() - t0) * 1000
            fallback_intent = Intent(
                action="refuse",
                reason_code="UNSUPPORTED_QUERY",
                reason="本地模型推理失败或无法解析模型返回。",
                alternative="请检查本地推理服务连接或查询语义复杂度。",
            )
            record = ModelCallRecord(
                adapter_id=self.adapter_id,
                provider=self.provider,
                model=self.model,
                network_used=False,
                cache_hit=False,
                retry_count=0,
                elapsed_ms=round(elapsed_ms, 2),
                prompt_digest=digest_val,
                parameters=params,
                outcome="error",
            )
            return fallback_intent, record

    def _default_post(self, url: str, body: dict[str, Any], timeout: float) -> str:
        assert_local_endpoint(url)
        urllib_request = importlib.import_module("urllib.request")

        class SafeLocalRedirectHandler(urllib_request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                assert_local_endpoint(newurl)
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        opener = urllib_request.build_opener(SafeLocalRedirectHandler)
        data = json.dumps(body).encode("utf-8")
        req = urllib_request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Connection": "close",
                "User-Agent": "Customer360-LocalModel",
            },
        )
        with opener.open(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")

    def _parse_response(self, raw_text: str, packet: AdapterPacket) -> Intent:
        # Extract assistant message content
        parsed = json.loads(raw_text)
        content = ""
        if "choices" in parsed and parsed["choices"]:
            choice = parsed["choices"][0]
            message = choice.get("message", {})
            content = message.get("content", "")
        elif "response" in parsed:
            content = parsed["response"]
        else:
            content = raw_text

        # Extract JSON code block or direct JSON
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
        json_str = json_match.group(1) if json_match else content.strip()
        data = json.loads(json_str)

        action = str(data.get("action", "refuse")).lower()
        if action == "refuse":
            return Intent(
                action="refuse",
                reason_code=data.get("reason_code", "UNSUPPORTED_QUERY"),
                reason=data.get("reason", "请求被拒绝。"),
                alternative=data.get("alternative"),
            )
        if action == "clarify":
            missing = tuple(data.get("missing_slots") or ("time_window",))
            questions = tuple(data.get("questions") or ("请补充缺失的查询条件。",))
            return Intent(
                action="clarify",
                metric_name=data.get("metric_name"),
                missing_slots=missing,
                questions=questions,
            )

        # Action: answer
        metric_name = data.get("metric_name")
        filters_list = []
        for f in data.get("filters") or ():
            if isinstance(f, dict) and "field" in f and "operator" in f:
                filters_list.append(
                    IntentFilter(
                        field=str(f["field"]),
                        operator=str(f["operator"]),
                        values=tuple(f.get("values", ())),
                    )
                )

        # Pre-execution defense: discard single customer identifiers from group_by
        forbidden_groups = frozenset({"customer_id", "id", "cust_id", "customer_name"})
        group_by = tuple(
            str(g) for g in data.get("group_by") or () if str(g).lower() not in forbidden_groups
        )

        # Parse time_date into datetime.date object if it's a string,
        # or fallback to packet anchor_date
        time_date_val = data.get("time_date")
        from datetime import date

        if isinstance(time_date_val, str) and time_date_val:
            try:
                time_date_obj = date.fromisoformat(time_date_val)
            except ValueError:
                time_date_obj = packet.anchor_date
        elif isinstance(time_date_val, date):
            time_date_obj = time_date_val
        else:
            time_date_obj = packet.anchor_date

        return Intent(
            action="answer",
            metric_name=metric_name,
            filters=tuple(filters_list),
            time_kind=data.get("time_kind", "none"),
            days=data.get("days"),
            time_date=time_date_obj,
            join_path=data.get("join_path"),
            group_by=group_by,
            evidence=("local_model", self.model),
        )


def create_local_model_agent(
    endpoint: str = DEFAULT_LOCAL_ENDPOINT,
    model: str = DEFAULT_LOCAL_MODEL,
    *,
    http_poster: Callable[[str, dict[str, Any], float], str] | None = None,
) -> BaselineAgent:
    """Create a BaselineAgent configured with a local loopback model adapter."""
    config = LocalModelConfig(endpoint=endpoint, model=model)
    adapter = LocalModelAdapter(config, http_poster=http_poster)
    return BaselineAgent(adapter=adapter)
