"""Protocol conformance adapter, NOT an NL baseline or a scored model."""

from customer360.agent.protocol import AgentTools
from customer360.contracts.public import AgentError, AgentRequest, AgentResponse, Refusal, Success
from customer360.errors import ExecutionFailure, QueryRejected


class SqlSubmissionAgent:
    def __init__(self, sql: str):
        self.sql = sql

    def respond(self, request: AgentRequest, tools: AgentTools) -> AgentResponse:
        try:
            receipt = tools.execute_sql(self.sql)
        except QueryRejected as exc:
            return Refusal(
                reason_code=exc.code,
                reason=str(exc),
                alternative="请使用授权范围内、受支持的聚合查询。",
            )
        except ExecutionFailure:
            return AgentError(reason_code="TOOL_ERROR", message="查询执行失败。")
        return Success(
            answer="查询已通过受控工具执行；结构化结果以 query_id 对应记录为准。",
            sql=self.sql,
            query_id=receipt.query_id,
            confidence=1,
            evidence=("executed_by_gateway",),
        )
