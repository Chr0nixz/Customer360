"""Named Tiny boundary probes. Counts and dates only; no restricted fields."""

from collections import Counter
from datetime import date, timedelta

from customer360.contracts.coverage import ProbeResult
from customer360.contracts.generation import GenerationConfig
from customer360.metadata.metrics import UNDECLARED_ENTITY_FIELDS, MetadataRepository
from customer360.tasks.independent import TableSlice


def _column(slice_: TableSlice, name: str) -> tuple[object, ...]:
    index = slice_.index(name)
    return tuple(row[index] for row in slice_.rows)


def _success_on(transactions: TableSlice, day: date) -> int:
    status = transactions.index("status")
    txn_date = transactions.index("transaction_date")
    return sum(1 for row in transactions.rows if row[status] == "success" and row[txn_date] == day)


def evaluate_probes(
    slices: dict[str, TableSlice],
    repository: MetadataRepository,
    config: GenerationConfig | None = None,
) -> tuple[ProbeResult, ...]:
    config = config or GenerationConfig()
    customers = slices["dim_customer"]
    transactions = slices["fact_transaction"]
    holdings = slices["fact_holding"]
    assets = slices["fact_asset_snapshot"]
    flows = slices["fact_cash_flow"]
    relations = slices["fact_service_relation"]
    window_start = config.anchor_date - timedelta(days=89)
    day_before = window_start - timedelta(days=1)
    occupation_nulls = sum(1 for value in _column(customers, "occupation") if value is None)
    txn_customers = set(_column(transactions, "customer_id"))
    hold_customers = set(_column(holdings, "customer_id"))
    all_customers = set(_column(customers, "customer_id"))
    statuses = Counter(_column(customers, "status"))
    txn_status = transactions.index("status")
    txn_amount = transactions.index("amount")
    txn_date = transactions.index("transaction_date")
    window_success_amounts = [
        row[txn_amount]
        for row in transactions.rows
        if row[txn_status] == "success" and window_start <= row[txn_date] <= config.anchor_date
    ]
    failed = sum(
        1
        for row in transactions.rows
        if row[txn_status] == "failed" and window_start <= row[txn_date] <= config.anchor_date
    )
    cancelled = sum(
        1
        for row in transactions.rows
        if row[txn_status] == "cancelled" and window_start <= row[txn_date] <= config.anchor_date
    )
    flow_date = flows.index("flow_date")
    flow_type = flows.index("flow_type")
    inflow = sum(
        1
        for row in flows.rows
        if row[flow_type] == "in" and window_start <= row[flow_date] <= config.anchor_date
    )
    outflow = sum(
        1
        for row in flows.rows
        if row[flow_type] == "out" and window_start <= row[flow_date] <= config.anchor_date
    )
    primary_open = sum(
        1
        for row in relations.rows
        if row[relations.index("is_primary")] is True and row[relations.index("end_date")] is None
    )
    snapshot_dates = tuple(sorted(set(_column(assets, "snapshot_date"))))
    catalog_columns = {
        column.column_name for table in repository.catalog.tables for column in table.columns
    }
    restricted_names = any(
        column.column_name == "customer_name" and column.sensitivity == "restricted"
        for column in repository.catalog.table("dim_customer").columns
    )
    checks = [
        (
            "window_day_before_success",
            _success_on(transactions, day_before),
            _success_on(transactions, day_before) >= 1,
            "window day before anchor-89 has success transactions",
        ),
        (
            "window_start_success",
            _success_on(transactions, window_start),
            _success_on(transactions, window_start) >= 1,
            "rolling window start day has success transactions",
        ),
        (
            "window_anchor_success",
            _success_on(transactions, config.anchor_date),
            _success_on(transactions, config.anchor_date) >= 1,
            "anchor date has success transactions",
        ),
        (
            "null_occupation_exact",
            occupation_nulls,
            occupation_nulls == config.customers_with_null_occupation,
            "occupation NULL count matches generation config",
        ),
        (
            "customers_without_transactions",
            len(all_customers - txn_customers),
            len(all_customers - txn_customers) == config.customers_without_transactions,
            "customers with no transactions match generation config",
        ),
        (
            "customers_without_positions",
            len(all_customers - hold_customers),
            len(all_customers - hold_customers) == config.customers_without_positions,
            "customers with no holdings match generation config",
        ),
        (
            "status_partition_complete",
            dict(statuses),
            set(statuses) == {"active", "dormant", "closed"}
            and sum(statuses.values()) == config.customers,
            "active/dormant/closed partition the customer table",
        ),
        (
            "vip_customers_present",
            sum(1 for value in _column(customers, "customer_level") if value == "VIP"),
            "VIP" in set(_column(customers, "customer_level")),
            "VIP customers exist for filter cases",
        ),
        (
            "failed_and_cancelled_present",
            {"failed": failed, "cancelled": cancelled},
            failed >= 1 and cancelled >= 1,
            "failed and cancelled transactions both appear in the rolling window",
        ),
        (
            "duplicate_success_amount",
            len(window_success_amounts) - len(set(window_success_amounts)),
            len(window_success_amounts) > len(set(window_success_amounts)),
            "success amounts in the rolling window are not all unique",
        ),
        (
            "valuation_dates_include_bounds",
            [day.isoformat() for day in snapshot_dates],
            snapshot_dates == tuple(config.snapshot_dates),
            "asset snapshots cover every configured valuation date",
        ),
        (
            "ended_or_non_primary_relations",
            {"primary_open": primary_open, "all": len(relations.rows)},
            primary_open >= 1 and len(relations.rows) > primary_open,
            "ended or non-primary relations exist so IS NULL/is_primary matter",
        ),
        (
            "in_and_out_flows_in_window",
            {"in": inflow, "out": outflow},
            inflow >= 1 and outflow >= 1,
            "window contains both inflow and outflow",
        ),
        (
            "restricted_name_exists_phone_absent",
            {
                "restricted_customer_name": restricted_names,
                "undeclared": sorted(catalog_columns & UNDECLARED_ENTITY_FIELDS),
            },
            restricted_names and not (catalog_columns & UNDECLARED_ENTITY_FIELDS),
            "customer_name is restricted; phone/id_card are absent",
        ),
    ]
    return tuple(
        ProbeResult(probe_id=probe_id, passed=passed, observed=observed, detail=detail)
        for probe_id, observed, passed, detail in checks
    )
