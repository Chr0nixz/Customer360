"""Official local Baseline Agent. Uses public tools only; does not read Gold."""

from datetime import date, timedelta
from typing import Any

from customer360.agent.adapter import (
    AdapterPacket,
    Intent,
    LocalDeterministicAdapter,
    ModelAdapter,
)
from customer360.agent.protocol import AgentTools
from customer360.agent.sqlgen import PlanFilter, QueryPlan, render_sql, sql_is_unsafe
from customer360.contracts.adapter import ModelCallRecord
from customer360.contracts.public import (
    AgentError,
    AgentRequest,
    AgentResponse,
    Clarification,
    Refusal,
    Success,
)
from customer360.errors import ExecutionFailure, QueryRejected

_REFUSAL_CODES = {
    "PERMISSION_DENIED",
    "UNSAFE_SQL",
    "UNKNOWN_METRIC",
    "UNKNOWN_FIELD",
    "UNSUPPORTED_QUERY",
    "AGGREGATION_TOO_SMALL",
}


def _conversation(request: AgentRequest) -> tuple[tuple[str, str], ...]:
    return tuple((message.role, message.content) for message in request.conversation)


class BaselineAgent:
    """Official M5 baseline: retrieve → parse → plan → SQL → gateway → compose."""

    def __init__(self, adapter: ModelAdapter | None = None) -> None:
        self.adapter = adapter or LocalDeterministicAdapter()
        self.calls: list[ModelCallRecord] = []

    def respond(self, request: AgentRequest, tools: AgentTools) -> AgentResponse:
        try:
            packet = self._retrieve(request, tools)
            intent, record = self.adapter.complete(packet)
            self.calls.append(record)
        except QueryRejected as exc:
            return self._refusal(exc.code, str(exc))
        except ExecutionFailure:
            return AgentError(reason_code="TOOL_ERROR", message="元数据检索失败。")
        if intent.action == "refuse":
            return self._refusal(
                intent.reason_code or "UNSUPPORTED_QUERY",
                intent.reason or "请求被拒绝。",
                intent.alternative,
            )
        if intent.action == "clarify":
            return Clarification(
                questions=intent.questions or ("请补充缺失的查询条件。",),
                requested_slots=intent.missing_slots or ("time_window",),
            )
        try:
            metric = tools.get_metric_definition(intent.metric_name or "")
            tools.get_table_schema(str(metric["source_table"]))
            if intent.join_path:
                tools.get_table_schema("fact_transaction")
            plan = self._plan(intent, metric, request.anchor_date)
            sql = render_sql(plan)
        except QueryRejected as exc:
            return self._refusal(exc.code, str(exc))
        except (KeyError, ValueError, TypeError) as exc:
            return AgentError(reason_code="INTERNAL_ERROR", message=str(exc) or "规划失败。")
        if sql_is_unsafe(sql):
            return self._refusal("UNSAFE_SQL", "候选 SQL 未通过本地安全预检。")
        try:
            receipt = tools.execute_sql(sql)
        except QueryRejected as exc:
            return self._refusal(exc.code, str(exc))
        except ExecutionFailure:
            return AgentError(reason_code="TOOL_ERROR", message="查询执行失败。")
        evidence = (
            "official_baseline",
            f"adapter:{self.adapter.adapter_id}",
            "network_used=false",
            *intent.evidence,
            "executed_by_gateway",
        )
        return Success(
            answer="查询已通过受控工具执行；结构化结果以 query_id 对应记录为准。",
            sql=sql,
            query_id=receipt.query_id,
            confidence=1,
            evidence=evidence,
            assumptions=("local_deterministic_adapter",),
        )

    def _retrieve(self, request: AgentRequest, tools: AgentTools) -> AdapterPacket:
        metrics = tools.search_metrics("") + tools.search_metrics(request.question)
        seen: dict[str, dict[str, Any]] = {}
        for item in metrics:
            name = str(item.get("metric_name") or "")
            if name and name not in seen:
                seen[name] = item
        columns = tools.search_columns("客户等级") + tools.search_columns("地区")
        if "职业" in request.question:
            columns = columns + tools.search_columns("职业")
        joins = tools.get_join_paths("")
        glossary = tools.get_business_glossary("客户")
        return AdapterPacket(
            question=request.question,
            conversation=_conversation(request),
            anchor_date=request.anchor_date,
            metrics=tuple(seen.values()),
            columns=columns,
            joins=joins,
            glossary=glossary,
        )

    def _plan(self, intent: Intent, metric: dict[str, Any], fallback_anchor: date) -> QueryPlan:
        predicates: list[PlanFilter] = []
        for key, value in (metric.get("fixed_filters") or {}).items():
            predicates.append(PlanFilter(field=key, operator="eq", values=(value,)))
        for column in metric.get("fixed_null_columns") or ():
            predicates.append(PlanFilter(field=column, operator="is_null"))
        time_column = metric.get("time_column")
        latest_anchor = None
        join_path = intent.join_path
        if intent.time_kind == "latest_snapshot":
            latest_anchor = intent.time_date or fallback_anchor
            predicates = []
        elif intent.time_kind == "point_in_time" and time_column:
            snapshot = intent.time_date or fallback_anchor
            predicates.append(
                PlanFilter(field=str(time_column), operator="eq", values=(snapshot.isoformat(),))
            )
        elif intent.time_kind == "rolling" and intent.days and intent.time_date:
            rolling_column = "transaction_date" if join_path else time_column
            if not rolling_column:
                raise ValueError("rolling query needs a time column")
            start = intent.time_date - timedelta(days=intent.days - 1)
            end = intent.time_date
            start_filter = PlanFilter(
                field=str(rolling_column),
                operator="gte",
                values=(start.isoformat(),),
                alias="t" if join_path else None,
            )
            end_filter = PlanFilter(
                field=str(rolling_column),
                operator="lte",
                values=(end.isoformat(),),
                alias="t" if join_path else None,
            )
            predicates.extend((start_filter, end_filter))
        allowed = set(metric.get("allowed_filter_columns") or ())
        for item in intent.filters:
            alias = None
            if join_path:
                alias = "t" if item.side == "join" else "c"
            if (
                item.side == "metric"
                and item.field not in allowed
                and item.field
                not in {
                    *(metric.get("fixed_filters") or {}),
                }
            ):
                if item.field not in allowed:
                    raise ValueError(f"filter is not allowed: {item.field}")
            predicates.append(
                PlanFilter(
                    field=item.field,
                    operator=item.operator,
                    values=item.values,
                    alias=alias,
                )
            )
        if join_path:
            predicates = [
                item
                for item in predicates
                if not (item.alias is None and item.field in (metric.get("fixed_filters") or {}))
            ]
            rebuilt: list[PlanFilter] = []
            for item in predicates:
                if item.alias:
                    rebuilt.append(item)
                else:
                    rebuilt.append(
                        PlanFilter(
                            field=item.field,
                            operator=item.operator,
                            values=item.values,
                            alias="c",
                        )
                    )
            predicates = rebuilt
        return QueryPlan(
            source_table=str(metric["source_table"]),
            operation=str(metric["operation"]),
            measure_column=str(metric["measure_column"]),
            output_column=str(metric["output_column"]),
            predicates=tuple(predicates),
            time_column=str(time_column) if time_column else None,
            latest_anchor=latest_anchor,
            join_path=join_path,
            group_by=intent.group_by,
        )

    def _refusal(
        self, code: str, reason: str, alternative: str | None = None
    ) -> Refusal | AgentError:
        if code in _REFUSAL_CODES:
            return Refusal(
                reason_code=code,  # type: ignore[arg-type]
                reason=reason,
                alternative=alternative or "请使用授权范围内、受支持的聚合查询。",
            )
        return AgentError(reason_code="UNSUPPORTED_REQUEST", message=reason)
