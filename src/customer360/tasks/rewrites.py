"""Structured rewrite checks against canonical SemanticSpec slots.

Trusted-side only: no compiler, DuckDB, Agent, evaluator or model judge.
A paraphrase passes when it keeps the spec's date, metric, filter and Join
evidence and does not introduce a competing slot.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from customer360.contracts.coverage import HumanCaseBlueprint, HumanCaseCatalog
from customer360.contracts.rewrites import RewriteCaseResult, RewriteIssue, RewriteReport
from customer360.contracts.semantic import Filter, PointInTime, RollingWindow

# Extra-filter probes; values must stay aligned with Tiny generator enums.
REGIONS = ("华东", "华北", "华南", "西南")
LEVELS = ("VIP", "standard")
OCCUPATIONS = ("教师", "工程师", "医生", "设计师", "公务员", "个体经营")

DATE_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
DATE_CN = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
DAY_SPAN = re.compile(r"(\d{1,4})\s*天")
NEGATED_VIP = re.compile(r"非\s*VIP|不是\s*VIP")
NEGATED_SUCCESS = re.compile(r"不成功|非成功|未成功")
NEGATED_EMPTY = re.compile(r"非空|不是空|已填写")
JOIN_CUSTOMER = re.compile(r"有成功交易的|发生过成功交易的|成功交易的?VIP客户|成功交易VIP客户")
FORBIDDEN_CALENDAR = (
    "三个月",
    "3个月",
    "本季度",
    "近一个月",
    "最近一个月",
    "近一周",
)
NULL_OCCUPATION = ("空", "缺失", "没有填写", "未填写")
CURRENT_RELATION = ("当前", "仍有效", "未结束", "现在")
WINDOW_START = ("首日", "第一天", "起始日")
WINDOW_OUTSIDE = ("窗口外", "窗口之外", "前一天", "前一日")
LATEST_SNAPSHOT = ("最新快照", "最新资产快照", "最近一次快照", "各自最新快照")
GROUPING = ("按地区", "分地区", "各地区", "按客户地区")
PHONE = ("手机号", "手机号码")
AMBIGUOUS_TIME = ("最近", "近期")
COUNT_TXN = ("笔数", "次数", "几笔", "交易笔")
AMOUNT_HINT = ("金额", "总额", "总和", "合计")
CUSTOMER_COUNT = ("客户数", "客户数量", "有多少人", "几人", "客户一共", "客户有多少")
METRIC_EVIDENCE: dict[str, tuple[tuple[str, ...], ...]] = {
    "distinct_customer_count": (
        ("客户",),
        ("数", "多少", "几人", "总数", "数量", "有多少人"),
    ),
    "active_customer_count": (("活跃",), ("客户",)),
    "successful_transaction_count": (("成功",), ("交易",), ("笔", "次", "几笔", "多少")),
    "successful_transaction_amount": (("成功",), ("交易",), ("金额", "总额", "总和")),
    "failed_transaction_count": (("失败",), ("交易",), ("笔", "次", "几笔", "多少")),
    "successful_net_cash_flow": (("成功",), ("净流入", "流入减流出")),
    "successful_cash_inflow": (("成功",), ("流入", "入账")),
    "current_primary_service_relation_count": (("主服务关系",), CURRENT_RELATION),
    "snapshot_total_asset": (("总资产",),),
    "snapshot_net_asset": (("净资产",),),
    "latest_total_asset": (("总资产",),),
}


def _issue(case: HumanCaseBlueprint, rewrite: str, code: str, detail: str) -> RewriteIssue:
    return RewriteIssue(case_id=case.case_id, rewrite=rewrite, code=code, detail=detail)


def _parse_dates(text: str) -> tuple[date, ...]:
    found: list[date] = []
    for match in DATE_ISO.finditer(text):
        found.append(date.fromisoformat(match.group(1)))
    for match in DATE_CN.finditer(text):
        found.append(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
    return tuple(dict.fromkeys(found))


def _date_aliases(value: date) -> tuple[str, ...]:
    return (
        value.isoformat(),
        f"{value.year}年{value.month}月{value.day}日",
        f"{value.year}年{value.month:02d}月{value.day:02d}日",
    )


def _mentions_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(item in text for item in needles)


def _rolling(case: HumanCaseBlueprint) -> RollingWindow | None:
    window = case.time_window
    if isinstance(window, RollingWindow):
        return window
    if case.join is not None and isinstance(case.join.time_window, RollingWindow):
        return case.join.time_window
    return None


def _point_in_time(case: HumanCaseBlueprint) -> PointInTime | None:
    if isinstance(case.time_window, PointInTime):
        return case.time_window
    return None


def _filter_dates(filters: tuple[Filter, ...]) -> frozenset[date]:
    values: set[date] = set()
    for item in filters:
        if item.operator not in {"eq", "in"}:
            continue
        for raw in item.values:
            if isinstance(raw, str) and DATE_ISO.fullmatch(raw):
                values.add(date.fromisoformat(raw))
            elif isinstance(raw, date):
                values.add(raw)
    return frozenset(values)


def _allowed_dates(case: HumanCaseBlueprint) -> frozenset[date]:
    allowed: set[date] = set()
    rolling = _rolling(case)
    if rolling is not None:
        allowed.add(rolling.anchor_date)
    pit = _point_in_time(case)
    if pit is not None:
        allowed.add(pit.snapshot_date)
    allowed.update(_filter_dates((*case.filters, *(case.join.filters if case.join else ()))))
    return frozenset(allowed)


def _eq_values(filters: tuple[Filter, ...], field: str) -> frozenset[str]:
    values: set[str] = set()
    for item in filters:
        if item.field == field and item.operator in {"eq", "in"}:
            values.update(str(value) for value in item.values)
    return frozenset(values)


def _has_null_filter(filters: tuple[Filter, ...], field: str) -> bool:
    return any(item.field == field and item.operator == "is_null" for item in filters)


def _all_filters(case: HumanCaseBlueprint) -> tuple[Filter, ...]:
    extra = case.join.filters if case.join is not None else ()
    return (*case.filters, *extra)


def _transaction_filter_dates(case: HumanCaseBlueprint) -> frozenset[date]:
    return _filter_dates(tuple(item for item in case.filters if item.field == "transaction_date"))


def _check_dates(case: HumanCaseBlueprint, text: str) -> list[RewriteIssue]:
    issues: list[RewriteIssue] = []
    try:
        mentioned = _parse_dates(text)
    except ValueError:
        return [_issue(case, text, "TIME_RANGE_ERROR", "rewrite contains an invalid calendar date")]
    allowed = _allowed_dates(case)
    for value in mentioned:
        if value not in allowed:
            issues.append(
                _issue(
                    case,
                    text,
                    "TIME_RANGE_ERROR",
                    f"rewrite date {value.isoformat()} is not in the spec",
                )
            )
    if _mentions_any(text, FORBIDDEN_CALENDAR):
        issues.append(_issue(case, text, "TIME_RANGE_ERROR", "rewrite uses a month/quarter window"))
    spans = tuple(int(match.group(1)) for match in DAY_SPAN.finditer(text))
    rolling = _rolling(case)
    pit = _point_in_time(case)
    missing_window = (
        case.expected_action == "clarification_needed" and "time_window" in case.missing_slots
    )
    if missing_window:
        filled_days = rolling is not None and rolling.days in spans
        filled_anchor = rolling is not None and _mentions_any(
            text, _date_aliases(rolling.anchor_date)
        )
        if filled_days or filled_anchor:
            issues.append(
                _issue(
                    case, text, "CLARIFICATION_FAILURE", "rewrite fills the hidden time_window slot"
                )
            )
        return issues
    if rolling is not None and case.material_status == "compilable_answer":
        if rolling.days not in spans:
            issues.append(
                _issue(
                    case,
                    text,
                    "TIME_RANGE_ERROR",
                    f"rewrite is missing the {rolling.days}-day rolling window",
                )
            )
        extra_spans = tuple(item for item in spans if item != rolling.days)
        if extra_spans:
            issues.append(
                _issue(
                    case, text, "TIME_RANGE_ERROR", f"rewrite uses extra day spans {extra_spans}"
                )
            )
        filter_dates = _transaction_filter_dates(case)
        if rolling.start_date in filter_dates and not _mentions_any(text, WINDOW_START):
            issues.append(
                _issue(case, text, "TIME_RANGE_ERROR", "rewrite drops the window-start boundary")
            )
        if rolling.start_date - timedelta(days=1) in filter_dates and not _mentions_any(
            text, WINDOW_OUTSIDE
        ):
            issues.append(
                _issue(case, text, "TIME_RANGE_ERROR", "rewrite drops the outside-window boundary")
            )
    if pit is not None and case.material_status == "compilable_answer":
        if not _mentions_any(text, _date_aliases(pit.snapshot_date)):
            issues.append(
                _issue(case, text, "TIME_RANGE_ERROR", "rewrite is missing the snapshot_date")
            )
        if "估值日" not in text:
            issues.append(_issue(case, text, "TIME_RANGE_ERROR", "rewrite is missing 估值日"))
        if spans or "近90天" in text:
            issues.append(
                _issue(
                    case, text, "TIME_RANGE_ERROR", "point-in-time rewrite uses a rolling window"
                )
            )
        if _mentions_any(text, LATEST_SNAPSHOT):
            issues.append(
                _issue(
                    case, text, "TIME_RANGE_ERROR", "point-in-time rewrite asks for latest-snapshot"
                )
            )
    if case.category == "latest_snapshot":
        if not _mentions_any(text, LATEST_SNAPSHOT):
            issues.append(
                _issue(case, text, "TIME_RANGE_ERROR", "rewrite drops latest-snapshot language")
            )
        if mentioned:
            issues.append(
                _issue(
                    case, text, "TIME_RANGE_ERROR", "latest-snapshot rewrite adds an explicit date"
                )
            )
    if rolling is None and pit is None and "估值日" in text:
        issues.append(_issue(case, text, "TIME_RANGE_ERROR", "rewrite introduces 估值日"))
    return issues


def _detected_metric(text: str) -> str | None:
    if "净资产" in text:
        return "snapshot_net_asset"
    if _mentions_any(text, LATEST_SNAPSHOT) and "总资产" in text:
        return "latest_total_asset"
    if "总资产" in text:
        return "snapshot_total_asset"
    if "净流入" in text or "流入减流出" in text:
        return "successful_net_cash_flow"
    inflow = "入账" in text or "流入" in text
    if inflow and "净流入" not in text and "流入减流出" not in text:
        return "successful_cash_inflow"
    if "失败交易" in text:
        return "failed_transaction_count"
    if "主服务关系" in text:
        return "current_primary_service_relation_count"
    if "活跃客户" in text or "活跃状态的客户" in text:
        return "active_customer_count"
    if "交易" in text and _mentions_any(text, AMOUNT_HINT) and "资金" not in text:
        return "successful_transaction_amount"
    if "成功交易" in text and _mentions_any(text, COUNT_TXN):
        return "successful_transaction_count"
    if _mentions_any(text, CUSTOMER_COUNT) or (
        "客户" in text and _mentions_any(text, ("数量", "多少", "总数"))
    ):
        return "distinct_customer_count"
    return None


def _join_mentions_success_customers(text: str) -> bool:
    return JOIN_CUSTOMER.search(text) is not None or ("成功交易" in text and "客户" in text)


def _check_metric(case: HumanCaseBlueprint, text: str) -> list[RewriteIssue]:
    issues: list[RewriteIssue] = []
    detected = _detected_metric(text)
    if case.material_status == "unsupported_capability":
        if case.category == "latest_snapshot":
            if "总资产" not in text:
                issues.append(
                    _issue(case, text, "METRIC_ERROR", "latest-snapshot rewrite drops 总资产")
                )
            if "净资产" in text:
                issues.append(
                    _issue(case, text, "METRIC_ERROR", "latest-snapshot rewrite swaps in 净资产")
                )
        elif case.category == "grouping" and "活跃" not in text:
            issues.append(_issue(case, text, "METRIC_ERROR", "grouping rewrite drops 活跃客户"))
        return issues
    if case.expected_action == "refuse":
        if not _mentions_any(text, PHONE):
            issues.append(
                _issue(case, text, "SCHEMA_ERROR", "refuse rewrite drops the unknown phone field")
            )
        if "姓名" in text or "身份证" in text:
            issues.append(
                _issue(case, text, "SCHEMA_ERROR", "refuse rewrite swaps the protected field")
            )
        return issues
    if case.expected_action == "clarification_needed":
        if not _mentions_any(text, AMBIGUOUS_TIME):
            issues.append(
                _issue(case, text, "CLARIFICATION_FAILURE", "clarification rewrite loses 最近/近期")
            )
        if "交易" not in text:
            issues.append(_issue(case, text, "METRIC_ERROR", "clarification rewrite drops 交易"))
        return issues
    expected = case.metric
    if expected is None:
        return issues
    for group in METRIC_EVIDENCE.get(expected, ()):
        if not _mentions_any(text, group):
            issues.append(
                _issue(case, text, "METRIC_ERROR", f"rewrite is missing metric evidence {group[0]}")
            )
    if expected == "successful_transaction_amount" and _mentions_any(text, COUNT_TXN):
        issues.append(_issue(case, text, "METRIC_ERROR", "amount rewrite uses a count unit"))
    if expected == "successful_transaction_count" and _mentions_any(text, ("金额", "总额", "总和")):
        issues.append(_issue(case, text, "METRIC_ERROR", "count rewrite uses an amount unit"))
    if expected == "successful_cash_inflow" and ("净流入" in text or "流入减流出" in text):
        issues.append(_issue(case, text, "METRIC_ERROR", "inflow rewrite swaps in net cash flow"))
    if expected == "successful_net_cash_flow" and "入账" in text:
        issues.append(
            _issue(case, text, "METRIC_ERROR", "net-flow rewrite swaps in inflow-only language")
        )
    if expected == "snapshot_total_asset" and "净资产" in text:
        issues.append(_issue(case, text, "METRIC_ERROR", "total-asset rewrite swaps in 净资产"))
    if expected == "latest_total_asset" and "净资产" in text:
        issues.append(_issue(case, text, "METRIC_ERROR", "latest-snapshot rewrite swaps in 净资产"))
    if expected == "snapshot_net_asset" and "总资产" in text:
        issues.append(_issue(case, text, "METRIC_ERROR", "net-asset rewrite swaps in 总资产"))
    if expected == "failed_transaction_count" and "成功交易" in text:
        issues.append(_issue(case, text, "METRIC_ERROR", "failed-count rewrite swaps in 成功交易"))
    if expected == "successful_transaction_count" and "失败交易" in text:
        issues.append(_issue(case, text, "METRIC_ERROR", "success-count rewrite swaps in 失败交易"))
    success_metric = expected in {
        "successful_transaction_count",
        "successful_transaction_amount",
        "successful_net_cash_flow",
        "successful_cash_inflow",
    }
    if success_metric and NEGATED_SUCCESS.search(text):
        issues.append(_issue(case, text, "METRIC_ERROR", "rewrite negates the success status"))
    join_customer_count = (
        case.join is not None
        and expected == "distinct_customer_count"
        and _join_mentions_success_customers(text)
    )
    if detected is not None and detected != expected and not join_customer_count:
        issues.append(
            _issue(case, text, "METRIC_ERROR", f"rewrite reads as {detected} instead of {expected}")
        )
    return issues


def _check_filters(case: HumanCaseBlueprint, text: str) -> list[RewriteIssue]:
    issues: list[RewriteIssue] = []
    if case.material_status != "compilable_answer":
        return issues
    filters = _all_filters(case)
    required_levels = _eq_values(filters, "customer_level")
    required_regions = _eq_values(filters, "region")
    if "VIP" in required_levels and "VIP" not in text:
        issues.append(_issue(case, text, "FILTER_ERROR", "rewrite drops the VIP filter"))
    if "VIP" in required_levels and NEGATED_VIP.search(text):
        issues.append(_issue(case, text, "FILTER_ERROR", "rewrite negates the VIP filter"))
    if "VIP" in text and "VIP" not in required_levels:
        issues.append(_issue(case, text, "FILTER_ERROR", "rewrite adds a VIP filter"))
    for region in REGIONS:
        if region in required_regions and region not in text:
            issues.append(_issue(case, text, "FILTER_ERROR", f"rewrite drops the {region} filter"))
        if region in text and region not in required_regions:
            issues.append(_issue(case, text, "FILTER_ERROR", f"rewrite adds a {region} filter"))
    if _has_null_filter(filters, "occupation"):
        if "职业" not in text or not _mentions_any(text, NULL_OCCUPATION):
            issues.append(_issue(case, text, "FILTER_ERROR", "rewrite drops occupation IS NULL"))
        if NEGATED_EMPTY.search(text):
            issues.append(_issue(case, text, "FILTER_ERROR", "rewrite negates occupation IS NULL"))
        if _mentions_any(text, OCCUPATIONS):
            issues.append(
                _issue(case, text, "FILTER_ERROR", "rewrite fills occupation with a concrete value")
            )
    elif "职业" in text:
        issues.append(_issue(case, text, "FILTER_ERROR", "rewrite adds an occupation filter"))
    if case.metric != "active_customer_count" and "活跃" in text:
        issues.append(_issue(case, text, "FILTER_ERROR", "rewrite adds an active-status filter"))
    for level in LEVELS:
        if level != "VIP" and level in text and level not in required_levels:
            issues.append(_issue(case, text, "FILTER_ERROR", f"rewrite adds a {level} filter"))
    return issues


def _check_join(case: HumanCaseBlueprint, text: str) -> list[RewriteIssue]:
    issues: list[RewriteIssue] = []
    join_language = JOIN_CUSTOMER.search(text) is not None
    if case.join is not None:
        if "客户" not in text or "交易" not in text:
            issues.append(_issue(case, text, "JOIN_ERROR", "join rewrite must keep 客户 and 交易"))
        if not join_language and not _join_mentions_success_customers(text):
            issues.append(
                _issue(case, text, "JOIN_ERROR", "rewrite drops the customer_transactions path")
            )
        counts_txn = _mentions_any(text, COUNT_TXN)
        counts_customers = _mentions_any(text, CUSTOMER_COUNT) or "客户" in text
        if counts_txn and not counts_customers:
            issues.append(
                _issue(
                    case,
                    text,
                    "JOIN_ERROR",
                    "join rewrite counts transactions instead of customers",
                )
            )
        success_filter = any(
            item.field == "status" and "success" in {str(value) for value in item.values}
            for item in case.join.filters
        )
        if success_filter and "成功" not in text:
            issues.append(_issue(case, text, "JOIN_ERROR", "join rewrite drops status=success"))
        if success_filter and NEGATED_SUCCESS.search(text):
            issues.append(_issue(case, text, "JOIN_ERROR", "join rewrite negates status=success"))
    elif case.material_status == "compilable_answer" and join_language:
        issues.append(
            _issue(case, text, "JOIN_ERROR", "non-join rewrite introduces customer_transactions")
        )
    return issues


def _check_unsupported_shape(case: HumanCaseBlueprint, text: str) -> list[RewriteIssue]:
    issues: list[RewriteIssue] = []
    if case.category == "grouping":
        if not _mentions_any(text, GROUPING):
            issues.append(
                _issue(case, text, "AGGREGATION_ERROR", "grouping rewrite drops the region split")
            )
    elif _mentions_any(text, GROUPING):
        issues.append(_issue(case, text, "AGGREGATION_ERROR", "rewrite introduces GROUP BY region"))
    return issues


def check_rewrite(case: HumanCaseBlueprint, rewrite: str) -> tuple[RewriteIssue, ...]:
    issues = [
        *_check_dates(case, rewrite),
        *_check_metric(case, rewrite),
        *_check_filters(case, rewrite),
        *_check_join(case, rewrite),
        *_check_unsupported_shape(case, rewrite),
    ]
    return tuple(issues)


def check_case_rewrites(case: HumanCaseBlueprint) -> RewriteCaseResult:
    canonical = tuple(check_rewrite(case, case.question))
    paraphrases = tuple(item for rewrite in case.rewrites for item in check_rewrite(case, rewrite))
    issues = canonical + paraphrases
    return RewriteCaseResult(
        case_id=case.case_id,
        passed=not issues,
        rewrite_count=len(case.rewrites),
        issues=issues,
    )


def validate_catalog_rewrites(catalog: HumanCaseCatalog) -> RewriteReport:
    results = tuple(check_case_rewrites(case) for case in catalog.cases)
    issues = tuple(item for result in results for item in result.issues)
    return RewriteReport(
        passed=not issues,
        rewrite_count=sum(result.rewrite_count for result in results),
        issue_count=len(issues),
        cases=results,
    )


def format_rewrite_failures(report: RewriteReport) -> str:
    if report.passed:
        return "rewrite semantic consistency passed"
    details = [
        f"{item.case_id} {item.code}: {item.detail}"
        for case in report.cases
        for item in case.issues
    ]
    return "rewrite semantic consistency failed: " + "; ".join(details)
