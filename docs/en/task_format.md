# Protocol and Task Format 0.1

[English](task_format.md) | [简体中文](../task_format.md)

For execution instructions, refer to the [User Guide](user-guide.md). This document defines public/private contracts and the current semantic DSL. Python type annotations serve as the authoritative reference; Pydantic models reject undeclared fields and invalid state combinations. Official local scoring is driven by `c360 score` (score protocol 1.0), rather than an online competition submission portal.

## Public Input vs. Private Oracle

`AgentRequest` contains only `case_id`, `question`, `anchor_date`, `metadata_version`, `protocol_version`, and `conversation`. It must never include `expected_action`, `semantic_spec`, Gold SQL, `missing_slots`, or hidden random seeds.

`PrivateCase` belongs exclusively to the trusted evaluator. Its `CaseOracle` is a tagged union discriminated by `expected_action`:

- `answer`: Contains a `SemanticSpec`.
- `clarification_needed`: Contains a scripted `SlotReply` list, optional multi-turn `ClarificationTurn` definitions, and the resolved `SemanticSpec` once slots are completed.
- `refuse`: Contains an allowed `reason_code`; no SQL is expected.

Evaluator 0.5 supports multi-turn scripted replay and execution auditing for answer, clarification, and refusal actions. The formal evaluation pipeline is upgraded to Evaluator 0.6 and Score Protocol 1.0 (`c360 evaluate-public` and `c360 evaluate-hidden --formal` produce formal inputs, which `c360 score` evaluates to generate separate weighted scores and hard gate reports for `public_dev` and `private_hidden`). Clarification requests are replayed turn-by-turn using hidden `ClarificationTurn` scripts, validating the final controlled query while auditing all turns, responses, tool calls, and receipts. Refusals are validated against specific reason codes. Zero-contribution reference queries record `POLICY_INCOMPATIBLE`. The official Baseline runner is the local `BaselineAgent` (`--agent baseline`).

The packaged `resources/human_cases.yaml` provides the public question prompts for 20 cases (`catalog_version: 0.3`, `task_version: human-0.1`, `split: dev`): only `case_id`, canonical question, and 3 paraphrases. The corresponding semantic specs, expected actions, missing slots, slot replies, and refusal reason codes are stored in `data/trusted/human_oracles.yaml` within the repository and are never bundled into wheels or passed to agents. Paraphrases are verified on the trusted side via `c360 check-rewrites --oracles data/trusted/human_oracles.yaml`. Semantic drifts are classified into stable error categories (`TIME_RANGE_ERROR`, `METRIC_ERROR`, `FILTER_ERROR`, `JOIN_ERROR`). Gold queries for the 18 answerable cases are compiled directly from semantic specs; clarification and refusal cases have unscored oracles. `C360_0001–0020` must never be relabeled as train, test, private, or hidden.

Generated task packs (M3) are separated from the 20-case baseline pack: `c360 generate-tasks --count 120 --seed 42` produces a development pack (`case_id` starting at `C360_1001`). `--count 300` generates the M6 public structure (180 train / 120 generated-dev). A `family_id` is derived from the template, metric, join, temporal semantics, filter signatures, grouping, and expected action; paraphrases share family IDs and do not count as new tasks. Train and dev splits never share family IDs.

The hidden benchmark set is an independent pack generated via `c360 generate-hidden --public-pack <public_pack> --count 30` (writing `case_id` starting at `C360_4001`, `split=private`). Its family IDs must never overlap with human cases or public train/dev cases. Public question prompts are written to `agent_cases.yaml`, while oracles reside in `hidden_oracles.yaml`. Hidden datasets are Tiny datasets carrying a `hidden_profile.json` (default seed 1042, seeds 42 and 43 prohibited).

Semantic verification (`c360 verify-pack`) validates compiled SQL against independent Python calculation oracles and verifies that 8 classes of erroneous SQL queries are distinguished on bound datasets. Public summaries only disclose task counts and `semantic_passed`; Gold SQL, specs, and seeds remain under `private/verify.json`.

Four frozen Tiny data variants are supported: `tiny_seed_43_distribution`, `tiny_duplicate_fanout`, `tiny_null_empty_groups`, and `tiny_date_boundary`. Replay across variants via `c360 replay-variant --mode same_sql` checks that compiled queries yield consistent results with the Python oracle across data variants while requiring at least one query to change results relative to the baseline.

## Semantic DSL Specification

~~~json
{
  "semantic_version": "0.1",
  "metric": "successful_transaction_count",
  "filters": [],
  "time_window": {
    "type": "rolling",
    "days": 90,
    "anchor_date": "2025-06-30"
  }
}
~~~

The default query pattern is single-metric, single-table. The only supported join is the fixed path `customer_transactions`: `dim_customer.customer_id` joined with `fact_transaction.customer_id`, supporting customer distinct counts with customer-side and transaction-side filters, where transaction filters require an explicit rolling window. `group_by` is currently restricted to `active_customer_count` grouped by `region`; output includes group keys and metric values, without zero-filling empty groups, and comparisons use unordered multisets.

`time_window` supports three distinct modes:
1. `rolling`: Rolling day window backwards from an anchor date.
2. `latest_snapshot`: For `latest_total_asset`, computing `MAX(snapshot_date) <= anchor` per customer before aggregation.
3. `point_in_time`: Exact valuation snapshot date.

Latest snapshot example:

~~~json
{
  "semantic_version": "0.1",
  "metric": "latest_total_asset",
  "time_window": {
    "type": "latest_snapshot",
    "anchor_date": "2025-06-30"
  }
}
~~~

Point-in-time snapshot example:

~~~json
{
  "semantic_version": "0.1",
  "metric": "snapshot_total_asset",
  "filters": [],
  "time_window": {
    "type": "point_in_time",
    "snapshot_date": "2025-06-30"
  }
}
~~~

Filters specify `field`, `operator`, and `values`. Supported operators: `eq`, `ne`, `gte`, `lte`, `in`, `is_null`, and `is_not_null`. Null checks use dedicated operators, `in` requires non-empty value lists, and literal types must strictly match column schemas.

## Agent Protocol Integration

Agents implement `Agent.respond(request, tools)` in `agent/protocol.py`. Available tools:
- `execute_sql`
- `search_tables`
- `search_columns`
- `search_metrics`
- `get_table_schema`
- `get_metric_definition`
- `get_business_glossary`
- `get_join_paths`

`execute_sql` returns a `QueryReceipt` containing a unique `query_id`, structured results, and execution latency (`elapsed_ms`). Successful responses must supply the matching `query_id`, the exact SQL submitted, the final answer text, and a confidence score.

Four valid Agent response statuses:
- `success`
- `clarification_needed`: Non-empty list of questions and deduplicated `requested_slots`.
- `refused`: Machine-readable `reason_code`, human explanation `reason`, and optional `alternative`.
- `error`: Operational runtime failure (never counted as a correct refusal).

The official baseline is `BaselineAgent`: it queries authorized metadata, generates plans via an offline `LocalDeterministicAdapter`, compiles candidate SQL, and executes via the gateway.

## Structured Result Contract

`QueryResult.columns` declares names and data kinds; `rows` contains row values matching column positions. Supported kinds: `string`, `integer`, `decimal`, `date`, `boolean`. Decimals are serialized as strings to preserve precision; dates use ISO `YYYY-MM-DD`. `NULL` is serialized as JSON `null`. `truncated` indicates whether row limits were reached.

~~~json
{
  "columns": [{"name": "transaction_amount", "kind": "decimal"}],
  "rows": [["650.00"]],
  "truncated": false
}
~~~

Truncated results, mismatched column names/types, missing execution receipts, or receipts whose executed SQL differs from candidate SQL will cause the evaluation to fail.
