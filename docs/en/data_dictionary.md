# Data Dictionary and Business Definitions

[English](data_dictionary.md) | [简体中文](../data_dictionary.md)

For data generation instructions across Tiny, Standard, and Large scales, see the [User Guide](user-guide.md). The authoritative source for column names, data types, nullability, sensitivity classifications, primary keys, unique constraints, and foreign keys is `src/customer360/resources/catalog.yaml`. Do not maintain a separate manual DDL file. Use `c360 schema` to inspect generated SQL DDL.

## Nine Tables and Granularities

| Table | Granularity / Key | Temporal Semantics and Relationships |
|---|---|---|
| `dim_customer` | `customer_id` PK | Current customer profile snapshot; `registration_date` is not an anchor for business queries |
| `dim_service_manager` | `manager_id` PK | Service manager dimension table; global unrestricted table scans are denied |
| `dim_product` | `product_id` PK | Product dimension table; initial data is standardized to CNY |
| `fact_service_relation` | `UNIQUE(customer_id, manager_id, start_date, relation_type)` | Customer and manager FKs; service interval defined as `[start_date, end_date)`, NULL end indicates ongoing |
| `dim_date` | `date_id` PK | `calendar_date` maps to calendar date; generator covers all 365 days from 2024-07-01 to 2025-06-30 (toy fixture only contains 3 sample dates) |
| `fact_holding` | `UNIQUE(snapshot_date, customer_id, product_id)` | Customer and product FKs; asset holdings on a specified valuation snapshot date |
| `fact_asset_snapshot` | `UNIQUE(snapshot_date, customer_id)` | Customer FK; customer asset summary on a specified valuation date |
| `fact_transaction` | `transaction_id` PK | Customer and product FKs; filtered by `transaction_date` |
| `fact_cash_flow` | `flow_id` PK | Customer FK; filtered by `flow_date` |

Database constraints enforce primary keys, unique keys, nullability, and 8 direct foreign keys. Complex business constraints (e.g., non-overlapping service manager assignments) are checked by 60 named quality assertions in `synth/constraints.py` during generation; any failure aborts publication of the dataset manifest.

## Semantic Standards

- Dates use SQL `DATE`. The system's current time is never used for business logic. The default smoke anchor date is fixed at `2025-06-30`.
- "Last N days" is defined as `[anchor - (N - 1), anchor]`, inclusive on both ends. For example, "last 90 days" starts on `2025-04-02`.
- Service intervals are half-open intervals `[start_date, end_date)`. A customer may have at most one primary service manager on any given date.
- Financial amounts and quantities use `DECIMAL(24, 2)` rather than floating-point numbers. Initial synthetic datasets are uniformly denominated in CNY.
- `amount` represents a non-negative transaction amount; transaction direction is indicated by `transaction_type`. The sum of transaction amounts does not equate to net inflow or net profit.
- Customer statuses: `active`, `dormant`, `closed`. Customer tiers: `VIP`, `standard`.
- Transaction statuses: `success`, `cancelled`, `failed`. Business metrics count only `success`.
- Cash flows: `in` is positive, `out` is negative. Net cash flow sums `signed_amount`.
- Asset balance invariant: `total_asset = cash_asset + investment_asset` and `net_asset = total_asset - liability`. Holdings are not assumed to cover 100% of investment assets.
- `age` is a derived value calculated from `birth_date` and an explicit target date, not an entity table column.
- Restricted columns: `customer_name`, `birth_date`, `manager_name`. Financial columns require authorization and minimum aggregation compliance.
- `phone` and `id_card` do NOT exist. "Column does not exist" and "column exists but is restricted" are distinct test cases that must not be conflated. `MetadataRepository` rejects datasets declaring these columns.
- The business glossary tool (`get_business_glossary`) returns only declared names and aliases from tables, columns, and metrics. It does not hallucinate definitions for undefined colloquial terms.

## Thirty Defined Metrics

| Technical Name | Output Column | Metric Definition |
|---|---|---|
| `distinct_customer_count` | `customer_count INTEGER` | Distinct count of `customer_id`; includes closed customers unless `status=active` is explicitly filtered; no time window; allows filtering on `occupation` (including `IS NULL`) |
| `active_customer_count` | `active_customer_count INTEGER` | Distinct count of customers with `status=active` (excludes dormant/closed) |
| `successful_transaction_count` | `transaction_count INTEGER` | Count of successful transactions within a rolling window (`status=success`) |
| `successful_transaction_amount` | `transaction_amount DECIMAL` | Sum of amounts for successful transactions within the window (no fee deductions, no buy/sell offsetting) |
| `failed_transaction_count` | `failed_transaction_count INTEGER` | Count of failed transactions (`status=failed`) within the rolling window |
| `successful_net_cash_flow` | `net_cash_flow DECIMAL` | Sum of `signed_amount` for successful cash flows within the window |
| `successful_cash_inflow` | `cash_inflow DECIMAL` | Sum of `signed_amount` for successful inflows (`flow_type=in`) within the window |
| `current_primary_service_relation_count` | `primary_service_relation_count INTEGER` | Count of active primary relations (`is_primary=TRUE` and `end_date IS NULL`) |
| `snapshot_total_asset` | `total_asset DECIMAL` | Sum of `total_asset` on a specific `snapshot_date`; requires explicit valuation date |
| `snapshot_net_asset` | `net_asset DECIMAL` | Sum of `net_asset` on a specific `snapshot_date`; requires explicit valuation date |
| `latest_total_asset` | `latest_total_asset DECIMAL` | Sum of each customer's most recent `total_asset` on or before the anchor date |
| `closed_customer_count` | `closed_customer_count INTEGER` | Distinct count of customers with `status=closed` |
| `dormant_customer_count` | `dormant_customer_count INTEGER` | Distinct count of customers with `status=dormant` |
| `high_risk_customer_count` | `high_risk_customer_count INTEGER` | Distinct count of customers with `risk_level=high` |
| `cancelled_transaction_count` | `cancelled_transaction_count INTEGER` | Count of cancelled transactions within the window |
| `cancelled_transaction_amount` | `cancelled_transaction_amount DECIMAL` | Sum of amounts for cancelled transactions within the window |
| `failed_transaction_amount` | `failed_transaction_amount DECIMAL` | Sum of amounts for failed transactions within the window |
| `successful_buy_transaction_count` | `successful_buy_transaction_count INTEGER` | Count of successful buy orders within the window |
| `successful_app_transaction_count` | `successful_app_transaction_count INTEGER` | Count of successful app-channel transactions within the window |
| `successful_cash_outflow` | `cash_outflow DECIMAL` | Sum of `signed_amount` for successful outflows within the window (negative) |
| `successful_cash_flow_count` | `cash_flow_count INTEGER` | Count of successful cash flows within the window |
| `snapshot_holding_market_value` | `holding_market_value DECIMAL` | Total market value of holdings on a specified valuation date |
| `snapshot_holding_cost_value` | `holding_cost_value DECIMAL` | Total cost value of holdings on a specified valuation date |
| `snapshot_holding_unrealized_profit` | `holding_unrealized_profit DECIMAL` | Total unrealized profit of holdings on a specified valuation date |
| `snapshot_holding_count` | `holding_count INTEGER` | Total number of holding records on a specified valuation date |
| `snapshot_active_holding_count` | `active_holding_count INTEGER` | Number of active holdings (`holding_status=active`) on a specified valuation date |
| `snapshot_cash_asset` | `cash_asset DECIMAL` | Total cash assets on a specified valuation date |
| `snapshot_investment_asset` | `investment_asset DECIMAL` | Total investment assets on a specified valuation date |
| `snapshot_liability` | `liability DECIMAL` | Total liabilities on a specified valuation date |
| `current_service_relation_count` | `service_relation_count INTEGER` | Count of active relations (`end_date IS NULL`), primary or secondary |

All metrics specify version, description, granularity, deduplication/null rules, fixed filters, allowed filters, prohibited scenarios, and example prompts in `resources/metrics.yaml` (`metrics_version=0.3`). The 20 audited join paths are listed in `resources/join_paths.yaml`; only `customer_transactions` is executable in v1.0. Point-in-time metrics use `{"type": "point_in_time", "snapshot_date": "..."}`; latest-snapshot metrics use `{"type": "latest_snapshot", "anchor_date": "..."}`. They cannot be swapped with rolling windows and do not compile to window functions. `active_customer_count` supports grouping by `region`.

## Public Fixture vs. Tiny Dataset

The toy fixture comprises 6 customers, 3 managers, 3 products, 4 relations, 3 dates, 2 holdings, 3 asset snapshots, 7 transactions, and 3 cash flows. It is intended only for basic pipeline sanity tests:

- VIP customers: C001, C003, C006 (total 3).
- Last 90 days successful transactions: T001–T004 (total 4).
- Amount: 100 + 200 + 50 + 300 = 650.00 CNY.
- T005 is outside the window, T006 failed, T007 cancelled.
- C006 has zero transactions. The sample includes customers with no holdings, NULL occupations, and historical service relationships.

Changing the seed in the toy fixture only offsets asset values for C001; core verification figures remain unchanged. Never claim that the toy fixture satisfies statistical distributions, snapshot coverage, or the 60 quality assertions required of Tiny datasets.

## Tiny Generator Specifications

The synthetic data generator (`synth/generator.py` with `configs/data_generation.yaml`) satisfies:

- Tiny scale is strictly 100 customers, 2,000 transactions, 10 managers, 8 products, and 800 cash flows (prefixed `C001`, `T0001`). Standard is 10,000 / 300,000; Large is 100,000 / 3,000,000.
- Customers with zero transactions, zero holdings, and empty occupations must meet minimum thresholds: at least 5%, 5%, and 3% respectively. Standard defaults to 500 / 500 / 300; Large defaults to 5,000 / 5,000 / 3,000 (`standard-v2` / `large-v2`). Tiny maintains 5 / 5 / 3 (`tiny-v1`).
- Anchor date is `2025-06-30`. All business dates fall within `[2024-07-01, 2025-06-30]`, and `dim_date` covers every single day (365 rows).
- Asset snapshots cover 7 month-end valuation dates (`2024-12-31` to `2025-06-30`) across all customers. Accounting invariants hold row by row.
- Exactly 5 customers have no transactions, 5 have no holdings (investment assets equal 0.00), and 3 have NULL occupations. VIP assets have a higher mean than standard tiers but maintain realistic distribution overlap.
- Transaction status quotas ensure `success`, `failed`, and `cancelled` all occur. Boundaries of the 90-day window (`2025-04-01` day before, `2025-04-02` start, and `2025-06-30` anchor) all contain successful transactions with duplicate amounts.
- Cash flows: `in` is positive, `out` is negative, status is `success`. Service relations guarantee at least one primary manager per customer, with non-overlapping intervals.
- Identical seed, configuration, and version generate identical normalized content digests (`generator_version=0.1.0`, `snapshot_version=tiny-v1`). Seeds affect business values but do not alter calendar dates.

## T3 Tiny Boundary Probes

The M2 dev case pack does not generate new data; it reads boundary probes from Tiny and verifies 20 versioned cases against an independent Python oracle:

- Boundaries of the 90-day window: An extra day before (`2025-04-01`), start date (`2025-04-02`), and anchor date (`2025-06-30`) have successful transactions. Shifting the window outside these dates yields 0.
- Customers with empty occupations match configuration (default 3); zero-transaction and zero-holding customers match configuration.
- Failed and cancelled transactions occur simultaneously; `cancelled` transactions are never counted as `failed` or `success`.
- Valuation snapshot dates match configuration; querying a snapshot requires equality filtering. Asset totals on `2024-12-31` and `2025-06-30` cannot be interchanged.
- Terminated and secondary relations exist, so `end_date IS NULL` and `is_primary` alter counts.
- `customer_name` is restricted; `phone` and `id_card` do not exist in the catalog.
- Region grouping and latest snapshot are supported in compiled Gold (`C360_0018` / `C360_0017`); other joins and window functions remain rejected.
