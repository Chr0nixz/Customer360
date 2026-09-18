"""Named business quality assertions over a generated Tiny dataset.

Each entry in CHECKS is an independent, individually named assertion with its own
business meaning; nothing is padded by looping one assertion over tables or
columns. Checks run on the generated database before any artifact is published.
"""

from collections.abc import Callable
from datetime import timedelta

from customer360.artifacts import json_text
from customer360.contracts.base import Identifier, Text
from customer360.contracts.generation import (
    GenerationConfig,
    QualityCheck,
    meets_boundary_ratio,
)
from customer360.synth.ids import numbered_id

REGIONS = ("华东", "华北", "华南", "西南")
LEVELS = ("VIP", "standard")
CUSTOMER_STATUS = ("active", "dormant", "closed")
RISK_LEVELS = ("low", "medium", "high")
PRODUCT_TYPES = ("fund", "bond")
TRANSACTION_STATUS = ("success", "failed", "cancelled")
TRANSACTION_TYPES = ("buy", "sell", "subscribe", "redeem")
CHANNELS = ("app", "branch")
FLOW_CHANNELS = ("bank", "app", "branch")

Check = Callable[[object, GenerationConfig], tuple[object, bool]]


def _count(conn, sql: str, params: tuple = ()) -> int:
    return conn.execute(sql, params).fetchone()[0]


def _violations(conn, sql: str, params: tuple = ()) -> tuple[int, bool]:
    observed = _count(conn, sql, params)
    return observed, observed == 0


def _group_counts(
    conn, sql: str, allowed: tuple[str, ...], require_all: bool
) -> tuple[object, bool]:
    counts = dict(conn.execute(sql).fetchall())
    unexpected = sum(count for key, count in counts.items() if key not in allowed)
    missing = [key for key in allowed if require_all and counts.get(key, 0) == 0]
    observed = {key: counts.get(key, 0) for key in allowed} | {"unexpected": unexpected}
    return observed, unexpected == 0 and not missing


def _customer_count_exact(conn, config):
    observed = _count(conn, "SELECT COUNT(*) FROM dim_customer")
    return observed, observed == config.customers


def _customer_id_contiguous(conn, config):
    ids = [row[0] for row in conn.execute("SELECT customer_id FROM dim_customer").fetchall()]
    expected = [
        numbered_id("C", index, config.customers) for index in range(1, config.customers + 1)
    ]
    return len(ids), sorted(ids) == expected


def _customer_level_enum(conn, config):
    return _violations(
        conn, f"SELECT COUNT(*) FROM dim_customer WHERE customer_level NOT IN {LEVELS}"
    )


def _customer_level_both_present(conn, config):
    return _group_counts(
        conn,
        "SELECT customer_level, COUNT(*) FROM dim_customer GROUP BY customer_level",
        LEVELS,
        require_all=True,
    )


def _customer_status_enum(conn, config):
    return _violations(
        conn, f"SELECT COUNT(*) FROM dim_customer WHERE status NOT IN {CUSTOMER_STATUS}"
    )


def _customer_status_all_present(conn, config):
    return _group_counts(
        conn,
        "SELECT status, COUNT(*) FROM dim_customer GROUP BY status",
        CUSTOMER_STATUS,
        require_all=True,
    )


def _customer_risk_level_enum(conn, config):
    return _violations(
        conn, f"SELECT COUNT(*) FROM dim_customer WHERE risk_level NOT IN {RISK_LEVELS}"
    )


def _customer_gender_enum(conn, config):
    return _violations(conn, "SELECT COUNT(*) FROM dim_customer WHERE gender NOT IN ('F', 'M')")


def _customer_region_enum(conn, config):
    return _violations(conn, f"SELECT COUNT(*) FROM dim_customer WHERE region NOT IN {REGIONS}")


def _customer_birth_age_range(conn, config):
    rows = conn.execute("SELECT birth_date FROM dim_customer").fetchall()
    ages = []
    for (birth,) in rows:
        age = config.anchor_date.year - birth.year
        if (config.anchor_date.month, config.anchor_date.day) < (birth.month, birth.day):
            age -= 1
        ages.append(age)
    observed = {"min_age": min(ages), "max_age": max(ages)}
    return observed, all(18 <= age <= 85 for age in ages)


def _customer_occupation_nulls_exact(conn, config):
    observed = _count(conn, "SELECT COUNT(*) FROM dim_customer WHERE occupation IS NULL")
    ratio_ok = meets_boundary_ratio(observed, config.customers, 3, 100)
    return observed, observed == config.customers_with_null_occupation and ratio_ok


def _customer_registration_within_horizon(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM dim_customer WHERE registration_date < ? OR registration_date > ?",
        (config.horizon_start, config.anchor_date),
    )


def _manager_count_exact(conn, config):
    observed = _count(conn, "SELECT COUNT(*) FROM dim_service_manager")
    return observed, observed == config.managers


def _manager_entry_date_not_future(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM dim_service_manager WHERE entry_date > ?",
        (config.anchor_date,),
    )


def _manager_status_enum(conn, config):
    return _violations(
        conn, "SELECT COUNT(*) FROM dim_service_manager WHERE status NOT IN ('active', 'dormant')"
    )


def _product_count_exact(conn, config):
    observed = _count(conn, "SELECT COUNT(*) FROM dim_product")
    return observed, observed == config.products


def _product_currency_cny_only(conn, config):
    return _violations(conn, "SELECT COUNT(*) FROM dim_product WHERE currency <> 'CNY'")


def _product_type_enum(conn, config):
    return _violations(
        conn, f"SELECT COUNT(*) FROM dim_product WHERE product_type NOT IN {PRODUCT_TYPES}"
    )


def _product_listed_before_horizon(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM dim_product WHERE listing_date >= ?",
        (config.horizon_start,),
    )


def _date_dim_range_exact(conn, config):
    expected = (config.anchor_date - config.horizon_start).days + 1
    low, high, total = conn.execute(
        "SELECT MIN(calendar_date), MAX(calendar_date), COUNT(*) FROM dim_date"
    ).fetchone()
    observed = {"rows": total, "min": low.isoformat(), "max": high.isoformat()}
    ordered = low == config.horizon_start and high == config.anchor_date
    return observed, total == expected and ordered


def _date_dim_no_gaps(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM dim_date a WHERE a.calendar_date < ? AND NOT EXISTS ("
        "SELECT 1 FROM dim_date b WHERE b.calendar_date = a.calendar_date + INTERVAL 1 DAY)",
        (config.anchor_date,),
    )


def _date_dim_calendar_attributes(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM dim_date WHERE year <> year(calendar_date) "
        "OR quarter <> quarter(calendar_date) OR month <> month(calendar_date) "
        "OR week <> week(calendar_date) "
        "OR is_month_end <> (calendar_date = last_day(calendar_date)) "
        "OR is_quarter_end <> (month(calendar_date) IN (3, 6, 9, 12) "
        "AND calendar_date = last_day(calendar_date))",
    )


def _date_dim_id_matches_calendar(conn, config):
    return _violations(
        conn, "SELECT COUNT(*) FROM dim_date WHERE date_id <> CAST(calendar_date AS VARCHAR)"
    )


def _date_dim_covers_fact_dates(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM ("
        "SELECT transaction_date AS d FROM fact_transaction "
        "UNION ALL SELECT flow_date FROM fact_cash_flow "
        "UNION ALL SELECT snapshot_date FROM fact_asset_snapshot "
        "UNION ALL SELECT snapshot_date FROM fact_holding "
        "UNION ALL SELECT start_date FROM fact_service_relation "
        "UNION ALL SELECT end_date FROM fact_service_relation WHERE end_date IS NOT NULL"
        ") facts LEFT JOIN dim_date dim ON dim.calendar_date = facts.d "
        "WHERE dim.calendar_date IS NULL",
    )


def _service_interval_valid(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM fact_service_relation "
        "WHERE (end_date IS NOT NULL AND end_date <= start_date) OR end_date > ?",
        (config.anchor_date,),
    )


def _service_primary_no_overlap(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM fact_service_relation a JOIN fact_service_relation b "
        "ON a.customer_id = b.customer_id AND a.rowid < b.rowid "
        "WHERE a.is_primary AND b.is_primary "
        "AND a.start_date < COALESCE(b.end_date, DATE '9999-12-31') "
        "AND b.start_date < COALESCE(a.end_date, DATE '9999-12-31')",
    )


def _service_start_after_registration(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM fact_service_relation r JOIN dim_customer c "
        "USING (customer_id) WHERE r.start_date < c.registration_date",
    )


def _service_covers_all_customers(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM dim_customer c WHERE NOT EXISTS ("
        "SELECT 1 FROM fact_service_relation r WHERE r.customer_id = c.customer_id)",
    )


def _service_primary_exists_per_customer(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM dim_customer c WHERE NOT EXISTS ("
        "SELECT 1 FROM fact_service_relation r "
        "WHERE r.customer_id = c.customer_id AND r.is_primary)",
    )


def _service_ongoing_not_closed(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM fact_service_relation r JOIN dim_customer c "
        "USING (customer_id) WHERE r.end_date IS NULL AND c.status = 'closed'",
    )


def _asset_identity_total(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM fact_asset_snapshot "
        "WHERE total_asset <> cash_asset + investment_asset",
    )


def _asset_identity_net(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM fact_asset_snapshot WHERE net_asset <> total_asset - liability",
    )


def _asset_components_non_negative(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM fact_asset_snapshot WHERE total_asset < 0 OR cash_asset < 0 "
        "OR investment_asset < 0 OR liability < 0 OR net_asset < 0",
    )


def _asset_snapshot_dates_match_config(conn, config):
    dates = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT snapshot_date FROM fact_asset_snapshot ORDER BY snapshot_date"
        ).fetchall()
    ]
    expected = sorted(config.snapshot_dates)
    return [d.isoformat() for d in dates], dates == expected


def _asset_all_customers_per_date(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM ("
        "SELECT snapshot_date FROM fact_asset_snapshot "
        "GROUP BY snapshot_date HAVING COUNT(*) <> ?)",
        (config.customers,),
    )


def _asset_vip_wealthier_on_average(conn, config):
    rows = dict(
        conn.execute(
            "SELECT c.customer_level, AVG(a.total_asset) FROM fact_asset_snapshot a "
            "JOIN dim_customer c USING (customer_id) GROUP BY c.customer_level"
        ).fetchall()
    )
    observed = {level: str(rows[level]) for level in LEVELS if level in rows}
    complete = set(rows) == set(LEVELS)
    return observed, complete and rows["VIP"] > rows["standard"]


def _asset_level_overlap(conn, config):
    richest_standard, poorest_vip = conn.execute(
        "SELECT MAX(CASE WHEN c.customer_level = 'standard' THEN a.total_asset END), "
        "MIN(CASE WHEN c.customer_level = 'VIP' THEN a.total_asset END) "
        "FROM fact_asset_snapshot a JOIN dim_customer c USING (customer_id)"
    ).fetchone()
    observed = {"max_standard": str(richest_standard), "min_vip": str(poorest_vip)}
    return observed, richest_standard is not None and poorest_vip is not None and (
        richest_standard > poorest_vip
    )


def _holding_profit_identity(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM fact_holding WHERE unrealized_profit <> market_value - cost_value",
    )


def _holding_quantity_positive(conn, config):
    return _violations(conn, "SELECT COUNT(*) FROM fact_holding WHERE quantity <= 0")


def _holding_values_non_negative(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM fact_holding WHERE market_value < 0 OR cost_value < 0",
    )


def _holding_status_enum(conn, config):
    return _violations(conn, "SELECT COUNT(*) FROM fact_holding WHERE holding_status <> 'active'")


def _holding_no_position_customers_exact(conn, config):
    observed = _count(
        conn,
        "SELECT COUNT(*) FROM dim_customer c WHERE NOT EXISTS ("
        "SELECT 1 FROM fact_holding h WHERE h.customer_id = c.customer_id)",
    )
    ratio_ok = meets_boundary_ratio(observed, config.customers, 1, 20)
    return observed, observed == config.customers_without_positions and ratio_ok


def _transaction_count_exact(conn, config):
    observed = _count(conn, "SELECT COUNT(*) FROM fact_transaction")
    return observed, observed == config.transactions


def _transaction_status_enum(conn, config):
    return _violations(
        conn, f"SELECT COUNT(*) FROM fact_transaction WHERE status NOT IN {TRANSACTION_STATUS}"
    )


def _transaction_status_all_present(conn, config):
    return _group_counts(
        conn,
        "SELECT status, COUNT(*) FROM fact_transaction GROUP BY status",
        TRANSACTION_STATUS,
        require_all=True,
    )


def _transaction_amount_non_negative(conn, config):
    return _violations(conn, "SELECT COUNT(*) FROM fact_transaction WHERE amount < 0")


def _transaction_quantity_positive(conn, config):
    return _violations(conn, "SELECT COUNT(*) FROM fact_transaction WHERE quantity <= 0")


def _transaction_fee_non_negative(conn, config):
    return _violations(conn, "SELECT COUNT(*) FROM fact_transaction WHERE fee < 0")


def _transaction_type_enum(conn, config):
    return _violations(
        conn,
        f"SELECT COUNT(*) FROM fact_transaction WHERE transaction_type NOT IN {TRANSACTION_TYPES}",
    )


def _transaction_channel_enum(conn, config):
    return _violations(
        conn, f"SELECT COUNT(*) FROM fact_transaction WHERE channel NOT IN {CHANNELS}"
    )


def _transaction_date_within_horizon(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM fact_transaction WHERE transaction_date < ? OR transaction_date > ?",
        (config.horizon_start, config.anchor_date),
    )


def _transaction_window_boundary_present(conn, config):
    # The frozen rolling-day convention is [anchor-(N-1), anchor]; 90 days from the
    # data dictionary. Boundary exercise: outside day, first window day, anchor day.
    window_start = config.anchor_date - timedelta(days=89)
    outside = window_start - timedelta(days=1)
    boundary_days = (outside, window_start, config.anchor_date)
    counts = dict(
        conn.execute(
            "SELECT transaction_date, COUNT(*) FROM fact_transaction "
            "WHERE status = 'success' AND transaction_date IN (?, ?, ?) GROUP BY transaction_date",
            boundary_days,
        ).fetchall()
    )
    observed = {key.isoformat(): counts.get(key, 0) for key in boundary_days}
    return observed, all(counts.get(key, 0) >= 1 for key in boundary_days)


def _transaction_duplicate_amount_present(conn, config):
    duplicated = _count(
        conn,
        "SELECT COUNT(*) FROM (SELECT amount FROM fact_transaction WHERE status = 'success' "
        "GROUP BY amount HAVING COUNT(*) >= 2)",
    )
    return duplicated, duplicated >= 1


def _no_transaction_customers_exact(conn, config):
    observed = _count(
        conn,
        "SELECT COUNT(*) FROM dim_customer c WHERE NOT EXISTS ("
        "SELECT 1 FROM fact_transaction t WHERE t.customer_id = c.customer_id)",
    )
    ratio_ok = meets_boundary_ratio(observed, config.customers, 1, 20)
    return observed, observed == config.customers_without_transactions and ratio_ok


def _cash_flow_in_positive(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM fact_cash_flow WHERE flow_type = 'in' AND signed_amount <= 0",
    )


def _cash_flow_out_negative(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM fact_cash_flow WHERE flow_type = 'out' AND signed_amount >= 0",
    )


def _cash_flow_date_within_horizon(conn, config):
    return _violations(
        conn,
        "SELECT COUNT(*) FROM fact_cash_flow WHERE flow_date < ? OR flow_date > ?",
        (config.horizon_start, config.anchor_date),
    )


def _cash_flow_channel_enum(conn, config):
    return _violations(
        conn, f"SELECT COUNT(*) FROM fact_cash_flow WHERE channel NOT IN {FLOW_CHANNELS}"
    )


def _cash_flow_status_success(conn, config):
    return _violations(conn, "SELECT COUNT(*) FROM fact_cash_flow WHERE status <> 'success'")


def _cash_flow_count_exact(conn, config):
    observed = _count(conn, "SELECT COUNT(*) FROM fact_cash_flow")
    return observed, observed == config.cash_flows


CHECKS: tuple[tuple[Identifier, Text, Check], ...] = (
    ("customer_count_exact", "dim_customer 行数等于配置客户数", _customer_count_exact),
    ("customer_id_contiguous", "客户ID从C001连续编号无缺口", _customer_id_contiguous),
    ("customer_level_enum", "客户等级只允许VIP/standard", _customer_level_enum),
    ("customer_level_both_present", "VIP与standard等级同时出现", _customer_level_both_present),
    ("customer_status_enum", "客户状态只允许active/dormant/closed", _customer_status_enum),
    ("customer_status_all_present", "三种客户状态同时出现", _customer_status_all_present),
    ("customer_risk_level_enum", "客户风险等级只允许low/medium/high", _customer_risk_level_enum),
    ("customer_gender_enum", "性别只允许F/M", _customer_gender_enum),
    ("customer_region_enum", "地区在固定四个区域内", _customer_region_enum),
    ("customer_birth_age_range", "按anchor计算年龄在18到85岁之间", _customer_birth_age_range),
    (
        "customer_occupation_nulls_exact",
        "职业为空的客户数等于配置的可空属性数量",
        _customer_occupation_nulls_exact,
    ),
    (
        "customer_registration_within_horizon",
        "注册日期落在数据窗口内且不超过anchor",
        _customer_registration_within_horizon,
    ),
    ("manager_count_exact", "服务经理行数等于配置数量", _manager_count_exact),
    ("manager_entry_date_not_future", "经理入职日期不晚于anchor", _manager_entry_date_not_future),
    ("manager_status_enum", "经理状态只允许active/dormant", _manager_status_enum),
    ("product_count_exact", "产品行数等于配置数量", _product_count_exact),
    ("product_currency_cny_only", "初始化数据只包含CNY产品", _product_currency_cny_only),
    ("product_type_enum", "产品类型只允许fund/bond", _product_type_enum),
    ("product_listed_before_horizon", "产品上市日期早于数据窗口", _product_listed_before_horizon),
    ("date_dim_range_exact", "日期维度恰好覆盖窗口首日至anchor", _date_dim_range_exact),
    ("date_dim_no_gaps", "日期维度连续无缺口", _date_dim_no_gaps),
    (
        "date_dim_calendar_attributes",
        "年/季/月/ISO周/月末/季末属性与日历一致",
        _date_dim_calendar_attributes,
    ),
    (
        "date_dim_id_matches_calendar",
        "date_id主键与calendar_date的ISO日期一致",
        _date_dim_id_matches_calendar,
    ),
    (
        "date_dim_covers_fact_dates",
        "全部事实表日期都被日期维度覆盖",
        _date_dim_covers_fact_dates,
    ),
    (
        "service_interval_valid",
        "服务区间满足end>start且结束不超过anchor",
        _service_interval_valid,
    ),
    (
        "service_primary_no_overlap",
        "同一客户的主服务经理区间在任意日期不重叠",
        _service_primary_no_overlap,
    ),
    (
        "service_start_after_registration",
        "服务关系开始日期不早于客户注册日期",
        _service_start_after_registration,
    ),
    (
        "service_covers_all_customers",
        "每个客户至少有一条服务关系",
        _service_covers_all_customers,
    ),
    (
        "service_primary_exists_per_customer",
        "每个客户至少有一条主服务关系",
        _service_primary_exists_per_customer,
    ),
    (
        "service_ongoing_not_closed",
        "未终止的服务关系只属于非注销客户",
        _service_ongoing_not_closed,
    ),
    ("asset_identity_total", "总资产恒等式total=cash+investment", _asset_identity_total),
    ("asset_identity_net", "净资产恒等式net=total-liability", _asset_identity_net),
    (
        "asset_components_non_negative",
        "资产各组成部分非负",
        _asset_components_non_negative,
    ),
    (
        "asset_snapshot_dates_match_config",
        "资产估值日集合与配置一致（多估值日）",
        _asset_snapshot_dates_match_config,
    ),
    (
        "asset_all_customers_per_date",
        "每个估值日都覆盖全部客户",
        _asset_all_customers_per_date,
    ),
    (
        "asset_vip_wealthier_on_average",
        "VIP客户平均总资产高于standard客户",
        _asset_vip_wealthier_on_average,
    ),
    (
        "asset_level_overlap",
        "资产分布与等级相关但不由等级完全决定",
        _asset_level_overlap,
    ),
    (
        "holding_profit_identity",
        "持仓未实现盈亏=市值-成本市值",
        _holding_profit_identity,
    ),
    ("holding_quantity_positive", "持仓数量为正", _holding_quantity_positive),
    ("holding_values_non_negative", "持仓市值与成本非负", _holding_values_non_negative),
    ("holding_status_enum", "持仓状态为active", _holding_status_enum),
    (
        "holding_no_position_customers_exact",
        "无持仓客户数等于配置数量",
        _holding_no_position_customers_exact,
    ),
    ("transaction_count_exact", "交易行数严格等于配置交易数", _transaction_count_exact),
    (
        "transaction_status_enum",
        "交易状态只允许success/failed/cancelled",
        _transaction_status_enum,
    ),
    (
        "transaction_status_all_present",
        "三种交易状态同时出现",
        _transaction_status_all_present,
    ),
    ("transaction_amount_non_negative", "交易金额非负", _transaction_amount_non_negative),
    ("transaction_quantity_positive", "交易数量为正", _transaction_quantity_positive),
    ("transaction_fee_non_negative", "交易费用非负", _transaction_fee_non_negative),
    (
        "transaction_type_enum",
        "交易类型只允许buy/sell/subscribe/redeem",
        _transaction_type_enum,
    ),
    ("transaction_channel_enum", "交易渠道只允许app/branch", _transaction_channel_enum),
    ("transaction_date_within_horizon", "交易日期落在数据窗口内", _transaction_date_within_horizon),
    (
        "transaction_window_boundary_present",
        "近90天窗口边界日（外一天/首日/anchor）都有成功交易",
        _transaction_window_boundary_present,
    ),
    (
        "transaction_duplicate_amount_present",
        "成功交易中存在重复金额",
        _transaction_duplicate_amount_present,
    ),
    (
        "no_transaction_customers_exact",
        "无交易客户数等于配置数量",
        _no_transaction_customers_exact,
    ),
    ("cash_flow_in_positive", "资金流in类型金额为正", _cash_flow_in_positive),
    ("cash_flow_out_negative", "资金流out类型金额为负", _cash_flow_out_negative),
    ("cash_flow_date_within_horizon", "资金流日期落在数据窗口内", _cash_flow_date_within_horizon),
    ("cash_flow_channel_enum", "资金流渠道只允许bank/app/branch", _cash_flow_channel_enum),
    ("cash_flow_status_success", "资金流状态均为success", _cash_flow_status_success),
    ("cash_flow_count_exact", "资金流行数等于配置数量", _cash_flow_count_exact),
)


def run_quality_checks(conn, config: GenerationConfig) -> tuple[QualityCheck, ...]:
    checks = []
    for check_id, description, evaluate in CHECKS:
        observed, passed = evaluate(conn, config)
        checks.append(
            QualityCheck(
                check_id=check_id,
                description=description,
                passed=passed,
                observed=json_text(observed),
            )
        )
    return tuple(checks)
