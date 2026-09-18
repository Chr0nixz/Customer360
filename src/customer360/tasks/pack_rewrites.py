"""Structured rewrite checks for generated and hidden packs. Trusted-side only."""

from __future__ import annotations

import re
from datetime import date

from customer360.contracts.rewrites import RewriteIssue
from customer360.contracts.semantic import Filter, LatestSnapshot, PointInTime, RollingWindow
from customer360.metadata.metrics import MetadataRepository

DATE_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
DATE_CN = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
DAY_SPAN = re.compile(r"(\d{1,4})\s*天")
NEGATED_VIP = re.compile(r"非\s*VIP|不是\s*VIP")
NEGATED_SUCCESS = re.compile(r"不成功|非成功|未成功")
REGIONS = ("华东", "华北", "华南", "西南")
NULL_OCCUPATION = ("空", "缺失", "没有填写", "未填写")
LATEST = ("最新快照", "最新资产快照", "最近一次快照", "最新总资产")
GROUPING = ("按地区", "分地区", "各地区", "按客户地区")
AMBIGUOUS_TIME = ("最近", "近期")
FORBIDDEN_CALENDAR = ("三个月", "3个月", "本季度", "近一个月", "最近一个月")
METRIC_ALIASES = {
    "distinct_customer_count": ("客户数", "去重人数", "有多少人", "客户数量", "去重客户"),
    "latest_total_asset": ("最新总资产", "总资产合计", "最新快照"),
}


def _parse_dates(text: str) -> tuple[date, ...]:
    found: list[date] = []
    for match in DATE_ISO.finditer(text):
        found.append(date.fromisoformat(match.group(1)))
    for match in DATE_CN.finditer(text):
        found.append(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
    return tuple(dict.fromkeys(found))


def _aliases(value: date) -> tuple[str, ...]:
    return (
        value.isoformat(),
        f"{value.year}年{value.month}月{value.day}日",
        f"{value.year}年{value.month:02d}月{value.day:02d}日",
    )


def _issue(case_id: str, rewrite: str, code: str, detail: str) -> RewriteIssue:
    return RewriteIssue(case_id=case_id, rewrite=rewrite, code=code, detail=detail)  # type: ignore[arg-type]


def _eq_values(filters: tuple[Filter, ...], field: str) -> frozenset[str]:
    values: set[str] = set()
    for item in filters:
        if item.field == field and item.operator in {"eq", "in"}:
            values.update(str(value) for value in item.values)
    return frozenset(values)


def _all_filters(case) -> tuple[Filter, ...]:
    extra = case.join.filters if case.join is not None else ()
    return (*case.filters, *extra)


def check_generated_rewrite(
    case, text: str, repository: MetadataRepository
) -> tuple[RewriteIssue, ...]:
    issues: list[RewriteIssue] = []
    case_id = case.case_id
    mentioned = _parse_dates(text)
    if any(item in text for item in FORBIDDEN_CALENDAR):
        issues.append(
            _issue(case_id, text, "TIME_RANGE_ERROR", "rewrite uses a month/quarter window")
        )
    spans = tuple(int(match.group(1)) for match in DAY_SPAN.finditer(text))
    window = case.time_window
    join_window = case.join.time_window if case.join is not None else None
    rolling = window if isinstance(window, RollingWindow) else join_window
    missing_window = (
        case.expected_action == "clarification_needed" and "time_window" in case.missing_slots
    )
    if missing_window:
        if any(item in spans for item in (30, 90, 180)) or mentioned:
            issues.append(
                _issue(
                    case_id, text, "CLARIFICATION_FAILURE", "rewrite fills the hidden time_window"
                )
            )
        if not any(token in text for token in AMBIGUOUS_TIME):
            issues.append(
                _issue(
                    case_id, text, "CLARIFICATION_FAILURE", "clarification rewrite loses 最近/近期"
                )
            )
        return tuple(issues)
    if case.expected_action == "refuse":
        codes = set(case.accepted_reason_codes)
        if "UNKNOWN_METRIC" in codes and "幸福" not in text:
            issues.append(
                _issue(case_id, text, "SCHEMA_ERROR", "unknown-metric rewrite drops 幸福指数")
            )
        if "UNKNOWN_FIELD" in codes and "身份证" not in text:
            issues.append(
                _issue(case_id, text, "SCHEMA_ERROR", "unknown-field rewrite drops 身份证")
            )
        if "PERMISSION_DENIED" in codes and "姓名" not in text:
            issues.append(_issue(case_id, text, "SCHEMA_ERROR", "permission rewrite drops 姓名"))
        return tuple(issues)
    if case.material_status == "compilable_answer":
        if case.metric is not None:
            business = repository.get_metric_definition(case.metric).business_name
            aliases = METRIC_ALIASES.get(case.metric, ())
            if business not in text and not any(item in text for item in aliases):
                issues.append(
                    _issue(case_id, text, "METRIC_ERROR", f"rewrite drops metric name {business}")
                )
        if isinstance(rolling, RollingWindow):
            if rolling.days not in spans:
                issues.append(
                    _issue(
                        case_id,
                        text,
                        "TIME_RANGE_ERROR",
                        f"rewrite is missing the {rolling.days}-day rolling window",
                    )
                )
            if not any(alias in text for alias in _aliases(rolling.anchor_date)):
                issues.append(
                    _issue(
                        case_id, text, "TIME_RANGE_ERROR", "rewrite is missing the rolling anchor"
                    )
                )
        if isinstance(window, PointInTime):
            if "估值日" not in text or not any(
                alias in text for alias in _aliases(window.snapshot_date)
            ):
                issues.append(
                    _issue(case_id, text, "TIME_RANGE_ERROR", "point-in-time rewrite drops 估值日")
                )
        if isinstance(window, LatestSnapshot) or case.category == "latest_snapshot":
            if not any(token in text for token in LATEST):
                issues.append(
                    _issue(
                        case_id, text, "TIME_RANGE_ERROR", "rewrite drops latest-snapshot language"
                    )
                )
            if mentioned:
                issues.append(
                    _issue(case_id, text, "TIME_RANGE_ERROR", "latest-snapshot rewrite adds a date")
                )
        filters = _all_filters(case)
        levels = _eq_values(filters, "customer_level")
        regions = _eq_values(filters, "region")
        if "VIP" in levels and "VIP" not in text:
            issues.append(_issue(case_id, text, "FILTER_ERROR", "rewrite drops the VIP filter"))
        if "VIP" in levels and NEGATED_VIP.search(text):
            issues.append(_issue(case_id, text, "FILTER_ERROR", "rewrite negates the VIP filter"))
        if "VIP" in text and "VIP" not in levels:
            issues.append(_issue(case_id, text, "FILTER_ERROR", "rewrite adds a VIP filter"))
        for region in REGIONS:
            if region in regions and region not in text:
                issues.append(
                    _issue(case_id, text, "FILTER_ERROR", f"rewrite drops the {region} filter")
                )
            if region in text and region not in regions:
                issues.append(
                    _issue(case_id, text, "FILTER_ERROR", f"rewrite adds a {region} filter")
                )
        if any(item.field == "occupation" and item.operator == "is_null" for item in filters):
            if "职业" not in text or not any(token in text for token in NULL_OCCUPATION):
                issues.append(
                    _issue(case_id, text, "FILTER_ERROR", "rewrite drops occupation IS NULL")
                )
        if case.join is not None:
            if "客户" not in text or "交易" not in text:
                issues.append(
                    _issue(case_id, text, "JOIN_ERROR", "join rewrite must keep 客户 and 交易")
                )
            if "成功" not in text:
                issues.append(
                    _issue(case_id, text, "JOIN_ERROR", "join rewrite drops status=success")
                )
            if NEGATED_SUCCESS.search(text):
                issues.append(
                    _issue(case_id, text, "JOIN_ERROR", "join rewrite negates status=success")
                )
        if case.group_by == ("region",) and not any(token in text for token in GROUPING):
            issues.append(
                _issue(
                    case_id, text, "AGGREGATION_ERROR", "grouping rewrite drops the region split"
                )
            )
    return tuple(issues)


def case_rewrites_pass(case, repository: MetadataRepository) -> bool:
    texts = (case.question, *case.rewrites)
    return not any(check_generated_rewrite(case, text, repository) for text in texts)
