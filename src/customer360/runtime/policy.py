"""Trusted eval AccessPolicy construction. Scope never comes from Agent prompts."""

from pathlib import Path

import duckdb

from customer360.contracts.execution import AccessPolicy, TableGrant
from customer360.contracts.generation import DatasetManifest
from customer360.metadata.metrics import load_catalog

ANALYST_GRANTS = (
    TableGrant(
        table="dim_customer",
        columns=(
            "customer_id",
            "customer_level",
            "gender",
            "risk_level",
            "region",
            "city",
            "occupation",
            "registration_date",
            "status",
        ),
    ),
    TableGrant(
        table="fact_transaction",
        columns=(
            "transaction_id",
            "transaction_date",
            "customer_id",
            "product_id",
            "transaction_type",
            "amount",
            "quantity",
            "fee",
            "status",
            "channel",
        ),
    ),
    TableGrant(
        table="fact_cash_flow",
        columns=(
            "flow_id",
            "flow_date",
            "customer_id",
            "flow_type",
            "signed_amount",
            "channel",
            "status",
        ),
    ),
    TableGrant(
        table="fact_service_relation",
        columns=(
            "customer_id",
            "manager_id",
            "start_date",
            "end_date",
            "relation_type",
            "is_primary",
        ),
    ),
    TableGrant(
        table="fact_asset_snapshot",
        columns=(
            "snapshot_date",
            "customer_id",
            "total_asset",
            "cash_asset",
            "investment_asset",
            "liability",
            "net_asset",
        ),
    ),
)

TINY_CUSTOMER_IDS = tuple(f"C{index:03d}" for index in range(1, 101))


def eval_policy_for_customer_ids(customer_ids: tuple[str, ...], *, role: str) -> AccessPolicy:
    return AccessPolicy(role=role, customer_ids=customer_ids, grants=ANALYST_GRANTS)


def tiny_eval_policy() -> AccessPolicy:
    """Frozen Tiny C001-C100 analyst policy used by Tiny evaluate/verify paths."""

    return eval_policy_for_customer_ids(TINY_CUSTOMER_IDS, role="tiny_variant_analyst")


def customer_ids_from_database(database: Path) -> tuple[str, ...]:
    with duckdb.connect(str(database), read_only=True) as connection:
        rows = connection.execute(
            'SELECT "customer_id" FROM "dim_customer" ORDER BY "customer_id"'
        ).fetchall()
    return tuple(row[0] for row in rows)


def eval_policy_for_dataset(
    manifest: DatasetManifest, customer_ids: tuple[str, ...]
) -> AccessPolicy:
    expected = manifest.row_counts["dim_customer"]
    if len(customer_ids) != expected:
        raise ValueError("eval policy customer_ids must match verified dim_customer row count")
    if len(set(customer_ids)) != len(customer_ids):
        raise ValueError("eval policy customer_ids must be unique")
    return eval_policy_for_customer_ids(
        tuple(sorted(customer_ids)), role=f"{manifest.scale}_eval_analyst"
    )


def benchmark_eval_policy(manifest: DatasetManifest, customer_ids: tuple[str, ...]) -> AccessPolicy:
    """Build the complete trusted benchmark grant for formal evaluation.

    The regular analyst policy intentionally exercises least privilege.  A
    formal benchmark replay must not turn a valid Gold query into a semantic
    miss merely because a development subset omitted a catalog table.  The
    benchmark grant therefore includes every non-restricted catalog column,
    while still applying the verified customer scope and the gateway's normal
    SQL/result safety checks.
    """

    expected = manifest.row_counts["dim_customer"]
    if len(customer_ids) != expected or len(set(customer_ids)) != len(customer_ids):
        raise ValueError("benchmark policy customer_ids must match verified dataset scope")
    grants = tuple(
        TableGrant(
            table=table.table_name,
            columns=tuple(
                column.column_name for column in table.columns if column.sensitivity != "restricted"
            ),
        )
        for table in load_catalog().tables
        if table.scope == "customer"
        and any(column.sensitivity != "restricted" for column in table.columns)
    )
    return AccessPolicy(
        role=f"{manifest.scale}_benchmark_analyst",
        customer_ids=tuple(sorted(customer_ids)),
        grants=grants,
    )
