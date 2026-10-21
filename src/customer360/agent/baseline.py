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
                right_table = {
                    "customer_transactions": "fact_transaction",
                    "customer_cash_flows": "fact_cash_flow",
                    "customer_holdings": "fact_holding",
                    "customer_asset_snapshots": "fact_asset_snapshot",
                    "customer_service_relations": "fact_service_relation",
                    "customer_transactions_and_holdings": "fact_transaction",
                }.get(intent.join_path, "fact_transaction")
                tools.get_table_schema(right_table)
                if intent.join_path == "customer_transactions_and_holdings":
                    tools.get_table_schema("fact_holding")
            plan = self._plan(intent, metric, request.anchor_date)
            # Pre-execution validation check
            plan_payload = {
                "source_table": plan.source_table,
                "operation": plan.operation,
                "measure_column": plan.measure_column,
                "output_column": plan.output_column,
                "predicates": [
                    {
                        "field": p.field,
                        "operator": p.operator,
                        "values": list(p.values),
                        "alias": p.alias,
                    }
                    for p in plan.predicates
                ],
                "join_path": plan.join_path,
                "group_by": list(plan.group_by),
                "time_column": plan.time_column,
            }
            if plan.join_path != "customer_transactions_and_holdings" and not plan.ratio_alias:
                val_res = tools.validate_query_plan(plan_payload)
                if not isinstance(val_res, dict) or not val_res.get("is_valid", False):
                    issues = val_res.get("issues", []) if isinstance(val_res, dict) else []
                    primary = issues[0] if issues else {}
                    msg = primary.get("message", "查询计划未通过受控校验。")
                    return self._refusal("UNSUPPORTED_QUERY", msg)

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
        for token, kw in (
            ("职业", "职业"),
            ("风险", "风险等级"),
            ("性别", "性别"),
            ("渠道", "交易渠道"),
            ("交易类型", "交易类型"),
            ("资金流", "资金流类型"),
        ):
            if token in request.question:
                columns = columns + tools.search_columns(kw)
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
        join_path = intent.join_path
        if join_path == "customer_transactions_and_holdings":
            composite_predicates: list[PlanFilter] = [
                PlanFilter(field="status", operator="eq", values=("success",), alias="t"),
                PlanFilter(field="holding_status", operator="eq", values=("active",), alias="h"),
                PlanFilter(
                    field="snapshot_date",
                    operator="eq",
                    values=(fallback_anchor.isoformat(),),
                    alias="h",
                ),
            ]
            if intent.time_kind == "rolling" and intent.days:
                anchor = intent.time_date or fallback_anchor
                start = anchor - timedelta(days=intent.days - 1)
                composite_predicates.extend(
                    [
                        PlanFilter(
                            field="transaction_date",
                            operator="gte",
                            values=(start.isoformat(),),
                            alias="t",
                        ),
                        PlanFilter(
                            field="transaction_date",
                            operator="lte",
                            values=(anchor.isoformat(),),
                            alias="t",
                        ),
                    ]
                )
            for item in intent.filters:
                if item.field in {"region", "customer_level", "risk_level", "gender"}:
                    composite_predicates.append(
                        PlanFilter(
                            field=item.field,
                            operator=item.operator,
                            values=item.values,
                            alias="c",
                        )
                    )
                elif item.field == "product_id":
                    composite_predicates.append(
                        PlanFilter(
                            field="product_id",
                            operator=item.operator,
                            values=item.values,
                            alias="t",
                        )
                    )
                    composite_predicates.append(
                        PlanFilter(
                            field="product_id",
                            operator=item.operator,
                            values=item.values,
                            alias="h",
                        )
                    )
            return QueryPlan(
                source_table="dim_customer",
                operation="count_distinct",
                measure_column="customer_id",
                output_column=str(metric["output_column"]),
                predicates=tuple(composite_predicates),
                join_path="customer_transactions_and_holdings",
            )

        predicates: list[PlanFilter] = []
        for key, value in (metric.get("fixed_filters") or {}).items():
            predicates.append(PlanFilter(field=key, operator="eq", values=(value,)))
        for column in metric.get("fixed_null_columns") or ():
            predicates.append(PlanFilter(field=column, operator="is_null"))
        time_column = metric.get("time_column")
        latest_anchor = None
        join_alias = "t"
        if join_path:
            join_alias = {
                "customer_transactions": "t",
                "customer_cash_flows": "cf",
                "customer_holdings": "h",
                "customer_asset_snapshots": "a",
                "customer_service_relations": "sr",
            }.get(join_path, "t")
        if intent.time_kind == "latest_snapshot":
            latest_anchor = intent.time_date or fallback_anchor
            predicates = []
        elif intent.time_kind == "point_in_time" and (
            time_column or join_path in {"customer_holdings", "customer_asset_snapshots"}
        ):
            snapshot = intent.time_date or fallback_anchor
            pit_col = str(time_column or "snapshot_date")
            predicates.append(
                PlanFilter(
                    field=pit_col,
                    operator="eq",
                    values=(snapshot.isoformat(),),
                    alias=join_alias if join_path else None,
                )
            )
        elif intent.time_kind == "rolling" and intent.days and intent.time_date:
            rolling_column = time_column
            if join_path:
                if join_path == "customer_transactions":
                    rolling_column = "transaction_date"
                elif join_path == "customer_cash_flows":
                    rolling_column = "flow_date"
            if not rolling_column:
                raise ValueError("rolling query needs a time column")
            start = intent.time_date - timedelta(days=intent.days - 1)
            end = intent.time_date
            start_filter = PlanFilter(
                field=str(rolling_column),
                operator="gte",
                values=(start.isoformat(),),
                alias=join_alias if join_path else None,
            )
            end_filter = PlanFilter(
                field=str(rolling_column),
                operator="lte",
                values=(end.isoformat(),),
                alias=join_alias if join_path else None,
            )
            predicates.extend((start_filter, end_filter))
        allowed = set(metric.get("allowed_filter_columns") or ())
        for item in intent.filters:
            alias = None
            if join_path:
                alias = join_alias if item.side == "join" else "c"
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
        output_col = intent.ratio_alias or str(metric["output_column"])
        return QueryPlan(
            source_table=str(metric["source_table"]),
            operation=str(metric["operation"]),
            measure_column=str(metric["measure_column"]),
            output_column=output_col,
            predicates=tuple(predicates),
            time_column=str(time_column) if time_column else None,
            latest_anchor=latest_anchor,
            join_path=join_path,
            group_by=intent.group_by,
            limit=intent.limit,
            order_by=intent.order_by,
            order_direction=intent.order_direction,
            having_operator=intent.having_operator,
            having_threshold=intent.having_threshold,
            ratio_alias=intent.ratio_alias,
        )

    def _refusal(
        self, code: str, reason: str, alternative: str | None = None
    ) -> Refusal | AgentError:
        effective_code = code if code in _REFUSAL_CODES else "UNSUPPORTED_QUERY"
        default_alt = (
            "请使用已更新的有效替代指标进行查询。"
            if code == "DEPRECATED_METRIC_REJECTED"
            else "请使用授权范围内、受支持的聚合查询。"
        )
        return Refusal(
            reason_code=effective_code,  # type: ignore[arg-type]
            reason=reason,
            alternative=alternative or default_alt,
        )
