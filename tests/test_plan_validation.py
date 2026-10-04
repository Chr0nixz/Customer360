from customer360.contracts.validation import PlanPredicate, QueryPlanValidationRequest
from customer360.runtime.validator import validate_query_plan
from customer360.tasks.variant import tiny_eval_policy


def test_validate_query_plan_success(repository):
    policy = tiny_eval_policy()
    # Legitimate customer count query
    req = QueryPlanValidationRequest(
        source_table="dim_customer",
        operation="count_distinct",
        measure_column="customer_id",
        output_column="customer_count",
        predicates=(
            PlanPredicate(field="customer_level", operator="eq", values=("VIP",)),
            PlanPredicate(field="status", operator="eq", values=("active",)),
        ),
    )
    res = validate_query_plan(req, repository, policy)
    assert res.is_valid is True
    assert len(res.issues) == 0


def test_validate_query_plan_issues(repository):
    policy = tiny_eval_policy()

    # 1. UNKNOWN_SOURCE_TABLE
    req1 = QueryPlanValidationRequest(
        source_table="unknown_table",
        operation="count",
        measure_column="customer_id",
        output_column="cnt",
    )
    res1 = validate_query_plan(req1, repository, policy)
    assert res1.is_valid is False
    assert any(i.code == "UNKNOWN_SOURCE_TABLE" for i in res1.issues)

    # 2. INVALID_MEASURE_COLUMN (non-decimal column for sum)
    req2 = QueryPlanValidationRequest(
        source_table="dim_customer",
        operation="sum",
        measure_column="customer_id",
        output_column="cnt",
    )
    res2 = validate_query_plan(req2, repository, policy)
    assert res2.is_valid is False
    assert any(i.code == "INVALID_MEASURE_COLUMN" for i in res2.issues)

    # 3. DISALLOWED_FILTER_COLUMN (non-existent column)
    req3 = QueryPlanValidationRequest(
        source_table="dim_customer",
        operation="count_distinct",
        measure_column="customer_id",
        output_column="cnt",
        predicates=(PlanPredicate(field="non_existent_col", operator="eq", values=("X",)),),
    )
    res3 = validate_query_plan(req3, repository, policy)
    assert res3.is_valid is False
    assert any(i.code == "DISALLOWED_FILTER_COLUMN" for i in res3.issues)

    # 4. INVALID_PREDICATE_LITERAL (string given for date column)
    req4 = QueryPlanValidationRequest(
        source_table="fact_transaction",
        operation="count",
        measure_column="transaction_id",
        output_column="cnt",
        predicates=(
            PlanPredicate(field="transaction_date", operator="gte", values=("not-a-valid-date",)),
        ),
    )
    res4 = validate_query_plan(req4, repository, policy)
    assert res4.is_valid is False
    assert any(i.code == "INVALID_PREDICATE_LITERAL" for i in res4.issues)

    # 5. UNSUPPORTED_JOIN_PATH
    req5 = QueryPlanValidationRequest(
        source_table="dim_customer",
        operation="count_distinct",
        measure_column="customer_id",
        output_column="cnt",
        join_path="arbitrary_unreviewed_join",
    )
    res5 = validate_query_plan(req5, repository, policy)
    assert res5.is_valid is False
    assert any(i.code == "UNSUPPORTED_JOIN_PATH" for i in res5.issues)

    # 6. INVALID_JOIN_PREDICATES (missing status=success on fact_transaction)
    req6 = QueryPlanValidationRequest(
        source_table="dim_customer",
        operation="count_distinct",
        measure_column="customer_id",
        output_column="cnt",
        join_path="customer_transactions",
        predicates=(),
    )
    res6 = validate_query_plan(req6, repository, policy)
    assert res6.is_valid is False
    assert any(i.code == "INVALID_JOIN_PREDICATES" for i in res6.issues)

    # 7. INVALID_GROUP_DIMENSION (group_by not permitted on join queries)
    req7 = QueryPlanValidationRequest(
        source_table="dim_customer",
        operation="count_distinct",
        measure_column="customer_id",
        output_column="cnt",
        join_path="customer_transactions",
        predicates=(PlanPredicate(field="status", operator="eq", values=("success",), alias="t"),),
        group_by=("region",),
    )
    res7 = validate_query_plan(req7, repository, policy)
    assert res7.is_valid is False
    assert any(i.code == "INVALID_GROUP_DIMENSION" for i in res7.issues)


def test_tool_session_validate_query_plan(baseline, repository):
    from customer360.runtime.gateway import ExecutionGateway
    from customer360.runtime.tools import ToolSession

    gateway = ExecutionGateway(baseline / "dataset.duckdb", tiny_eval_policy())
    tools = ToolSession(gateway, repository)

    valid_plan = {
        "source_table": "dim_customer",
        "operation": "count_distinct",
        "measure_column": "customer_id",
        "output_column": "customer_count",
        "predicates": [
            {"field": "customer_level", "operator": "eq", "values": ["VIP"]},
        ],
    }
    resp = tools.validate_query_plan(valid_plan)
    assert resp["is_valid"] is True
    assert len(resp["issues"]) == 0

    invalid_plan = {
        "source_table": "unknown_table",
        "operation": "count",
        "measure_column": "customer_id",
        "output_column": "cnt",
    }
    resp_invalid = tools.validate_query_plan(invalid_plan)
    assert resp_invalid["is_valid"] is False
    assert any(i["code"] == "UNKNOWN_SOURCE_TABLE" for i in resp_invalid["issues"])

    # Verify trace recorded
    tool_calls = [c for c in tools.calls if c["tool"] == "validate_query_plan"]
    assert len(tool_calls) == 2
