"""Reproducible dataset generator (Tiny / Standard / Large).

Tiny keeps C001 identifiers and the frozen 100/2000 recipe. All business values
come from a local Random seeded by GenerationConfig.seed; no system time, global
random state, network or model API participates. Every date lies inside
[horizon_start, anchor_date] so dim_date covers all facts. Generation fails
closed: if any named quality check fails, no manifest is published and the
partial directory is kept for inspection.
"""

from datetime import date, timedelta
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from random import Random

import duckdb
import yaml

from customer360.artifacts import digest, json_text, write_json_new
from customer360.contracts.generation import (
    ARTIFACT_KIND,
    SNAPSHOT_VERSION,
    DatasetManifest,
    GenerationConfig,
    QualityReport,
)
from customer360.metadata.metrics import load_catalog
from customer360.synth.constraints import (
    CHANNELS,
    CUSTOMER_STATUS,
    LEVELS,
    PRODUCT_TYPES,
    REGIONS,
    RISK_LEVELS,
    TRANSACTION_TYPES,
    run_quality_checks,
)
from customer360.synth.ids import numbered_id
from customer360.synth.schema import render_ddl, render_literal

GENERATOR_VERSION = "0.1.0"
SUPPORTED_SCALES = ("tiny", "standard", "large")
DATABASE_NAME = "dataset.duckdb"
MANIFEST_NAME = "manifest.json"
QUALITY_REPORT_NAME = "quality_report.json"
CONFIG_SNAPSHOT_NAME = "generation_config.json"

CENT = Decimal("0.01")
REGION_CITIES = {
    "华东": ("上海", "杭州", "南京"),
    "华北": ("北京", "天津"),
    "华南": ("深圳", "广州"),
    "西南": ("成都", "重庆"),
}
OCCUPATIONS = ("教师", "工程师", "医生", "设计师", "公务员", "个体经营")
VIP_CUSTOMERS = 40
CLOSED_CUSTOMERS = 6
DORMANT_CUSTOMERS = 10
MANAGER_ENTRY_START = date(2015, 1, 1)
MANAGER_ENTRY_END = date(2023, 12, 31)
PRODUCT_LISTING_START = date(2015, 1, 1)
ASSET_GROWTH_BPS = 300
ROLLING_DAYS = 90


def _bulk_insert(conn, table: str, rows: list[tuple], chunk_size: int = 250) -> None:
    # executemany costs ~10ms per row on DuckDB; chunked literal VALUES is fast.
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start : start + chunk_size]
        values = ", ".join("(" + ", ".join(render_literal(v) for v in row) + ")" for row in chunk)
        conn.execute(f'INSERT INTO "{table}" VALUES {values}')


def _ordered(rows: list[dict], table: str, catalog) -> list[tuple]:
    names = [column.column_name for column in catalog.table(table).columns]
    return [tuple(row[name] for name in names) for row in rows]


def _status_group_sizes(config: GenerationConfig) -> tuple[int, int, int]:
    if config.scale == "tiny":
        return VIP_CUSTOMERS, CLOSED_CUSTOMERS, DORMANT_CUSTOMERS
    return (
        config.customers * 40 // 100,
        config.customers * 6 // 100,
        config.customers * 10 // 100,
    )


def _txn_values(amount: Decimal, rng: Random) -> tuple[Decimal, Decimal]:
    price = Decimal(rng.randrange(100, 5001)) / 100
    quantity = (amount / price).quantize(CENT)
    fee = (amount * rng.randrange(1, 101) / 10000).quantize(CENT)
    return quantity, fee


def _build_rows(config: GenerationConfig) -> dict[str, list[tuple]]:
    rng = Random(config.seed)
    horizon_days = (config.anchor_date - config.horizon_start).days + 1
    # A custom, valid horizon may be only one day long.  Keep the
    # registration draw non-empty; the default recipes remain unchanged.
    first_half_days = max(1, horizon_days // 2)

    # Fixed draw order: designation sets first, then per-row attributes.
    vip_count, closed_count, dormant_count = _status_group_sizes(config)
    designation = rng.sample(range(config.customers), config.customers)
    vip = set(designation[:vip_count])
    cursor = vip_count
    closed = set(designation[cursor : cursor + closed_count])
    cursor += closed_count
    dormant = set(designation[cursor : cursor + dormant_count])
    cursor += dormant_count
    no_txn = set(designation[cursor : cursor + config.customers_without_transactions])
    cursor += config.customers_without_transactions
    no_hold = set(designation[cursor : cursor + config.customers_without_positions])
    cursor += config.customers_without_positions
    null_occupation = set(designation[cursor : cursor + config.customers_with_null_occupation])
    if cursor + config.customers_with_null_occupation > config.customers:
        raise ValueError("designated customer groups exceed the customer count")

    customers = []
    for index in range(config.customers):
        region = REGIONS[rng.randrange(0, len(REGIONS))]
        age = rng.randrange(18, 86)
        try:
            birth = config.anchor_date.replace(year=config.anchor_date.year - age)
        except ValueError:
            birth = date(config.anchor_date.year - age, config.anchor_date.month, 28)
        customers.append(
            {
                "customer_id": numbered_id("C", index + 1, config.customers),
                "customer_name": f"客户{numbered_id('C', index + 1, config.customers)[1:]}",
                "gender": "F" if rng.random() < 0.5 else "M",
                "birth_date": birth,
                "customer_level": LEVELS[0] if index in vip else LEVELS[1],
                "risk_level": RISK_LEVELS[rng.randrange(0, len(RISK_LEVELS))],
                "region": region,
                "city": REGION_CITIES[region][rng.randrange(0, len(REGION_CITIES[region]))],
                "occupation": None
                if index in null_occupation
                else OCCUPATIONS[rng.randrange(0, len(OCCUPATIONS))],
                "registration_date": config.horizon_start
                + timedelta(days=rng.randrange(0, first_half_days)),
                "status": CUSTOMER_STATUS[2]
                if index in closed
                else CUSTOMER_STATUS[1]
                if index in dormant
                else CUSTOMER_STATUS[0],
            }
        )

    managers = []
    dormant_managers = set(rng.sample(range(config.managers), max(1, config.managers // 5)))
    for index in range(config.managers):
        region = REGIONS[rng.randrange(0, len(REGIONS))]
        city = REGION_CITIES[region][rng.randrange(0, len(REGION_CITIES[region]))]
        managers.append(
            {
                "manager_id": numbered_id("M", index + 1, config.managers),
                "manager_name": f"经理{numbered_id('M', index + 1, config.managers)[1:]}",
                "branch_id": numbered_id("B", index + 1, config.managers),
                "branch_name": f"{city}第{index + 1:02d}营业部",
                "region": region,
                "entry_date": MANAGER_ENTRY_START
                + timedelta(
                    days=rng.randrange(0, (MANAGER_ENTRY_END - MANAGER_ENTRY_START).days + 1)
                ),
                "status": "dormant" if index in dormant_managers else "active",
            }
        )

    products = []
    type_slots = [PRODUCT_TYPES[0]] * (config.products // 2)
    type_slots += [PRODUCT_TYPES[1]] * (config.products - len(type_slots))
    rng.shuffle(type_slots)
    for index in range(config.products):
        product_type = type_slots[index]
        listing_span = (config.horizon_start - timedelta(days=1) - PRODUCT_LISTING_START).days + 1
        products.append(
            {
                "product_id": numbered_id("P", index + 1, config.products),
                "product_name": (
                    f"成长混合{index + 1:02d}"
                    if product_type == PRODUCT_TYPES[0]
                    else f"稳健债券{index + 1:02d}"
                ),
                "product_type": product_type,
                "risk_level": RISK_LEVELS[rng.randrange(0, len(RISK_LEVELS))],
                "issuer": f"Issuer-{chr(65 + index % 26)}",
                "currency": "CNY",
                "listing_date": PRODUCT_LISTING_START
                + timedelta(days=rng.randrange(0, listing_span)),
                "status": "active",
            }
        )

    dim_date = []
    day = config.horizon_start
    while day <= config.anchor_date:
        month_end = (day + timedelta(days=1)).month != day.month
        dim_date.append(
            {
                "date_id": day.isoformat(),
                "calendar_date": day,
                "year": day.year,
                "quarter": (day.month - 1) // 3 + 1,
                "month": day.month,
                "week": day.isocalendar()[1],
                "is_month_end": month_end,
                "is_quarter_end": month_end and day.month in (3, 6, 9, 12),
            }
        )
        day += timedelta(days=1)

    manager_ids = [manager["manager_id"] for manager in managers]
    relations = []
    for index in range(config.customers):
        customer_id = numbered_id("C", index + 1, config.customers)
        registration = customers[index]["registration_date"]
        span = (config.anchor_date - registration).days
        is_closed = index in closed
        max_start_offset = span - 1 if is_closed else span
        primary_start = registration + timedelta(days=rng.randrange(0, max_start_offset + 1))
        primary_manager = manager_ids[rng.randrange(0, len(manager_ids))]
        primary_end = None
        if is_closed:
            end_span = (config.anchor_date - primary_start).days
            primary_end = primary_start + timedelta(days=rng.randrange(1, end_span + 1))
        relations.append(
            {
                "customer_id": customer_id,
                "manager_id": primary_manager,
                "start_date": primary_start,
                "end_date": primary_end,
                "relation_type": "wealth",
                "is_primary": True,
            }
        )
        if primary_start > registration and rng.random() < 0.2:
            # Left-closed/right-open intervals: the prior primary ends exactly
            # where the current one starts, so any date has at most one primary.
            relations.append(
                {
                    "customer_id": customer_id,
                    "manager_id": manager_ids[rng.randrange(0, len(manager_ids))],
                    "start_date": registration,
                    "end_date": primary_start,
                    "relation_type": "wealth",
                    "is_primary": True,
                }
            )
        # A one-manager configuration cannot produce a distinct secondary
        # relation.  Treat that relation as optional instead of indexing an
        # empty list after a valid GenerationConfig has been accepted.
        if len(manager_ids) > 1 and max_start_offset >= 1 and rng.random() < 0.3:
            others = [manager_id for manager_id in manager_ids if manager_id != primary_manager]
            secondary_start = registration + timedelta(days=rng.randrange(1, max_start_offset + 1))
            secondary_end = None
            if is_closed:
                end_span = (config.anchor_date - secondary_start).days
                secondary_end = secondary_start + timedelta(days=rng.randrange(1, end_span + 1))
            relations.append(
                {
                    "customer_id": customer_id,
                    "manager_id": others[rng.randrange(0, len(others))],
                    "start_date": secondary_start,
                    "end_date": secondary_end,
                    "relation_type": "wealth",
                    "is_primary": False,
                }
            )

    base_wealth = {}
    for index in range(config.customers):
        if index in vip:
            cents = rng.randrange(20_000_000, 200_000_001)
        else:
            cents = rng.randrange(500_000, 50_000_001)
        base_wealth[index] = Decimal(cents) / 100

    snapshots = []
    investments = {}
    for index in range(config.customers):
        factor = Decimal(1)
        for snapshot_date in config.snapshot_dates:
            if factor != 1:
                factor *= Decimal(10000 + rng.randrange(-ASSET_GROWTH_BPS, ASSET_GROWTH_BPS + 1))
                factor = factor / 10000
            total = (base_wealth[index] * factor).quantize(CENT)
            if index in no_hold:
                investment = Decimal("0.00")
            else:
                investment = (total * rng.randrange(10, 91) / 100).quantize(CENT)
            investments[(index, snapshot_date)] = investment
            liability = (total * rng.randrange(0, 4001) / 10000).quantize(CENT)
            snapshots.append(
                {
                    "snapshot_date": snapshot_date,
                    "customer_id": numbered_id("C", index + 1, config.customers),
                    "total_asset": total,
                    "cash_asset": total - investment,
                    "investment_asset": investment,
                    "liability": liability,
                    "net_asset": total - liability,
                }
            )

    product_ids = [product["product_id"] for product in products]
    holdings = []
    for index in range(config.customers):
        if index in no_hold:
            continue
        customer_id = numbered_id("C", index + 1, config.customers)
        for snapshot_date in config.snapshot_dates:
            investment = investments[(index, snapshot_date)]
            # The anchor valuation date always carries positions; earlier dates
            # may not, so exactly the designated customers stay without holdings.
            if snapshot_date != config.anchor_date and rng.random() >= 0.85:
                continue
            if len(product_ids) >= 3:
                selection_sizes = (1, 1, 2, 3)
            elif len(product_ids) == 2:
                selection_sizes = (1, 1, 2)
            else:
                selection_sizes = (1,)
            chosen = rng.sample(range(len(product_ids)), rng.choice(selection_sizes))
            weights = [rng.randrange(1, 101) for _ in chosen]
            held_total = investment * rng.randrange(30, 91) / 100
            for weight, product_index in zip(weights, chosen, strict=True):
                market_value = (held_total * weight / sum(weights)).quantize(CENT)
                cost_value = (market_value * rng.randrange(80, 121) / 100).quantize(CENT)
                price = Decimal(rng.randrange(100, 5001)) / 100
                holdings.append(
                    {
                        "snapshot_date": snapshot_date,
                        "customer_id": customer_id,
                        "product_id": product_ids[product_index],
                        "quantity": (market_value / price).quantize(CENT),
                        "market_value": market_value,
                        "cost_value": cost_value,
                        "unrealized_profit": market_value - cost_value,
                        "holding_status": "active",
                    }
                )

    transactions = []
    txn_pool = [index for index in range(config.customers) if index not in no_txn]
    if len(txn_pool) < 4:
        raise ValueError("at least four customers must remain eligible for transactions")
    window_start = config.anchor_date - timedelta(days=ROLLING_DAYS - 1)
    boundary = (window_start - timedelta(days=1), window_start, config.anchor_date)
    forced = [
        (boundary[0], txn_pool[0], Decimal("1000.00")),
        (boundary[1], txn_pool[1], Decimal("1000.00")),
        (boundary[2], txn_pool[2], Decimal("1000.00")),
        (boundary[2], txn_pool[3], Decimal("2500.00")),
        (boundary[1], txn_pool[3], Decimal("2500.00")),
    ]
    random_count = config.transactions - len(forced)
    failed_count = random_count * 6 // 100
    cancelled_count = random_count * 4 // 100
    statuses = (
        ["success"] * (random_count - failed_count - cancelled_count)
        + ["failed"] * failed_count
        + ["cancelled"] * cancelled_count
    )
    buy_count = random_count * 40 // 100
    sell_count = random_count * 25 // 100
    subscribe_count = random_count * 20 // 100
    types = (
        [TRANSACTION_TYPES[0]] * buy_count
        + [TRANSACTION_TYPES[1]] * sell_count
        + [TRANSACTION_TYPES[2]] * subscribe_count
        + [TRANSACTION_TYPES[3]] * (random_count - buy_count - sell_count - subscribe_count)
    )
    app_count = random_count * 60 // 100
    channels = [CHANNELS[0]] * app_count + [CHANNELS[1]] * (random_count - app_count)
    rng.shuffle(statuses)
    rng.shuffle(types)
    rng.shuffle(channels)

    def append_transaction(
        number, transaction_date, customer_index, amount, status, txn_type, channel
    ):
        quantity, fee = _txn_values(amount, rng)
        transactions.append(
            {
                "transaction_id": numbered_id("T", number, config.transactions),
                "transaction_date": transaction_date,
                "customer_id": numbered_id("C", customer_index + 1, config.customers),
                "product_id": product_ids[rng.randrange(0, len(product_ids))],
                "transaction_type": txn_type,
                "amount": amount,
                "quantity": quantity,
                "fee": fee,
                "status": status,
                "channel": channel,
            }
        )

    for offset, (transaction_date, customer_index, amount) in enumerate(forced):
        append_transaction(
            offset + 1, transaction_date, customer_index, amount, "success", "buy", "app"
        )
    for offset in range(random_count):
        append_transaction(
            len(forced) + offset + 1,
            config.horizon_start + timedelta(days=rng.randrange(0, horizon_days)),
            txn_pool[rng.randrange(0, len(txn_pool))],
            Decimal(rng.randrange(1_000, 10_000_000)) / 100,
            statuses[offset],
            types[offset],
            channels[offset],
        )

    flows = []
    in_count = config.cash_flows * 45 // 100
    flow_types = ["in"] * in_count + ["out"] * (config.cash_flows - in_count)
    bank_count = config.cash_flows * 45 // 100
    app_flow_count = config.cash_flows * 25 // 100
    flow_channels = (
        ["bank"] * bank_count
        + ["app"] * app_flow_count
        + ["branch"] * (config.cash_flows - bank_count - app_flow_count)
    )
    rng.shuffle(flow_types)
    rng.shuffle(flow_channels)
    for offset in range(config.cash_flows):
        amount = Decimal(rng.randrange(10_000, 5_000_001)) / 100
        flows.append(
            {
                "flow_id": numbered_id("F", offset + 1, config.cash_flows),
                "flow_date": config.horizon_start + timedelta(days=rng.randrange(0, horizon_days)),
                "customer_id": numbered_id(
                    "C", rng.randrange(0, config.customers) + 1, config.customers
                ),
                "flow_type": flow_types[offset],
                "signed_amount": amount if flow_types[offset] == "in" else -amount,
                "channel": flow_channels[offset],
                "status": "success",
            }
        )

    catalog = load_catalog()
    return {
        "dim_customer": _ordered(customers, "dim_customer", catalog),
        "dim_service_manager": _ordered(managers, "dim_service_manager", catalog),
        "dim_product": _ordered(products, "dim_product", catalog),
        "fact_service_relation": _ordered(relations, "fact_service_relation", catalog),
        "dim_date": _ordered(dim_date, "dim_date", catalog),
        "fact_holding": _ordered(holdings, "fact_holding", catalog),
        "fact_asset_snapshot": _ordered(snapshots, "fact_asset_snapshot", catalog),
        "fact_transaction": _ordered(transactions, "fact_transaction", catalog),
        "fact_cash_flow": _ordered(flows, "fact_cash_flow", catalog),
    }


def _check_scale(scale: str) -> None:
    if scale not in SUPPORTED_SCALES:
        supported = ", ".join(sorted(SUPPORTED_SCALES))
        raise ValueError(f"scale {scale!r} is not supported yet; only {supported!r} exists")


def generate_dataset(config: GenerationConfig, output_dir: Path) -> tuple[dict, dict]:
    """Build a scale dataset and publish manifest, quality report and config snapshot."""
    _check_scale(config.scale)
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite dataset directory: {output_dir}")
    catalog = load_catalog()
    rows = _build_rows(config)
    output_dir.mkdir(parents=True, exist_ok=False)
    conn = duckdb.connect(str(output_dir / DATABASE_NAME))
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute(render_ddl(catalog))
        for table, values in rows.items():
            _bulk_insert(conn, table, values)
        row_counts = {
            table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in rows
        }
        content_hashes = {
            table: digest(
                sorted(conn.execute(f'SELECT * FROM "{table}"').fetchall(), key=json_text)
            )
            for table in rows
        }
        checks = run_quality_checks(conn, config)
        quality = QualityReport(
            seed=config.seed,
            anchor_date=config.anchor_date,
            scale=config.scale,
            checks=checks,
            passed_count=sum(1 for check in checks if check.passed),
            failed_count=sum(1 for check in checks if not check.passed),
            all_passed=all(check.passed for check in checks),
        ).model_dump(mode="json")
        write_json_new(output_dir / QUALITY_REPORT_NAME, quality)
        if not quality["all_passed"]:
            failed = [c["check_id"] for c in quality["checks"] if not c["passed"]]
            raise ValueError(f"quality checks failed: {failed}")
        manifest = DatasetManifest(
            artifact_kind=ARTIFACT_KIND[config.scale],
            snapshot_version=SNAPSHOT_VERSION[config.scale],
            scale=config.scale,
            seed=config.seed,
            anchor_date=config.anchor_date,
            config_hash=digest(config.model_dump(mode="json")),
            catalog_hash=digest(catalog.model_dump(mode="json")),
            row_counts=row_counts,
            content_hashes=content_hashes,
            quality_report_hash=digest(quality),
            environment={name: version(name) for name in ("duckdb", "pydantic")},
        ).model_dump(mode="json")
        conn.execute("COMMIT")
        conn.execute("CHECKPOINT")
    finally:
        conn.close()
    write_json_new(output_dir / MANIFEST_NAME, manifest)
    write_json_new(output_dir / CONFIG_SNAPSHOT_NAME, config.model_dump(mode="json"))
    return manifest, quality


def load_generation_config(
    path: Path, scale: str | None = None, seed: int | None = None
) -> GenerationConfig:
    """Load configs/data_generation.yaml; CLI arguments override file values."""
    from customer360.contracts.generation import SCALE_PRESETS, SIZE_KEYS

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    chosen = scale if scale is not None else raw.get("scale", "tiny")
    _check_scale(chosen)
    merged = dict(SCALE_PRESETS[chosen])
    for key, value in raw.items():
        if key == "scale":
            continue
        if chosen != "tiny" and key in SIZE_KEYS:
            continue
        merged[key] = value
    merged["scale"] = chosen
    if seed is not None:
        merged["seed"] = seed
    return GenerationConfig.model_validate(merged)
