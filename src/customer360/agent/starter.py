"""Agent starter generator for external developer onboarding."""

from pathlib import Path

STARTER_TEMPLATE = '''"""Custom Customer360 Agent starter template.

Implement your retrieval, semantic reasoning, and SQL generation logic here.
All database executions must use the provided tools.execute_sql() gateway.
"""

from customer360.agent.protocol import AgentTools
from customer360.contracts.public import (
    AgentRequest,
    AgentResponse,
    Clarification,
    Refusal,
    Success,
)


class {agent_name}:
    """Starter agent implementing the Customer360 Agent protocol."""

    def __init__(self, name: str = "{agent_name}") -> None:
        self.name = name

    def respond(self, request: AgentRequest, tools: AgentTools) -> AgentResponse:
        """Process one conversational turn.

        Args:
            request: The case request, containing case_id, question, anchor_date,
                     and any previous conversation turns.
            tools: Secure execution gateway and metadata discovery tools:
                   - tools.search_metrics(query)
                   - tools.search_tables(query)
                   - tools.search_columns(query)
                   - tools.get_metric_definition(metric_name)
                   - tools.get_table_schema(table_name)
                   - tools.get_join_paths(query)
                   - tools.validate_query_plan(plan_dict)
                   - tools.execute_sql(sql_str) -> QueryReceipt

        Returns:
            One of:
            - Success: Answer with validated SQL and query_id from tools.execute_sql()
            - Clarification: If critical slots or dimensions are ambiguous
            - Refusal: If unauthorized or unsafe data is requested
        """
        question = request.question.strip()

        # 1. Safety & Access Check example
        if "customer_name" in question or "DROP" in question.upper():
            return Refusal(
                status="refused",
                reason_code="PERMISSION_DENIED",
                reason="Cannot query sensitive customer names or execute DDL.",
            )

        # 2. Clarification example
        if "最近" in question and not request.conversation:
            # When time window is ambiguous, request clarification slots
            return Clarification(
                status="clarification_needed",
                requested_slots=("time_window",),
                questions=("请问您需要统计的时间窗口是近30天还是近90天？",),
            )

        # 3. Discovery & Execution example
        metrics = tools.search_metrics("客户数")
        sql = "SELECT COUNT(DISTINCT customer_id) AS customer_count FROM dim_customer"
        receipt = tools.execute_sql(sql)
        row_count = len(receipt.result.rows)

        return Success(
            status="success",
            answer=f"现有客户查询已执行，共返回 {{row_count}} 行结果。",
            sql=sql,
            query_id=receipt.query_id,
            confidence=1.0,
        )
'''


def generate_agent_starter(
    output_path: Path,
    agent_name: str = "MyCustomAgent",
    *,
    force: bool = False,
) -> Path:
    """Generate a starter agent Python file."""
    if not agent_name.isidentifier():
        raise ValueError(
            f"agent_name '{agent_name}' is not a valid Python identifier. "
            "It must start with a letter/underscore and contain only alphanumeric characters."
        )

    if output_path.suffix != ".py":
        raise ValueError(f"output_path must end with .py, got: '{output_path.name}'")

    if output_path.exists() and not force:
        raise FileExistsError(f"File already exists: {output_path}. Use force=True to overwrite.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = STARTER_TEMPLATE.format(agent_name=agent_name)
    output_path.write_text(content, encoding="utf-8")
    return output_path
