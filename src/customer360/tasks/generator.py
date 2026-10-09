"""Deterministic M3 task pack generator. Gold is compiled later; this emits specs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from random import Random

import yaml

from customer360.artifacts import write_json_new
from customer360.contracts.family import (
    ERROR_CLASSES_REQUIRED,
    M6_PUBLIC_COUNT,
    PUBLIC_GENERATED_ID_MAX,
)
from customer360.contracts.oracle import SlotReply
from customer360.contracts.pack import (
    GeneratedCaseBlueprint,
    GeneratedTaskPack,
    PublicGeneratedCase,
    PublicGeneratedCatalog,
    TrustedGeneratedCatalog,
    TrustedGeneratedOracle,
)
from customer360.contracts.semantic import (
    Filter,
    JoinSpec,
    LatestSnapshot,
    PointInTime,
    RollingWindow,
)
from customer360.metadata.metrics import MetadataRepository, MetricDef
from customer360.tasks.catalog import load_human_cases
from customer360.tasks.family import fingerprint_for, fingerprint_human_case
from customer360.tasks.isolation import check_generated_isolation

ANCHOR = date(2025, 6, 30)
ROLLING = RollingWindow(days=90, anchor_date=ANCHOR)
PIT = PointInTime(snapshot_date=ANCHOR)
LATEST = LatestSnapshot(anchor_date=ANCHOR)
REGIONS = ("华东", "华北", "华南", "西南")
GENDERS = ("M", "F")
LEVELS = ("VIP", "standard")
RISKS = ("low", "medium", "high")
STATUSES = ("active", "dormant", "closed")
TX_TYPES = ("buy", "sell", "subscribe", "redeem")
TX_CHANNELS = ("app", "branch")
FLOW_CHANNELS = ("bank", "app", "branch")
FLOW_TYPES = ("in", "out")
ROLLING_DAYS = (30, 90, 180)
EXTRA_PIT_DATES = (
    date(2024, 12, 31),
    date(2025, 1, 31),
    date(2025, 2, 28),
    date(2025, 3, 31),
    date(2025, 4, 30),
    date(2025, 5, 31),
)
TRAIN_COUNT = 90
TRAIN_COUNT_M6 = 180
REQUIRED_COUNT = 8
DEFAULT_COUNT = 120


@dataclass(frozen=True)
class Draft:
    expected_action: str
    category: str
    material_status: str
    intended_failure_class: str
    metric: str | None = None
    filters: tuple[Filter, ...] = ()
    time_window: RollingWindow | PointInTime | LatestSnapshot | None = None
    join: JoinSpec | None = None
    group_by: tuple[str, ...] = ()
    missing_slots: tuple[str, ...] = ()
    slot_replies: tuple[SlotReply, ...] = ()
    accepted_reason_codes: tuple[str, ...] = ()


def _window_for(
    metric: MetricDef, *, days: int = 90
) -> RollingWindow | PointInTime | LatestSnapshot | None:
    if metric.time_semantics == "rolling_required":
        return RollingWindow(days=days, anchor_date=ANCHOR)
    if metric.time_semantics == "point_in_time_required":
        return PIT
    if metric.time_semantics == "latest_snapshot_required":
        return LATEST
    return None


def _rolling_windows(metric: MetricDef) -> tuple[RollingWindow, ...]:
    if metric.time_semantics != "rolling_required":
        return ()
    return tuple(RollingWindow(days=days, anchor_date=ANCHOR) for days in ROLLING_DAYS)


def _category_for(draft: Draft) -> str:
    return draft.category


def _plain_category(metric: MetricDef) -> str:
    if metric.operation == "sum":
        return "aggregation"
    return "single_table"


def _join_spec(*, extra: tuple[Filter, ...] = (), days: int = 90) -> JoinSpec:
    return _join_spec_path("customer_transactions", extra=extra, days=days)


def _join_spec_path(
    path: str,
    *,
    extra: tuple[Filter, ...] = (),
    days: int = 90,
    window: RollingWindow | PointInTime | None = None,
) -> JoinSpec:
    if path == "customer_transactions":
        tw = window or RollingWindow(days=days, anchor_date=ANCHOR)
        return JoinSpec(
            path=path,  # type: ignore[arg-type]
            filters=(Filter(field="status", operator="eq", values=("success",)), *extra),
            time_window=tw,
        )
    if path == "customer_cash_flows":
        tw = window or RollingWindow(days=days, anchor_date=ANCHOR)
        return JoinSpec(
            path=path,  # type: ignore[arg-type]
            filters=(Filter(field="status", operator="eq", values=("success",)), *extra),
            time_window=tw,
        )
    if path == "customer_holdings":
        tw = window or PIT
        return JoinSpec(
            path=path,  # type: ignore[arg-type]
            filters=(Filter(field="holding_status", operator="eq", values=("active",)), *extra),
            time_window=tw,
        )
    if path == "customer_asset_snapshots":
        tw = window or PIT
        return JoinSpec(
            path=path,  # type: ignore[arg-type]
            filters=extra,
            time_window=tw,
        )
    if path == "customer_service_relations":
        return JoinSpec(
            path=path,  # type: ignore[arg-type]
            filters=extra or (Filter(field="is_primary", operator="eq", values=(True,)),),
        )
    raise ValueError(f"unsupported join path: {path}")


def fingerprint_draft(draft: Draft):
    return fingerprint_for(
        expected_action=draft.expected_action,
        metric=draft.metric,
        filters=draft.filters,
        time_window=draft.time_window,
        join=draft.join,
        group_by=draft.group_by,
        missing_slots=draft.missing_slots,
        accepted_reason_codes=draft.accepted_reason_codes,
    )


def _fingerprint(draft: Draft):
    return fingerprint_draft(draft)


def _required_drafts() -> tuple[Draft, ...]:
    return (
        Draft(
            expected_action="answer",
            category="time_window",
            material_status="compilable_answer",
            intended_failure_class="TIME_RANGE_ERROR",
            metric="cancelled_transaction_count",
            time_window=ROLLING,
        ),
        Draft(
            expected_action="answer",
            category="join",
            material_status="compilable_answer",
            intended_failure_class="JOIN_ERROR",
            metric="distinct_customer_count",
            filters=(Filter(field="region", operator="eq", values=("华东",)),),
            join=_join_spec(),
        ),
        Draft(
            expected_action="answer",
            category="join",
            material_status="compilable_answer",
            intended_failure_class="DUPLICATE_COUNT_ERROR",
            metric="distinct_customer_count",
            filters=(Filter(field="customer_level", operator="eq", values=("standard",)),),
            join=_join_spec(),
        ),
        Draft(
            expected_action="answer",
            category="null_handling",
            material_status="compilable_answer",
            intended_failure_class="NULL_HANDLING_ERROR",
            metric="current_service_relation_count",
        ),
        Draft(
            expected_action="answer",
            category="customer_filter",
            material_status="compilable_answer",
            intended_failure_class="FILTER_ERROR",
            metric="distinct_customer_count",
            filters=(Filter(field="region", operator="eq", values=("华南",)),),
        ),
        Draft(
            expected_action="answer",
            category="aggregation",
            material_status="compilable_answer",
            intended_failure_class="METRIC_ERROR",
            metric="failed_transaction_amount",
            time_window=ROLLING,
        ),
        Draft(
            expected_action="refuse",
            category="refuse",
            material_status="unscored_oracle",
            intended_failure_class="PERMISSION_ERROR",
            accepted_reason_codes=("PERMISSION_DENIED",),
        ),
        Draft(
            expected_action="clarification_needed",
            category="clarification",
            material_status="unscored_oracle",
            intended_failure_class="CLARIFICATION_FAILURE",
            metric="successful_transaction_amount",
            time_window=ROLLING,
            missing_slots=("time_window",),
            slot_replies=(SlotReply(slot="time_window", reply="截至2025-06-30的近90个自然日"),),
        ),
    )


def _customer_filters(metric: MetricDef) -> tuple[tuple[Filter, ...], ...]:
    allowed = set(metric.allowed_filter_columns) - set(metric.fixed_filters)
    combinations: list[tuple[Filter, ...]] = [()]
    if "customer_level" in allowed:
        combinations.extend(
            (Filter(field="customer_level", operator="eq", values=(level,)),) for level in LEVELS
        )
    if "region" in allowed:
        combinations.extend(
            (Filter(field="region", operator="eq", values=(region,)),) for region in REGIONS
        )
    if "gender" in allowed:
        combinations.extend(
            (Filter(field="gender", operator="eq", values=(gender,)),) for gender in GENDERS
        )
    if "risk_level" in allowed:
        combinations.extend(
            (Filter(field="risk_level", operator="eq", values=(risk,)),) for risk in RISKS
        )
    if "status" in allowed:
        combinations.extend(
            (Filter(field="status", operator="eq", values=(status,)),) for status in STATUSES
        )
    if "occupation" in allowed:
        combinations.append((Filter(field="occupation", operator="is_null"),))
        if "region" in allowed:
            combinations.extend(
                (
                    Filter(field="occupation", operator="is_null"),
                    Filter(field="region", operator="eq", values=(region,)),
                )
                for region in REGIONS
            )
        if "customer_level" in allowed:
            combinations.extend(
                (
                    Filter(field="occupation", operator="is_null"),
                    Filter(field="customer_level", operator="eq", values=(level,)),
                )
                for level in LEVELS
            )
    if "transaction_type" in allowed:
        combinations.extend(
            (Filter(field="transaction_type", operator="eq", values=(kind,)),) for kind in TX_TYPES
        )
    if "channel" in allowed:
        channels = FLOW_CHANNELS if metric.source_table == "fact_cash_flow" else TX_CHANNELS
        combinations.extend(
            (Filter(field="channel", operator="eq", values=(channel,)),) for channel in channels
        )
    if "flow_type" in allowed:
        combinations.extend(
            (Filter(field="flow_type", operator="eq", values=(kind,)),) for kind in FLOW_TYPES
        )
    if "is_primary" in allowed:
        combinations.append((Filter(field="is_primary", operator="eq", values=(True,)),))
        combinations.append((Filter(field="is_primary", operator="eq", values=(False,)),))
    if "relation_type" in allowed:
        combinations.extend(
            (Filter(field="relation_type", operator="eq", values=(kind,)),)
            for kind in ("exclusive", "shared")
        )
    return tuple(combinations)


def _failure_class_for(
    metric: MetricDef,
    filters: tuple[Filter, ...],
    window: RollingWindow | PointInTime | LatestSnapshot | None,
) -> str:
    if any(item.operator == "is_null" for item in filters):
        return "NULL_HANDLING_ERROR"
    if filters:
        return "FILTER_ERROR"
    if window is not None:
        return "TIME_RANGE_ERROR"
    if metric.operation == "sum":
        return "METRIC_ERROR"
    return "METRIC_ERROR"


def _pool_drafts(repository: MetadataRepository) -> list[Draft]:
    drafts: list[Draft] = []
    for metric in repository.metrics.metrics:
        if metric.metric_name == "latest_total_asset":
            drafts.append(
                Draft(
                    expected_action="answer",
                    category="latest_snapshot",
                    material_status="compilable_answer",
                    intended_failure_class="TIME_RANGE_ERROR",
                    metric=metric.metric_name,
                    time_window=LATEST,
                )
            )
            drafts.append(
                Draft(
                    expected_action="clarification_needed",
                    category="clarification",
                    material_status="unscored_oracle",
                    intended_failure_class="CLARIFICATION_FAILURE",
                    metric=metric.metric_name,
                    time_window=LATEST,
                    missing_slots=("time_window",),
                    slot_replies=(
                        SlotReply(slot="time_window", reply="截至2025-06-30的最新资产快照"),
                    ),
                )
            )
            continue
        win = _window_for(metric)
        for dim in metric.allowed_group_dimensions:
            drafts.append(
                Draft(
                    expected_action="answer",
                    category="grouping",
                    material_status="compilable_answer",
                    intended_failure_class="AGGREGATION_ERROR",
                    metric=metric.metric_name,
                    time_window=win,
                    group_by=(dim,),
                )
            )
            # 带基础条件的分组组合
            allowed = set(metric.allowed_filter_columns) - set(metric.fixed_filters)
            if "customer_level" in allowed and dim != "customer_level":
                for level in ("VIP", "standard"):
                    lvl_filter = Filter(field="customer_level", operator="eq", values=(level,))
                    drafts.append(
                        Draft(
                            expected_action="answer",
                            category="grouping",
                            material_status="compilable_answer",
                            intended_failure_class="AGGREGATION_ERROR",
                            metric=metric.metric_name,
                            filters=(lvl_filter,),
                            time_window=win,
                            group_by=(dim,),
                        )
                    )
            if "region" in allowed and dim != "region":
                for region in ("华东", "华北"):
                    drafts.append(
                        Draft(
                            expected_action="answer",
                            category="grouping",
                            material_status="compilable_answer",
                            intended_failure_class="AGGREGATION_ERROR",
                            metric=metric.metric_name,
                            filters=(Filter(field="region", operator="eq", values=(region,)),),
                            time_window=win,
                            group_by=(dim,),
                        )
                    )
        windows: tuple[RollingWindow | PointInTime | LatestSnapshot | None, ...]
        if metric.time_semantics == "rolling_required":
            windows = _rolling_windows(metric)
        elif metric.time_semantics == "point_in_time_required":
            windows = (PIT, *(PointInTime(snapshot_date=item) for item in EXTRA_PIT_DATES))
        else:
            windows = (None,)
        for window in windows:
            for filters in _customer_filters(metric):
                category = _plain_category(metric)
                if isinstance(window, RollingWindow):
                    category = "time_window"
                elif isinstance(window, PointInTime):
                    category = "point_in_time"
                if any(item.operator == "is_null" for item in filters):
                    category = "null_handling"
                elif filters:
                    category = "customer_filter"
                drafts.append(
                    Draft(
                        expected_action="answer",
                        category=category,
                        material_status="compilable_answer",
                        intended_failure_class=_failure_class_for(metric, filters, window),
                        metric=metric.metric_name,
                        filters=filters,
                        time_window=window,
                    )
                )
        allowed = set(metric.allowed_filter_columns) - set(metric.fixed_filters)
        combos: list[tuple[Filter, ...]] = [()]
        if "customer_level" in allowed:
            combos.extend(
                [
                    (Filter(field="customer_level", operator="eq", values=("VIP",)),),
                    (Filter(field="customer_level", operator="eq", values=("standard",)),),
                ]
            )
        if "region" in allowed:
            combos.extend(
                [
                    (Filter(field="region", operator="eq", values=("华东",)),),
                    (Filter(field="region", operator="eq", values=("华北",)),),
                ]
            )
        if "channel" in allowed:
            combos.extend(
                [
                    (Filter(field="channel", operator="eq", values=("app",)),),
                    (Filter(field="channel", operator="eq", values=("branch",)),),
                ]
            )
        if "transaction_type" in allowed:
            combos.extend(
                [
                    (Filter(field="transaction_type", operator="eq", values=("buy",)),),
                    (Filter(field="transaction_type", operator="eq", values=("sell",)),),
                ]
            )

        if metric.time_semantics == "rolling_required" or (
            metric.time_semantics == "none"
            and metric.source_table in {"fact_transaction", "fact_cash_flow"}
        ):
            for days, cn_window in ((90, "近90个自然日"), (30, "近30个自然日")):
                for flt in combos:
                    drafts.append(
                        Draft(
                            expected_action="clarification_needed",
                            category="clarification",
                            material_status="unscored_oracle",
                            intended_failure_class="CLARIFICATION_FAILURE",
                            metric=metric.metric_name,
                            filters=flt,
                            time_window=RollingWindow(days=days, anchor_date=ANCHOR),
                            missing_slots=("time_window",),
                            slot_replies=(
                                SlotReply(
                                    slot="time_window",
                                    reply=f"截至2025-06-30的{cn_window}",
                                ),
                            ),
                        )
                    )
        elif metric.time_semantics == "point_in_time_required":
            for flt in combos:
                drafts.append(
                    Draft(
                        expected_action="clarification_needed",
                        category="clarification",
                        material_status="unscored_oracle",
                        intended_failure_class="CLARIFICATION_FAILURE",
                        metric=metric.metric_name,
                        filters=flt,
                        time_window=PointInTime(snapshot_date=ANCHOR),
                        missing_slots=("time_window",),
                        slot_replies=(SlotReply(slot="time_window", reply="2025年6月30日"),),
                    )
                )
    # 1. customer_transactions
    for region in ("华北", "华南", "西南", "华东"):
        drafts.append(
            Draft(
                expected_action="answer",
                category="join",
                material_status="compilable_answer",
                intended_failure_class="JOIN_ERROR",
                metric="distinct_customer_count",
                filters=(Filter(field="region", operator="eq", values=(region,)),),
                join=_join_spec_path("customer_transactions"),
            )
        )
    for level in ("VIP", "standard"):
        drafts.append(
            Draft(
                expected_action="answer",
                category="join",
                material_status="compilable_answer",
                intended_failure_class="JOIN_ERROR",
                metric="distinct_customer_count",
                filters=(Filter(field="customer_level", operator="eq", values=(level,)),),
                join=_join_spec_path("customer_transactions"),
            )
        )
    for extra in (
        (Filter(field="channel", operator="eq", values=("app",)),),
        (Filter(field="channel", operator="eq", values=("branch",)),),
        (Filter(field="transaction_type", operator="eq", values=("buy",)),),
        (Filter(field="transaction_type", operator="eq", values=("sell",)),),
    ):
        drafts.append(
            Draft(
                expected_action="answer",
                category="join",
                material_status="compilable_answer",
                intended_failure_class="JOIN_ERROR",
                metric="distinct_customer_count",
                filters=(Filter(field="region", operator="eq", values=("西南",)),),
                join=_join_spec_path("customer_transactions", extra=extra),
            )
        )
    drafts.append(
        Draft(
            expected_action="answer",
            category="join",
            material_status="compilable_answer",
            intended_failure_class="DUPLICATE_COUNT_ERROR",
            metric="distinct_customer_count",
            filters=(Filter(field="region", operator="eq", values=("华北",)),),
            join=_join_spec_path("customer_transactions", days=30),
        )
    )

    # 2. customer_cash_flows
    for region in ("华东", "华北", "华南", "西南"):
        for flow_type in ("in", "out"):
            drafts.append(
                Draft(
                    expected_action="answer",
                    category="join",
                    material_status="compilable_answer",
                    intended_failure_class="JOIN_ERROR",
                    metric="distinct_customer_count",
                    filters=(Filter(field="region", operator="eq", values=(region,)),),
                    join=_join_spec_path(
                        "customer_cash_flows",
                        extra=(Filter(field="flow_type", operator="eq", values=(flow_type,)),),
                    ),
                )
            )
    for channel in ("app", "bank"):
        drafts.append(
            Draft(
                expected_action="answer",
                category="join",
                material_status="compilable_answer",
                intended_failure_class="JOIN_ERROR",
                metric="distinct_customer_count",
                filters=(Filter(field="customer_level", operator="eq", values=("VIP",)),),
                join=_join_spec_path(
                    "customer_cash_flows",
                    extra=(Filter(field="channel", operator="eq", values=(channel,)),),
                ),
            )
        )

    # 3. customer_holdings
    for region in ("华东", "华北", "华南", "西南"):
        drafts.append(
            Draft(
                expected_action="answer",
                category="join",
                material_status="compilable_answer",
                intended_failure_class="JOIN_ERROR",
                metric="distinct_customer_count",
                filters=(Filter(field="region", operator="eq", values=(region,)),),
                join=_join_spec_path("customer_holdings"),
            )
        )
    for level in ("VIP", "standard"):
        drafts.append(
            Draft(
                expected_action="answer",
                category="join",
                material_status="compilable_answer",
                intended_failure_class="JOIN_ERROR",
                metric="distinct_customer_count",
                filters=(Filter(field="customer_level", operator="eq", values=(level,)),),
                join=_join_spec_path("customer_holdings"),
            )
        )

    # 4. customer_asset_snapshots
    for region in ("华东", "华北", "华南", "西南"):
        drafts.append(
            Draft(
                expected_action="answer",
                category="join",
                material_status="compilable_answer",
                intended_failure_class="JOIN_ERROR",
                metric="distinct_customer_count",
                filters=(Filter(field="region", operator="eq", values=(region,)),),
                join=_join_spec_path("customer_asset_snapshots"),
            )
        )
    for level in ("VIP", "standard"):
        drafts.append(
            Draft(
                expected_action="answer",
                category="join",
                material_status="compilable_answer",
                intended_failure_class="JOIN_ERROR",
                metric="distinct_customer_count",
                filters=(Filter(field="customer_level", operator="eq", values=(level,)),),
                join=_join_spec_path("customer_asset_snapshots"),
            )
        )

    # 5. customer_service_relations
    for region in ("华东", "华北", "华南", "西南"):
        for is_prim in (True, False):
            drafts.append(
                Draft(
                    expected_action="answer",
                    category="join",
                    material_status="compilable_answer",
                    intended_failure_class="JOIN_ERROR",
                    metric="distinct_customer_count",
                    filters=(Filter(field="region", operator="eq", values=(region,)),),
                    join=_join_spec_path(
                        "customer_service_relations",
                        extra=(Filter(field="is_primary", operator="eq", values=(is_prim,)),),
                    ),
                )
            )

    # Refusal drafts (contextual filters for family separation, metric must be None)
    refuse_base = [
        (("PERMISSION_DENIED",), "PERMISSION_ERROR"),
        (("PERMISSION_DENIED", "UNSAFE_SQL"), "PERMISSION_ERROR"),
        (("UNKNOWN_FIELD",), "SCHEMA_ERROR"),
        (("UNKNOWN_METRIC",), "SCHEMA_ERROR"),
    ]
    refuse_contexts = [
        (),
        (Filter(field="region", operator="eq", values=("华东",)),),
        (Filter(field="region", operator="eq", values=("华北",)),),
        (Filter(field="region", operator="eq", values=("华南",)),),
        (Filter(field="region", operator="eq", values=("西南",)),),
        (Filter(field="customer_level", operator="eq", values=("VIP",)),),
        (Filter(field="customer_level", operator="eq", values=("standard",)),),
    ]
    for codes, f_class in refuse_base:
        for ctx in refuse_contexts:
            drafts.append(
                Draft(
                    expected_action="refuse",
                    category="refuse",
                    material_status="unscored_oracle",
                    intended_failure_class=f_class,
                    metric=None,
                    filters=ctx,
                    accepted_reason_codes=codes,
                )
            )
    return drafts


def _filter_label(filters: tuple[Filter, ...]) -> str:
    if not filters:
        return ""
    item = filters[0]
    if item.field == "customer_level" and item.values == ("VIP",):
        return "VIP"
    if item.field == "customer_level" and item.values == ("standard",):
        return "标准等级"
    if item.field == "region":
        return str(item.values[0])
    if item.field == "occupation" and item.operator == "is_null":
        return "职业为空"
    if item.field == "gender" and item.values == ("M",):
        return "男性"
    if item.field == "gender" and item.values == ("F",):
        return "女性"
    if item.field == "risk_level":
        return {"low": "低风险", "medium": "中风险", "high": "高风险"}[str(item.values[0])]
    if item.field == "status":
        return {"active": "在用", "dormant": "休眠", "closed": "已注销"}[str(item.values[0])]
    if item.field == "transaction_type":
        return {"buy": "买入", "sell": "卖出", "subscribe": "申购", "redeem": "赎回"}[
            str(item.values[0])
        ]
    if item.field == "channel":
        return {"app": "App渠道", "branch": "网点渠道", "bank": "银行渠道"}[str(item.values[0])]
    if item.field == "flow_type":
        return {"in": "流入", "out": "流出"}[str(item.values[0])]
    if item.field == "is_primary" and item.values == (True,):
        return "主服务标记"
    if item.field == "is_primary" and item.values == (False,):
        return "非主服务标记"
    if item.field == "relation_type":
        return {"exclusive": "独占型", "shared": "共享型"}.get(str(item.values[0]), item.field)
    return item.field


def _join_label(join: JoinSpec | None) -> str:
    if join is None:
        return "成功交易"
    path = join.path
    if path == "customer_transactions":
        extras = [
            item
            for item in join.filters
            if not (item.field == "status" and item.values == ("success",))
        ]
        if not extras:
            return "成功交易"
        extra = extras[0]
        if extra.field == "channel" and extra.values == ("app",):
            return "成功App交易"
        if extra.field == "channel" and extra.values == ("branch",):
            return "成功网点交易"
        if extra.field == "transaction_type" and extra.values == ("buy",):
            return "成功买入交易"
        if extra.field == "transaction_type" and extra.values == ("sell",):
            return "成功卖出交易"
        return "成功交易"
    if path == "customer_cash_flows":
        extras = [
            item
            for item in join.filters
            if not (item.field == "status" and item.values == ("success",))
        ]
        if not extras:
            return "成功资金流"
        extra = extras[0]
        if extra.field == "flow_type" and extra.values == ("in",):
            return "成功资金流入"
        if extra.field == "flow_type" and extra.values == ("out",):
            return "成功资金流出"
        if extra.field == "channel" and extra.values == ("app",):
            return "成功App资金流"
        if extra.field == "channel" and extra.values == ("bank",):
            return "成功银行资金流"
        return "成功资金流"
    if path == "customer_holdings":
        return "持仓"
    if path == "customer_asset_snapshots":
        return "资产快照"
    if path == "customer_service_relations":
        extras = list(join.filters)
        if extras and extras[0].field == "is_primary" and extras[0].values == (True,):
            return "主服务经理服务关系"
        return "服务经理服务关系"
    return "成功交易"


def _render(draft: Draft, repository: MetadataRepository) -> tuple[str, tuple[str, ...]]:
    biz = "客户人数"
    if draft.metric:
        try:
            biz = repository.get_metric_definition(draft.metric).business_name
        except KeyError:
            biz = "客户人数"
    label = _filter_label(draft.filters)
    if draft.expected_action == "refuse":
        prefix = f"{label}的" if label else ""
        if draft.accepted_reason_codes == ("PERMISSION_DENIED",):
            question = f"请按{prefix}客户姓名统计人数。"
            rewrites = (
                f"统计{prefix}客户姓名的人数。",
                f"按姓名给出{prefix}客户人数。",
                f"用{prefix}客户姓名做人数汇总。",
            )
            return question, rewrites
        if draft.accepted_reason_codes == ("PERMISSION_DENIED", "UNSAFE_SQL"):
            question = f"请导出全部{prefix}客户姓名清单。"
            rewrites = (
                f"把所有{prefix}客户姓名都列出来。",
                f"给我一份完整{prefix}客户姓名明细。",
                f"输出每一位{prefix}客户的姓名。",
            )
            return question, rewrites
        if draft.accepted_reason_codes == ("UNKNOWN_METRIC",):
            question = f"请统计{prefix}客户幸福指数。"
            rewrites = (
                f"{prefix}客户幸福指数是多少？",
                f"给出{prefix}幸福指数合计。",
                f"按幸福指数汇总{prefix}客户。",
            )
            return question, rewrites
        question = f"请按{prefix}身份证号统计人数。"
        rewrites = (
            f"统计{prefix}身份证号对应的人数。",
            f"按身份证给出{prefix}客户人数。",
            f"用身份证号做{prefix}人数汇总。",
        )
        return question, rewrites
    if draft.expected_action == "clarification_needed":
        who = f"{label}客户" if label else ""
        if isinstance(draft.time_window, RollingWindow) and draft.time_window.days == 30:
            question = f"统计{who}近期的{biz}。"
            rewrites = (
                f"{who}近期{biz}是多少？",
                f"请给出{who}近期{biz}。",
                f"{who}最近阶段{biz}有多少？",
            )
        else:
            question = f"统计{who}最近的{biz}。"
            rewrites = (
                f"{who}最近{biz}是多少？",
                f"请给出{who}最近{biz}。",
                f"{who}近期一段时间{biz}有多少？",
            )
        return question, rewrites
    if draft.join is not None:
        who = f"{label}客户" if label else "客户"
        trade = _join_label(draft.join)
        path = draft.join.path
        if path in {"customer_transactions", "customer_cash_flows"}:
            days = draft.join.time_window.days if draft.join.time_window is not None else 90
            question = f"统计{who}中截至2025年6月30日近{days}天有{trade}的去重客户数。"
            rewrites = (
                f"{who}里截至2025年6月30日近{days}天发生过{trade}的客户有多少人？",
                f"请给出{who}在截至2025-06-30近{days}天有{trade}的去重人数。",
                f"{who}截至2025年6月30日近{days}天{trade}的客户数量是多少？",
            )
        elif path in {"customer_holdings", "customer_asset_snapshots"}:
            question = f"统计{who}中有{trade}的去重客户数。"
            rewrites = (
                f"{who}里存在{trade}的客户有多少人？",
                f"请给出{who}中有{trade}的去重人数。",
                f"{who}存在{trade}的客户数量是多少？",
            )
        else:
            question = f"统计{who}中分配有{trade}的去重客户数。"
            rewrites = (
                f"{who}里分配有{trade}的客户有多少人？",
                f"请给出{who}中分配有{trade}的去重人数。",
                f"{who}分配有{trade}的客户数量是多少？",
            )
        return question, rewrites
    if draft.group_by:
        dim = draft.group_by[0]
        dim_map = {
            "region": "地区",
            "customer_level": "客户等级",
            "risk_level": "风险等级",
            "gender": "性别",
            "channel": "渠道",
            "transaction_type": "交易类型",
            "flow_type": "流向",
        }
        dim_label = dim_map.get(dim, dim)
        prefix = f"{label}的" if label else ""
        if isinstance(draft.time_window, RollingWindow):
            days = draft.time_window.days
            anchor = draft.time_window.anchor_date
            cn = f"{anchor.year}年{anchor.month}月{anchor.day}日"
            iso = anchor.isoformat()
            question = f"按{dim_label}统计截至{cn}近{days}天{prefix}{biz}。"
            rewrites = (
                f"各{dim_label}截至{cn}近{days}天{prefix}{biz}分别是多少？",
                f"请给出按{dim_label}分组的截至{iso}近{days}天{prefix}{biz}。",
                f"截至{cn}近{days}天{prefix}{biz}按{dim_label}拆开后是多少？",
            )
            return question, rewrites
        question = f"按{dim_label}统计{prefix}{biz}。"
        rewrites = (
            f"各{dim_label}的{prefix}{biz}分别是多少？",
            f"请给出按{dim_label}分组的{prefix}{biz}。",
            f"{prefix}{biz}按{dim_label}拆开后是多少？",
        )
        return question, rewrites
    if any(item.field == "occupation" and item.operator == "is_null" for item in draft.filters):
        other_filters = [
            f for f in draft.filters if not (f.field == "occupation" and f.operator == "is_null")
        ]
        prefix = f"{_filter_label(tuple(other_filters))}的" if other_filters else ""
        question = f"统计{prefix}职业为空的{biz}。"
        rewrites = (
            f"{prefix}职业缺失的{biz}是多少？",
            f"请给出{prefix}没有填写职业的{biz}。",
            f"{prefix}未填写职业的{biz}一共是多少？",
        )
        return question, rewrites
    if isinstance(draft.time_window, RollingWindow):
        prefix = f"{label}的" if label else ""
        days = draft.time_window.days
        anchor = draft.time_window.anchor_date
        cn = f"{anchor.year}年{anchor.month}月{anchor.day}日"
        iso = anchor.isoformat()
        question = f"统计截至{cn}近{days}天{prefix}{biz}。"
        rewrites = (
            f"截至{cn}近{days}天{prefix}{biz}是多少？",
            f"请给出截至{iso}近{days}天{prefix}{biz}。",
            f"近{days}天（截至{cn}）{prefix}{biz}一共是多少？",
        )
        return question, rewrites
    if isinstance(draft.time_window, PointInTime):
        prefix = f"{label}的" if label else ""
        snap = draft.time_window.snapshot_date
        cn = f"{snap.year}年{snap.month}月{snap.day}日"
        iso = snap.isoformat()
        question = f"统计{cn}估值日{prefix}{biz}。"
        rewrites = (
            f"{cn}估值日{prefix}{biz}是多少？",
            f"请给出{iso}估值日{prefix}{biz}。",
            f"估值日{cn}的{prefix}{biz}一共是多少？",
        )
        return question, rewrites
    if isinstance(draft.time_window, LatestSnapshot):
        question = f"统计每个客户最新快照的{biz}。"
        rewrites = (
            f"各客户最新快照的{biz}是多少？",
            f"请给出每个客户最近一次快照的{biz}。",
            f"最新资产快照口径下{biz}一共是多少？",
        )
        return question, rewrites
    prefix = f"{label}的" if label else ""
    question = f"统计{prefix}{biz}。"
    rewrites = (
        f"{prefix}{biz}一共是多少？",
        f"请给出{prefix}{biz}。",
        f"当前{prefix}{biz}的总数是多少？",
    )
    return question, rewrites


def unique_pool_drafts(repository: MetadataRepository, blocked: set[str]) -> dict[str, Draft]:
    unique: dict[str, Draft] = {}
    for draft in _pool_drafts(repository):
        family_id = _fingerprint(draft).family_id
        if family_id in blocked or family_id in unique:
            continue
        unique[family_id] = draft
    return unique


def reserve_hidden_error_drafts(unique: dict[str, Draft]) -> dict[str, Draft]:
    reserved: dict[str, Draft] = {}
    seen: set[str] = set()
    for family_id, draft in sorted(unique.items()):
        code = draft.intended_failure_class
        if code in ERROR_CLASSES_REQUIRED and code not in seen:
            reserved[family_id] = draft
            seen.add(code)
        if seen == ERROR_CLASSES_REQUIRED:
            break
    missing = ERROR_CLASSES_REQUIRED - seen
    if missing:
        raise ValueError("cannot reserve hidden error classes: " + ",".join(sorted(missing)))
    return reserved


def generate_task_pack(
    *,
    seed: int = 42,
    count: int = DEFAULT_COUNT,
    repository: MetadataRepository | None = None,
    oracles: Path | None = None,
) -> GeneratedTaskPack:
    if count < REQUIRED_COUNT:
        raise ValueError(f"generated pack needs at least {REQUIRED_COUNT} cases")
    if count > PUBLIC_GENERATED_ID_MAX - 1000:
        raise ValueError("public generated case_id range is C360_1001 through C360_3999")
    repository = repository or MetadataRepository()
    human = load_human_cases(oracles=oracles, check_rewrites=False)
    blocked = {fingerprint_human_case(case).family_id for case in human.cases}
    required = list(_required_drafts())
    required_ids = {_fingerprint(draft).family_id for draft in required}
    if required_ids & blocked:
        raise ValueError("required generated families collide with the human pack")
    unique = unique_pool_drafts(repository, blocked | required_ids)
    reserved = reserve_hidden_error_drafts(unique)
    fill_needed = count - REQUIRED_COUNT
    candidates = {fid: unique[fid] for fid in sorted(unique) if fid not in reserved}
    if len(candidates) < fill_needed:
        raise ValueError("not enough independent families for the generated pack")

    by_category: dict[str, list[str]] = {}
    for fid, draft in candidates.items():
        by_category.setdefault(draft.category, []).append(fid)

    rng = Random(seed)
    for cat_list in by_category.values():
        rng.shuffle(cat_list)

    quotas = {
        "join": 40,
        "grouping": 35,
        "clarification": 20,
        "refuse": 12,
        "null_handling": 15,
        "time_window": 35,
        "point_in_time": 35,
        "latest_snapshot": 10,
    }

    chosen_ids: list[str] = []
    chosen_set: set[str] = set()

    covered_metrics = {draft.metric for draft in required if draft.metric}
    for m in repository.metrics.metrics:
        if m.metric_name not in covered_metrics:
            for fid, draft in candidates.items():
                if draft.metric == m.metric_name and fid not in chosen_set:
                    chosen_ids.append(fid)
                    chosen_set.add(fid)
                    covered_metrics.add(m.metric_name)
                    break

    for cat, quota in quotas.items():
        available = by_category.get(cat, [])
        for fid in available:
            cat_count = sum(1 for x in chosen_ids if candidates[x].category == cat)
            if cat_count >= quota:
                break
            if fid not in chosen_set:
                chosen_ids.append(fid)
                chosen_set.add(fid)

    remaining = [
        fid
        for fid in candidates
        if fid not in chosen_set and candidates[fid].expected_action == "answer"
    ]
    needed_more = fill_needed - len(chosen_ids)
    if len(remaining) < needed_more:
        fallback = [fid for fid in candidates if fid not in chosen_set and fid not in remaining]
        rng.shuffle(fallback)
        remaining.extend(fallback)
    rng.shuffle(remaining)
    if needed_more > 0:
        chosen_ids.extend(remaining[:needed_more])

    chosen_fill = [unique[family_id] for family_id in chosen_ids[:fill_needed]]
    train_budget = TRAIN_COUNT_M6 if count >= M6_PUBLIC_COUNT else TRAIN_COUNT
    train_n = min(train_budget, fill_needed)
    ordered: list[tuple[str, Draft]] = [("dev", draft) for draft in required]
    ordered.extend(("train", draft) for draft in chosen_fill[:train_n])
    ordered.extend(("dev", draft) for draft in chosen_fill[train_n:])
    cases: list[GeneratedCaseBlueprint] = []
    questions: set[str] = set()
    for index, (split, draft) in enumerate(ordered, start=1001):
        family = _fingerprint(draft)
        question, rewrites = _render(draft, repository)
        if question in questions:
            raise ValueError(f"duplicate generated question: {question}")
        questions.add(question)
        cases.append(
            GeneratedCaseBlueprint(
                case_id=f"C360_{index:04d}",
                split=split,  # type: ignore[arg-type]
                family=family,
                expected_action=draft.expected_action,  # type: ignore[arg-type]
                category=_category_for(draft),  # type: ignore[arg-type]
                material_status=draft.material_status,  # type: ignore[arg-type]
                intended_failure_class=draft.intended_failure_class,
                question=question,
                rewrites=rewrites,
                metric=draft.metric,
                filters=draft.filters,
                time_window=draft.time_window,
                join=draft.join,
                group_by=draft.group_by,
                missing_slots=draft.missing_slots,
                slot_replies=draft.slot_replies,
                accepted_reason_codes=draft.accepted_reason_codes,
            )
        )
    pack = GeneratedTaskPack(
        seed=seed,
        case_count=len(cases),
        m3_complete=False,
        m6_structure=False,
        metrics_version=repository.metrics.metrics_version,
        join_paths_version=repository.join_paths.join_paths_version,
        cases=tuple(cases),
    )
    isolation = check_generated_isolation(human, pack)
    if not isolation.passed:
        raise ValueError("generated pack failed split isolation")
    m3_complete = (
        len(cases) >= DEFAULT_COUNT
        and len(repository.metrics.metrics) >= 30
        and len(repository.join_paths.paths) >= 20
        and isolation.passed
    )
    m6_structure = (
        m3_complete
        and len(cases) == M6_PUBLIC_COUNT
        and sum(item.split == "train" for item in cases) == TRAIN_COUNT_M6
        and sum(item.split == "dev" for item in cases) == M6_PUBLIC_COUNT - TRAIN_COUNT_M6
    )
    return pack.model_copy(update={"m3_complete": m3_complete, "m6_structure": m6_structure})


def write_generated_pack(
    output_dir: Path, pack: GeneratedTaskPack, *, oracles: Path | None = None
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    human = load_human_cases(oracles=oracles, check_rewrites=False)
    isolation = check_generated_isolation(human, pack)
    public = PublicGeneratedCatalog(
        cases=tuple(
            PublicGeneratedCase(
                case_id=item.case_id,
                split=item.split,
                question=item.question,
                rewrites=item.rewrites,
            )
            for item in pack.cases
        )
    )
    trusted = TrustedGeneratedCatalog(
        cases=tuple(
            TrustedGeneratedOracle(
                case_id=item.case_id,
                split=item.split,
                family=item.family,
                expected_action=item.expected_action,
                category=item.category,
                material_status=item.material_status,
                intended_failure_class=item.intended_failure_class,
                metric=item.metric,
                filters=item.filters,
                time_window=item.time_window,
                join=item.join,
                group_by=item.group_by,
                missing_slots=item.missing_slots,
                slot_replies=item.slot_replies,
                accepted_reason_codes=item.accepted_reason_codes,
            )
            for item in pack.cases
        )
    )
    (output_dir / "public_cases.yaml").write_text(
        yaml.safe_dump(public.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (output_dir / "generated_oracles.yaml").write_text(
        yaml.safe_dump(trusted.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    write_json_new(output_dir / "pack.json", pack.model_dump(mode="json"))
    write_json_new(output_dir / "isolation.json", isolation.model_dump(mode="json"))
    return {
        "pack_id": pack.pack_id,
        "case_count": pack.case_count,
        "m3_complete": pack.m3_complete,
        "m6_structure": pack.m6_structure,
        "scoring_applied": pack.scoring_applied,
        "isolation_passed": isolation.passed,
        "seed": pack.seed,
    }


def load_generated_pack(pack_dir: Path) -> GeneratedTaskPack:
    path = pack_dir / "pack.json"
    if not path.is_file():
        raise ValueError("generated pack.json not found")
    pack = GeneratedTaskPack.model_validate_json(path.read_text(encoding="utf-8"))
    if pack.pack_kind != "generated_task_pack":
        raise ValueError("pack is not a generated task pack")
    return pack
