"""Vendor-independent model adapter. Default is offline; network stays fail-closed."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from time import perf_counter
from typing import Any, Literal, Protocol

from customer360.contracts.adapter import AdapterParameters, ModelCallRecord
from customer360.errors import QueryRejected

UNKNOWN_FIELD_TOKENS = ("手机号", "手机号码", "身份证", "身份证号")
LATEST_TOKENS = ("最新快照", "最新资产快照", "最近一次快照", "各自最新快照")
GROUP_DIM_TOKENS: dict[str, tuple[str, ...]] = {
    "region": ("按地区", "分地区", "各地区", "按客户地区", "地区拆开", "按地区分组"),
    "customer_level": (
        "按客户等级",
        "分客户等级",
        "各客户等级",
        "客户等级拆开",
        "按客户等级分组",
        "按等级",
        "分等级",
        "各等级",
        "按等级分组",
    ),
    "risk_level": (
        "按风险等级",
        "分风险等级",
        "各风险等级",
        "风险等级拆开",
        "按风险等级分组",
        "按风险",
        "分风险",
        "各风险",
    ),
    "gender": ("按性别", "分性别", "各性别", "按客户性别", "性别拆开", "按性别分组"),
    "channel": (
        "按渠道",
        "分渠道",
        "各渠道",
        "渠道拆开",
        "按渠道分组",
        "按交易渠道",
        "按资金渠道",
    ),
    "transaction_type": (
        "按交易类型",
        "分交易类型",
        "各交易类型",
        "交易类型拆开",
        "按交易类型分组",
    ),
    "flow_type": ("按流向", "分流向", "各流向", "流向拆开", "按流向分组", "按资金流向"),
}
GROUP_REGION_TOKENS = GROUP_DIM_TOKENS["region"]
JOIN_TOKENS = (
    "有成功交易",
    "发生过成功交易",
    "成功交易VIP",
    "成功App交易",
    "成功网点交易",
    "成功买入交易",
    "成功卖出交易",
    "有成功App交易",
    "有成功网点交易",
    "有成功买入交易",
    "有成功卖出交易",
    "发生过成功App交易",
    "发生过成功网点交易",
    "发生过成功买入交易",
    "发生过成功卖出交易",
)
NULL_OCCUPATION_TOKENS = (
    "职业为空",
    "职业字段为空",
    "没有填写职业",
    "职业信息缺失",
    "职业缺失",
    "未填写职业",
)
WINDOW_START_TOKENS = ("窗口首日", "第一天", "起始日")
WINDOW_BEFORE_TOKENS = ("窗口外前一日", "窗口外一天", "前一天", "前一日")
PII_REFUSAL = (
    "UNKNOWN_FIELD",
    "客户手机号或身份证不是已声明字段。",
    "请改用已授权的客户属性或指标。",
)
NEGATION_PATTERNS = (
    re.compile(r"非\s*VIP|不是\s*VIP|不属于\s*VIP"),
    re.compile(r"非\s*(?:低|中|高)风险|不是\s*(?:低|中|高)风险"),
    re.compile(r"非\s*(?:在用|休眠|注销|已注销)|未\s*(?:在用|注销)"),
    re.compile(r"职业\s*(?:不为空|非空|填写完整|有效|存在)"),
    re.compile(r"非\s*(?:买入|卖出|申购|赎回)"),
    re.compile(r"非\s*(?:App|网点|银行)"),
)
DATE_PATTERN = re.compile(
    r"(?P<iso>\d{4}-\d{2}-\d{2})|(?P<y>\d{4})年(?P<m>\d{1,2})月(?P<d>\d{1,2})日"
)
DAYS_PATTERN = re.compile(r"(?:近|往前)\s*(?P<days>\d+)\s*(?:个)?(?:自然)?[日天]")
VALUE_HINTS = (
    ("VIP", "customer_level", "eq", "VIP"),
    ("华东", "region", "eq", "华东"),
    ("华北", "region", "eq", "华北"),
    ("华南", "region", "eq", "华南"),
    ("西南", "region", "eq", "西南"),
)
LOCAL_PARAMETERS = AdapterParameters(
    temperature=0, top_p=1, seed=0, max_output_tokens=0, max_retries=0
)


@dataclass(frozen=True)
class AdapterPacket:
    question: str
    conversation: tuple[tuple[str, str], ...]
    anchor_date: date
    metrics: tuple[dict[str, Any], ...]
    columns: tuple[dict[str, Any], ...]
    joins: tuple[dict[str, Any], ...]
    glossary: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class IntentFilter:
    field: str
    operator: str
    values: tuple[object, ...] = ()
    side: Literal["metric", "join"] = "metric"


@dataclass(frozen=True)
class Intent:
    action: Literal["answer", "clarify", "refuse"]
    metric_name: str | None = None
    filters: tuple[IntentFilter, ...] = ()
    time_kind: Literal["rolling", "point_in_time", "latest_snapshot"] | None = None
    days: int | None = None
    time_date: date | None = None
    join_path: str | None = None
    group_by: tuple[str, ...] = ()
    missing_slots: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()
    reason_code: str | None = None
    reason: str | None = None
    alternative: str | None = None
    evidence: tuple[str, ...] = ()


class ModelAdapter(Protocol):
    adapter_id: str
    provider: str
    model: str

    def complete(self, packet: AdapterPacket) -> tuple[Intent, ModelCallRecord]: ...


def _digest(packet: AdapterPacket) -> str:
    payload = {
        "question": packet.question,
        "conversation": list(packet.conversation),
        "anchor_date": packet.anchor_date.isoformat(),
        "metrics": [item.get("metric_name") for item in packet.metrics],
        "joins": [item.get("path_name") for item in packet.joins],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _norm(text: str) -> str:
    return text.replace(" ", "").replace("，", "").rstrip("。？?")


def _combined_text(packet: AdapterPacket) -> str:
    parts = [packet.question, *(content for _role, content in packet.conversation)]
    return "\n".join(parts)


def _parse_date(text: str) -> date | None:
    found: date | None = None
    for match in DATE_PATTERN.finditer(text):
        if match.group("iso"):
            parsed = date.fromisoformat(match.group("iso"))
        else:
            parsed = date(int(match.group("y")), int(match.group("m")), int(match.group("d")))
        found = parsed
    return found


def _parse_days(text: str) -> int | None:
    if "最近三个月" in text or "近三个月" in text:
        return None
    match = DAYS_PATTERN.search(text)
    if match is None:
        return None
    return int(match.group("days"))


def _has_unsupported_negation(text: str) -> bool:
    return any(pattern.search(text) for pattern in NEGATION_PATTERNS)


def _is_join_query(question: str) -> bool:
    if "客户" not in question and "人数" not in question:
        return False
    if any(
        token in question
        for token in (
            "交易笔数",
            "交易次数",
            "交易金额",
            "交易量",
            "资金流笔数",
            "资金流金额",
            "持仓笔数",
            "持仓数量",
        )
    ):
        return False
    has_join_predicate = any(
        token in question
        for token in (
            "有成功交易",
            "发生过成功交易",
            "发生过",
            "有成功",
            "成功交易",
            "分配有",
            "存在服务关系",
            "有服务关系",
            "有资金流",
            "发生过资金流",
            "有持仓",
            "存在持仓",
            "有资产快照",
            "存在资产快照",
        )
    )
    is_customer_agg = any(
        token in question
        for token in (
            "去重客户数",
            "去重人数",
            "去重客户",
            "客户数量",
            "客户有多少人",
            "客户人数",
            "客户数",
        )
    )
    return has_join_predicate and is_customer_agg


def _executable_join(packet: AdapterPacket, question: str = "") -> str | None:
    executable_paths = {
        item.get("path_name") for item in packet.joins if item.get("compile_status") == "executable"
    }
    if not executable_paths:
        return None
    if (
        any(k in question for k in ("资金流", "现金流", "流向", "流入", "流出"))
        and "customer_cash_flows" in executable_paths
    ):
        return "customer_cash_flows"
    if (
        any(k in question for k in ("持仓", "资产持有", "投资持仓"))
        and "customer_holdings" in executable_paths
    ):
        return "customer_holdings"
    if (
        any(k in question for k in ("资产快照", "快照净资产", "总资产快照"))
        and "customer_asset_snapshots" in executable_paths
    ):
        return "customer_asset_snapshots"
    if (
        any(k in question for k in ("服务关系", "分配有", "主管经理", "经理关系", "服务经理"))
        and "customer_service_relations" in executable_paths
    ):
        return "customer_service_relations"
    if (
        any(k in question for k in ("交易", "买入", "卖出", "申购", "赎回", "发生过"))
        and "customer_transactions" in executable_paths
    ):
        return "customer_transactions"
    if "customer_transactions" in executable_paths:
        return "customer_transactions"
    return next(iter(sorted(executable_paths)), None)


class NetworkModelAdapter:
    """Placeholder for vendor SDKs. Network is not permitted until ROADMAP §10 is decided."""

    adapter_id = "network"
    provider = "unspecified"
    model = "unspecified"

    def __init__(self, *, network_enabled: bool = False) -> None:
        if not network_enabled:
            raise ValueError("external model network is not permitted")
        raise ValueError("no vendor SDK is installed; network adapter is fail-closed")

    def complete(self, packet: AdapterPacket) -> tuple[Intent, ModelCallRecord]:
        raise ValueError("external model network is not permitted")


class LocalDeterministicAdapter:
    """Offline planner: public metadata + deterministic NL cues. Not an LLM."""

    adapter_id = "local_deterministic"
    provider = "offline"
    model = "c360-local-planner-0.1"

    def __init__(self) -> None:
        self._cache: dict[str, Intent] = {}

    def complete(self, packet: AdapterPacket) -> tuple[Intent, ModelCallRecord]:
        started = perf_counter()
        digest = _digest(packet)
        cached = self._cache.get(digest)
        intent = cached if cached is not None else self._parse(packet)
        if cached is None:
            self._cache[digest] = intent
        record = ModelCallRecord(
            adapter_id=self.adapter_id,
            provider=self.provider,
            model=self.model,
            network_used=False,
            cache_hit=cached is not None,
            retry_count=0,
            elapsed_ms=(perf_counter() - started) * 1000,
            prompt_digest=digest,
            parameters=LOCAL_PARAMETERS,
        )
        return intent, record

    def _parse(self, packet: AdapterPacket) -> Intent:
        question = packet.question
        text = _combined_text(packet)
        if any(token in question for token in UNKNOWN_FIELD_TOKENS):
            code, reason, alternative = PII_REFUSAL
            return Intent(
                action="refuse",
                reason_code=code,
                reason=reason,
                alternative=alternative,
                evidence=("unknown_entity_field",),
            )
        if _has_unsupported_negation(question):
            return Intent(
                action="refuse",
                reason_code="UNSUPPORTED_QUERY",
                reason="不支持否定条件或反向过滤查询。",
                alternative="请使用已授权的正向等值或存在性过滤条件。",
                evidence=("negation_unsupported",),
            )
        latest = any(token in text for token in LATEST_TOKENS)
        vague = (
            any(token in question for token in ("最近", "近期"))
            and not latest
            and "近90" not in question
            and "估值日" not in question
            and _parse_days(text) is None
        )
        if vague:
            return Intent(
                action="clarify",
                missing_slots=("time_window",),
                questions=("请给出含锚点日期的近N个自然日窗口。",),
                evidence=("missing_time_window",),
            )
        metric = self._pick_metric(packet, question, text, latest)
        if metric is None:
            return Intent(
                action="refuse",
                reason_code="UNKNOWN_METRIC",
                reason="无法从已授权指标中解析该问题。",
                alternative="请改用已发布的指标名称或业务口径。",
                evidence=("unresolved_metric",),
            )
        join_path = None
        if _is_join_query(question):
            join_path = _executable_join(packet, question)
            if join_path is None:
                return Intent(
                    action="refuse",
                    reason_code="UNSUPPORTED_QUERY",
                    reason="请求的 Join 路径不可执行。",
                    alternative="请使用已授权且可编译的客户-交易路径。",
                    evidence=("join_not_executable",),
                )
        time_kind, days, time_date, missing = self._time_for(
            metric, packet, text, latest, join_path
        )
        if missing:
            return Intent(
                action="clarify",
                metric_name=metric["metric_name"],
                missing_slots=missing,
                questions=("请给出含锚点日期的近N个自然日窗口。",),
                evidence=("metric_requires_time", metric["metric_name"]),
            )
        filters = self._filters(question, metric, time_kind, days, time_date, join_path)
        group_by: tuple[str, ...] = ()
        allowed_groups = tuple(metric.get("allowed_group_dimensions") or ())
        for dim, tokens in GROUP_DIM_TOKENS.items():
            if dim in allowed_groups and any(token in question for token in tokens):
                group_by = (dim,)
                break
        return Intent(
            action="answer",
            metric_name=metric["metric_name"],
            filters=filters,
            time_kind=time_kind,
            days=days,
            time_date=time_date,
            join_path=join_path,
            group_by=group_by,
            evidence=("local_planner", metric["metric_name"]),
        )

    def _pick_metric(
        self, packet: AdapterPacket, question: str, text: str, latest: bool
    ) -> dict[str, Any] | None:
        scored: list[tuple[int, str, dict[str, Any]]] = []
        for metric in packet.metrics:
            score = self._score(metric, question, text, latest)
            scored.append((score, metric.get("metric_name") or "", metric))
        scored.sort(key=lambda item: (-item[0], item[1]))
        if not scored or scored[0][0] <= 0:
            return None
        return scored[0][2]

    def _score(self, metric: dict[str, Any], question: str, text: str, latest: bool) -> int:
        name = str(metric.get("business_name") or "")
        metric_id = str(metric.get("metric_name") or "")
        unit = str(metric.get("unit") or "")
        semantics = str(metric.get("time_semantics") or "none")
        q = question
        score = 0
        qn = _norm(q)
        for example in metric.get("example_questions") or ():
            example_n = _norm(str(example))
            if example_n == qn:
                score += 120
            elif example_n and example_n in qn:
                score += 80
        if name and name in q:
            score += 50
        tokens = (
            "净流入",
            "流入减流出",
            "入账",
            "流出",
            "流入",
            "总资产",
            "净资产",
            "活跃",
            "失败",
            "撤销",
            "主服务",
            "持仓",
            "买入",
            "App",
            "休眠",
            "注销",
            "高风险",
        )
        for token in tokens:
            in_q = token in q or (token == "流入减流出" and "流入减流出" in text)
            in_name = token in name or token in metric_id
            if token == "流入" and ("净流入" in q or "流入减流出" in q):
                continue
            if in_q and in_name:
                score += 28
            elif in_name and not in_q:
                score -= 18
            elif in_q and not in_name and token not in {"活跃"}:
                score -= 8
        wants_amount = any(token in q for token in ("金额", "净流入", "流入", "流出", "资产"))
        wants_count = any(
            token in q
            for token in ("笔数", "次数", "客户数", "人数", "条数", "多不多", "数量", "多少人")
        )
        table = str(metric.get("source_table") or "")
        is_join = _is_join_query(q)
        if is_join:
            if metric_id == "distinct_customer_count":
                score += 85
            if table == "fact_transaction":
                score -= 60
        if any(
            token in q
            for token in (
                "客户数",
                "客户人数",
                "多少人",
                "VIP客户",
                "标准等级客户",
                "低风险客户",
                "中风险客户",
                "高风险客户",
                "在用客户",
                "休眠客户",
                "已注销客户",
                "客户一共",
                "去重客户数",
                "去重人数",
            )
        ):
            if metric_id == "distinct_customer_count":
                score += 40
            if "服务关系" in name:
                score -= 35
            if table == "dim_customer" and metric.get("operation") == "count_distinct":
                score += 8
        if "在用客户" in q and metric_id == "active_customer_count":
            score += 50
        if "休眠客户" in q and metric_id == "dormant_customer_count":
            score += 50
        if ("已注销客户" in q or "注销客户" in q) and metric_id == "closed_customer_count":
            score += 50
        if "高风险客户" in q and metric_id == "high_risk_customer_count":
            score += 50
        if "买入" in q and ("笔数" in q or "次数" in q) and not is_join:
            if metric_id == "successful_buy_transaction_count":
                score += 40
        if "App" in q and ("笔数" in q or "次数" in q) and not is_join:
            if metric_id == "successful_app_transaction_count":
                score += 40
        if "服务关系" in q:
            score += 25 if "service_relation" in table else -20
        elif "客户" in q and "交易" not in q and "资金" not in q:
            if table == "dim_customer":
                score += 12
            elif "service_relation" in table:
                score -= 20
        if "持仓" in q:
            score += 25 if table == "fact_holding" else -15
        if "金额" in q and unit == "CNY":
            score += 18
        if "金额" in q and unit == "count":
            score -= 30
        if wants_count and "金额" not in q and unit == "count":
            score += 12
        if wants_count and "金额" not in q and unit == "CNY" and "资产" not in q:
            score -= 24
        if latest:
            score += 45 if semantics == "latest_snapshot_required" else -45
        elif "估值日" in q:
            score += 30 if semantics == "point_in_time_required" else -25
        elif _parse_days(text) is not None or "近90" in q or "最近" in q or "近期" in q:
            if is_join:
                if metric_id == "distinct_customer_count":
                    score += 55
                if str(metric.get("source_table")) == "fact_transaction":
                    score -= 40
            elif semantics == "rolling_required":
                score += 22
            else:
                score -= 16
        elif semantics == "none":
            score += 16
        else:
            score -= 12
        if is_join:
            if metric_id == "distinct_customer_count":
                score += 40
        if "活跃" in q and "活跃" in name:
            score += 25
        if any(token in q for token in ("客户数", "客户人数")) and metric_id == (
            "distinct_customer_count"
        ):
            score += 20
        if wants_amount and "交易" in q and metric_id == "successful_transaction_amount":
            score += 12
        if ("交易笔" in q or "交易次数" in q or "交易多不多" in q) and metric_id == (
            "successful_transaction_count"
        ):
            score += 20
        if "失败交易" in q and "失败" in name:
            score += 20
        if wants_amount and "资产" in q and "资产" in name:
            score += 8
        return score

    def _time_for(
        self,
        metric: dict[str, Any],
        packet: AdapterPacket,
        text: str,
        latest: bool,
        join_path: str | None,
    ) -> tuple[
        Literal["rolling", "point_in_time", "latest_snapshot"] | None,
        int | None,
        date | None,
        tuple[str, ...],
    ]:
        semantics = str(metric.get("time_semantics") or "none")
        parsed_date = _parse_date(text) or packet.anchor_date
        days = _parse_days(text)
        if join_path:
            if join_path in {"customer_transactions", "customer_cash_flows"}:
                if days is None:
                    return None, None, None, ("time_window",)
                return "rolling", days, parsed_date, ()
            if join_path in {"customer_holdings", "customer_asset_snapshots"}:
                explicit = _parse_date(text)
                return "point_in_time", None, explicit or packet.anchor_date, ()
            if join_path == "customer_service_relations":
                return None, None, None, ()
        if semantics == "latest_snapshot_required" or latest:
            return "latest_snapshot", None, parsed_date, ()
        if semantics == "point_in_time_required":
            explicit = _parse_date(text)
            if explicit is None and "估值日" not in text:
                return None, None, None, ("time_window",)
            return "point_in_time", None, explicit or packet.anchor_date, ()
        if semantics == "rolling_required":
            if days is None:
                return None, None, None, ("time_window",)
            return "rolling", days, parsed_date, ()
        return None, None, None, ()

    def _filters(
        self,
        question: str,
        metric: dict[str, Any],
        time_kind: str | None,
        days: int | None,
        time_date: date | None,
        join_path: str | None,
    ) -> tuple[IntentFilter, ...]:
        found: list[IntentFilter] = []
        allowed = set(metric.get("allowed_filter_columns") or ())
        fixed = metric.get("fixed_filters") or {}

        # 1. occupation IS NULL
        if "occupation" in allowed and "occupation" not in fixed:
            if any(token in question for token in NULL_OCCUPATION_TOKENS) or (
                "职业" in question
                and any(token in question for token in ("空", "缺失", "没有填写", "未填写"))
                and "非空" not in question
                and "不为空" not in question
            ):
                found.append(IntentFilter(field="occupation", operator="is_null", side="metric"))

        # 2. customer_level
        if "customer_level" in allowed and "customer_level" not in fixed:
            has_vip = "VIP" in question
            has_standard = "标准等级" in question
            if has_vip and has_standard:
                raise QueryRejected("UNSUPPORTED_QUERY", "不支持多等级组合条件。")
            if has_vip:
                found.append(
                    IntentFilter(
                        field="customer_level", operator="eq", values=("VIP",), side="metric"
                    )
                )
            elif has_standard:
                found.append(
                    IntentFilter(
                        field="customer_level", operator="eq", values=("standard",), side="metric"
                    )
                )

        # 3. region
        if "region" in allowed and "region" not in fixed:
            matched_regions = [r for r in ("华东", "华北", "华南", "西南") if r in question]
            if len(matched_regions) > 1:
                raise QueryRejected("UNSUPPORTED_QUERY", "不支持跨地区多选或组合条件。")
            if len(matched_regions) == 1:
                found.append(
                    IntentFilter(
                        field="region", operator="eq", values=(matched_regions[0],), side="metric"
                    )
                )

        # 4. gender
        if "gender" in allowed and "gender" not in fixed:
            has_m = "男性" in question or "男客户" in question
            has_f = "女性" in question or "女客户" in question
            if has_m and has_f:
                raise QueryRejected("UNSUPPORTED_QUERY", "不支持多性别组合条件。")
            if has_m:
                found.append(
                    IntentFilter(field="gender", operator="eq", values=("M",), side="metric")
                )
            elif has_f:
                found.append(
                    IntentFilter(field="gender", operator="eq", values=("F",), side="metric")
                )

        # 5. risk_level
        if "risk_level" in allowed and "risk_level" not in fixed:
            matched_risks = [
                ("low", "低风险"),
                ("medium", "中风险"),
                ("high", "高风险"),
            ]
            found_risks = [val for val, kw in matched_risks if kw in question]
            if len(found_risks) > 1:
                raise QueryRejected("UNSUPPORTED_QUERY", "不支持多风险等级组合条件。")
            if len(found_risks) == 1:
                found.append(
                    IntentFilter(
                        field="risk_level", operator="eq", values=(found_risks[0],), side="metric"
                    )
                )

        # 6. customer status (only for dim_customer table)
        if str(metric.get("source_table")) == "dim_customer":
            if "status" in allowed and "status" not in fixed:
                if "在用" in question:
                    found.append(
                        IntentFilter(
                            field="status", operator="eq", values=("active",), side="metric"
                        )
                    )
                elif "休眠" in question:
                    found.append(
                        IntentFilter(
                            field="status", operator="eq", values=("dormant",), side="metric"
                        )
                    )
                elif "已注销" in question or "注销" in question:
                    found.append(
                        IntentFilter(
                            field="status", operator="eq", values=("closed",), side="metric"
                        )
                    )

        # 7. single-table transaction / cash flow / service relation filters
        if not join_path:
            if "transaction_type" in allowed and "transaction_type" not in fixed:
                if "买入" in question:
                    found.append(
                        IntentFilter(
                            field="transaction_type", operator="eq", values=("buy",), side="metric"
                        )
                    )
                elif "卖出" in question:
                    found.append(
                        IntentFilter(
                            field="transaction_type", operator="eq", values=("sell",), side="metric"
                        )
                    )
                elif "申购" in question:
                    found.append(
                        IntentFilter(
                            field="transaction_type",
                            operator="eq",
                            values=("subscribe",),
                            side="metric",
                        )
                    )
                elif "赎回" in question:
                    found.append(
                        IntentFilter(
                            field="transaction_type",
                            operator="eq",
                            values=("redeem",),
                            side="metric",
                        )
                    )

            if "channel" in allowed and "channel" not in fixed:
                if "App" in question or "App渠道" in question:
                    found.append(
                        IntentFilter(field="channel", operator="eq", values=("app",), side="metric")
                    )
                elif "网点" in question or "网点渠道" in question:
                    found.append(
                        IntentFilter(
                            field="channel", operator="eq", values=("branch",), side="metric"
                        )
                    )
                elif "银行" in question or "银行渠道" in question:
                    found.append(
                        IntentFilter(
                            field="channel", operator="eq", values=("bank",), side="metric"
                        )
                    )

            if "flow_type" in allowed and "flow_type" not in fixed:
                if "流入" in question and "净流入" not in question:
                    found.append(
                        IntentFilter(
                            field="flow_type", operator="eq", values=("in",), side="metric"
                        )
                    )
                elif "流出" in question and "净流入" not in question:
                    found.append(
                        IntentFilter(
                            field="flow_type", operator="eq", values=("out",), side="metric"
                        )
                    )

            if "is_primary" in allowed and "is_primary" not in fixed:
                if "主服务标记" in question:
                    found.append(
                        IntentFilter(
                            field="is_primary", operator="eq", values=(True,), side="metric"
                        )
                    )
                elif "非主服务标记" in question:
                    found.append(
                        IntentFilter(
                            field="is_primary", operator="eq", values=(False,), side="metric"
                        )
                    )

        # 8. rolling window boundary filters
        if time_kind == "rolling" and days is not None and time_date is not None:
            start = time_date - timedelta(days=days - 1)
            extra_date = None
            if any(token in question for token in WINDOW_START_TOKENS):
                extra_date = start
            elif any(token in question for token in WINDOW_BEFORE_TOKENS):
                extra_date = start - timedelta(days=1)
            if extra_date is not None:
                found.append(
                    IntentFilter(
                        field="transaction_date",
                        operator="eq",
                        values=(extra_date.isoformat(),),
                        side="join" if join_path else "metric",
                    )
                )

        # 9. join-side filters
        if join_path:
            if join_path == "customer_transactions":
                found.append(
                    IntentFilter(
                        field="status",
                        operator="eq",
                        values=("success",),
                        side="join",
                    )
                )
                if "App" in question:
                    found.append(
                        IntentFilter(field="channel", operator="eq", values=("app",), side="join")
                    )
                elif "网点" in question:
                    found.append(
                        IntentFilter(
                            field="channel", operator="eq", values=("branch",), side="join"
                        )
                    )
                if "买入" in question:
                    found.append(
                        IntentFilter(
                            field="transaction_type", operator="eq", values=("buy",), side="join"
                        )
                    )
                elif "卖出" in question:
                    found.append(
                        IntentFilter(
                            field="transaction_type", operator="eq", values=("sell",), side="join"
                        )
                    )
            elif join_path == "customer_cash_flows":
                found.append(
                    IntentFilter(
                        field="status",
                        operator="eq",
                        values=("success",),
                        side="join",
                    )
                )
                if "流入" in question and "净流入" not in question:
                    found.append(
                        IntentFilter(field="flow_type", operator="eq", values=("in",), side="join")
                    )
                elif "流出" in question and "净流入" not in question:
                    found.append(
                        IntentFilter(field="flow_type", operator="eq", values=("out",), side="join")
                    )
                if "App" in question:
                    found.append(
                        IntentFilter(field="channel", operator="eq", values=("app",), side="join")
                    )
                elif "网点" in question:
                    found.append(
                        IntentFilter(
                            field="channel", operator="eq", values=("branch",), side="join"
                        )
                    )
            elif join_path == "customer_holdings":
                found.append(
                    IntentFilter(
                        field="holding_status",
                        operator="eq",
                        values=("active",),
                        side="join",
                    )
                )
            elif join_path == "customer_service_relations":
                found.append(
                    IntentFilter(
                        field="is_primary",
                        operator="eq",
                        values=(True,),
                        side="join",
                    )
                )

        return tuple(found)
