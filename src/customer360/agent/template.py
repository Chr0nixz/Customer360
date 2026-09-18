"""Deterministic local protocol agent. Not an official baseline and not Gold."""

from customer360.agent.protocol import AgentTools
from customer360.contracts.public import (
    AgentError,
    AgentRequest,
    AgentResponse,
    Clarification,
    Refusal,
    Success,
)
from customer360.errors import ExecutionFailure, QueryRejected

_ROLLING = (
    'SELECT COUNT("transaction_id") AS "transaction_count" FROM "fact_transaction" '
    "WHERE \"status\" = 'success' AND \"transaction_date\" >= '2025-04-02' "
    "AND \"transaction_date\" <= '2025-06-30'"
)
_LATEST = (
    'SELECT SUM("s"."total_asset") AS "latest_total_asset" '
    'FROM "fact_asset_snapshot" AS "s" '
    'JOIN (SELECT "customer_id", MAX("snapshot_date") AS "snapshot_date" '
    'FROM "fact_asset_snapshot" WHERE "snapshot_date" <= \'2025-06-30\' '
    'GROUP BY "customer_id") AS "latest" '
    'ON "s"."customer_id" = "latest"."customer_id" '
    'AND "s"."snapshot_date" = "latest"."snapshot_date"'
)
_GROUPED = (
    'SELECT "region" AS "region", COUNT(DISTINCT "customer_id") AS "active_customer_count" '
    'FROM "dim_customer" WHERE "status" = \'active\' GROUP BY "region"'
)


class TemplateAgent:
    """Resolves the frozen 20 public questions via tools. Does not read oracles."""

    def respond(self, request: AgentRequest, tools: AgentTools) -> AgentResponse:
        tools.search_metrics(request.question)
        question = request.question
        if any(token in question for token in ("手机号", "手机号码")):
            return Refusal(
                reason_code="UNKNOWN_FIELD",
                reason="客户手机号不是已声明字段。",
                alternative="请改用已授权的客户属性或指标。",
            )
        if self._needs_time_window(request):
            return Clarification(
                questions=("请给出含锚点日期的近N个自然日窗口。",),
                requested_slots=("time_window",),
            )
        sql = self._sql_for(question)
        if sql is None:
            return AgentError(reason_code="UNSUPPORTED_REQUEST", message="未识别的问题模板。")
        try:
            receipt = tools.execute_sql(sql)
        except QueryRejected as exc:
            allowed = {
                "PERMISSION_DENIED",
                "UNSAFE_SQL",
                "UNKNOWN_METRIC",
                "UNKNOWN_FIELD",
                "UNSUPPORTED_QUERY",
                "AGGREGATION_TOO_SMALL",
            }
            return Refusal(
                reason_code=exc.code if exc.code in allowed else "UNSUPPORTED_QUERY",
                reason=str(exc),
                alternative="请使用授权范围内、受支持的聚合查询。",
            )
        except ExecutionFailure:
            return AgentError(reason_code="TOOL_ERROR", message="查询执行失败。")
        return Success(
            answer="查询已通过受控工具执行；结构化结果以 query_id 对应记录为准。",
            sql=sql,
            query_id=receipt.query_id,
            confidence=1,
            evidence=("template_agent", "executed_by_gateway"),
        )

    def _needs_time_window(self, request: AgentRequest) -> bool:
        question = request.question
        if "最新" in question or "近90天" in question or "估值日" in question:
            return False
        if not any(token in question for token in ("最近", "近期")):
            return False
        return not any("近90" in message.content for message in request.conversation)

    def _sql_for(self, question: str) -> str | None:
        if any(token in question for token in ("按地区", "分地区", "各地区", "按客户地区")):
            return _GROUPED
        if any(
            token in question
            for token in ("最新快照", "最新资产快照", "最近一次快照", "各自最新快照")
        ):
            return _LATEST
        if "窗口外" in question or "前一日" in question or "前一天" in question:
            return (
                'SELECT COUNT("transaction_id") AS "transaction_count" FROM "fact_transaction" '
                "WHERE \"status\" = 'success' AND \"transaction_date\" >= '2025-04-02' "
                "AND \"transaction_date\" <= '2025-06-30' AND \"transaction_date\" = '2025-04-01'"
            )
        if "首日" in question or "第一天" in question or "起始日" in question:
            return (
                'SELECT COUNT("transaction_id") AS "transaction_count" FROM "fact_transaction" '
                "WHERE \"status\" = 'success' AND \"transaction_date\" >= '2025-04-02' "
                "AND \"transaction_date\" <= '2025-06-30' AND \"transaction_date\" = '2025-04-02'"
            )
        if "有成功交易" in question or "发生过成功交易" in question or "成功交易VIP" in question:
            return (
                'SELECT COUNT(DISTINCT "c"."customer_id") AS "customer_count" '
                'FROM "dim_customer" AS "c" '
                'JOIN "fact_transaction" AS "t" ON "c"."customer_id" = "t"."customer_id" '
                'WHERE "c"."customer_level" = \'VIP\' AND "t"."status" = \'success\' '
                'AND "t"."transaction_date" >= \'2025-04-02\' '
                'AND "t"."transaction_date" <= \'2025-06-30\''
            )
        if "职业" in question and any(token in question for token in ("空", "缺失", "没有填写")):
            return (
                'SELECT COUNT(DISTINCT "customer_id") AS "customer_count" '
                'FROM "dim_customer" WHERE "occupation" IS NULL'
            )
        if "华东" in question and "VIP" in question:
            return (
                'SELECT COUNT(DISTINCT "customer_id") AS "customer_count" '
                'FROM "dim_customer" WHERE "customer_level" = \'VIP\' AND "region" = \'华东\''
            )
        if "主服务关系" in question:
            return (
                'SELECT COUNT("customer_id") AS "primary_service_relation_count" '
                'FROM "fact_service_relation" WHERE "is_primary" = TRUE AND "end_date" IS NULL'
            )
        if "净流入" in question or "流入减流出" in question:
            return (
                'SELECT SUM("signed_amount") AS "net_cash_flow" FROM "fact_cash_flow" '
                "WHERE \"status\" = 'success' AND \"flow_date\" >= '2025-04-02' "
                "AND \"flow_date\" <= '2025-06-30'"
            )
        if "入账" in question or ("流入" in question and "净流入" not in question):
            return (
                'SELECT SUM("signed_amount") AS "cash_inflow" FROM "fact_cash_flow" '
                "WHERE \"status\" = 'success' AND \"flow_type\" = 'in' "
                "AND \"flow_date\" >= '2025-04-02' AND \"flow_date\" <= '2025-06-30'"
            )
        if "失败交易" in question:
            return (
                'SELECT COUNT("transaction_id") AS "failed_transaction_count" '
                'FROM "fact_transaction" WHERE "status" = \'failed\' '
                "AND \"transaction_date\" >= '2025-04-02' AND \"transaction_date\" <= '2025-06-30'"
            )
        if "净资产" in question:
            snapshot = "2024-12-31" if "2024" in question else "2025-06-30"
            return (
                f'SELECT SUM("net_asset") AS "net_asset" FROM "fact_asset_snapshot" '
                f"WHERE \"snapshot_date\" = '{snapshot}'"
            )
        if "总资产" in question:
            return (
                'SELECT SUM("total_asset") AS "total_asset" FROM "fact_asset_snapshot" '
                "WHERE \"snapshot_date\" = '2025-06-30'"
            )
        if "交易金额" in question or "金额总和" in question or "成功交易金额" in question:
            return (
                'SELECT SUM("amount") AS "transaction_amount" FROM "fact_transaction" '
                "WHERE \"status\" = 'success' AND \"transaction_date\" >= '2025-04-02' "
                "AND \"transaction_date\" <= '2025-06-30'"
            )
        if "成功交易" in question or "交易笔" in question or "交易次数" in question:
            return _ROLLING
        if "活跃" in question:
            return (
                'SELECT COUNT(DISTINCT "customer_id") AS "active_customer_count" '
                'FROM "dim_customer" WHERE "status" = \'active\''
            )
        if "VIP" in question:
            return (
                'SELECT COUNT(DISTINCT "customer_id") AS "customer_count" '
                'FROM "dim_customer" WHERE "customer_level" = \'VIP\''
            )
        if "交易" in question:
            return _ROLLING
        return None
