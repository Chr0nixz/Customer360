"""Canonical semantic-family fingerprints. No compiler, DuckDB or Agent."""

from hashlib import sha256

from customer360.contracts.coverage import HumanCaseBlueprint
from customer360.contracts.family import FamilyFingerprint
from customer360.contracts.semantic import (
    Filter,
    JoinSpec,
    LatestSnapshot,
    PointInTime,
    RollingWindow,
)


def infer_template_id(
    *,
    expected_action: str,
    join: JoinSpec | None,
    group_by: tuple[str, ...],
    time_window: RollingWindow | PointInTime | LatestSnapshot | None,
    filters: tuple[Filter, ...],
    missing_slots: tuple[str, ...],
) -> str:
    if expected_action == "refuse":
        return "t_refuse"
    if expected_action == "clarification_needed" or missing_slots:
        return "t_clarify_time"
    if join is not None:
        return "t_join"
    if group_by:
        return "t_group"
    if isinstance(time_window, LatestSnapshot):
        return "t_latest"
    if isinstance(time_window, PointInTime):
        return "t_pit"
    if isinstance(time_window, RollingWindow):
        return "t_rolling"
    if any(item.operator == "is_null" for item in filters):
        return "t_null"
    if filters:
        return "t_filter"
    return "t_plain"


def filter_signature(
    filters: tuple[Filter, ...],
    *,
    join: JoinSpec | None = None,
    accepted_reason_codes: tuple[str, ...] = (),
) -> str:
    items = list(filters)
    if join is not None:
        items.extend(join.filters)
        items.append(
            Filter(field="join_path", operator="eq", values=(join.path,)),
        )
    parts = []
    for item in sorted(
        items, key=lambda row: (row.field, row.operator, tuple(map(str, row.values)))
    ):
        values = ",".join(str(value) for value in item.values)
        parts.append(f"{item.field}:{item.operator}:{values}")
    if accepted_reason_codes:
        parts.append("reason:" + ",".join(accepted_reason_codes))
    return "|".join(parts) or "none"


def _time_fields(
    time_window: RollingWindow | PointInTime | LatestSnapshot | None,
    join: JoinSpec | None,
) -> tuple[str, int | None, str]:
    window = time_window
    if window is None and join is not None:
        window = join.time_window
    if isinstance(window, RollingWindow):
        return "rolling", window.days, window.anchor_date.isoformat()
    if isinstance(window, PointInTime):
        return "point_in_time", None, window.snapshot_date.isoformat()
    if isinstance(window, LatestSnapshot):
        return "latest_snapshot", None, window.anchor_date.isoformat()
    return "none", None, "-"


def fingerprint_for(
    *,
    expected_action: str,
    metric: str | None,
    filters: tuple[Filter, ...] = (),
    time_window: RollingWindow | PointInTime | LatestSnapshot | None = None,
    join: JoinSpec | None = None,
    group_by: tuple[str, ...] = (),
    missing_slots: tuple[str, ...] = (),
    accepted_reason_codes: tuple[str, ...] = (),
) -> FamilyFingerprint:
    template_id = infer_template_id(
        expected_action=expected_action,
        join=join,
        group_by=group_by,
        time_window=time_window,
        filters=filters,
        missing_slots=missing_slots,
    )
    time_kind, rolling_days, time_point = _time_fields(time_window, join)
    signature = filter_signature(filters, join=join, accepted_reason_codes=accepted_reason_codes)
    canonical = "|".join(
        (
            template_id,
            expected_action,
            metric or "-",
            join.path if join is not None else "-",
            time_kind,
            str(rolling_days) if rolling_days is not None else "-",
            time_point,
            signature,
            ",".join(group_by) or "-",
        )
    )
    family_id = "fam_" + sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return FamilyFingerprint(
        template_id=template_id,
        expected_action=expected_action,  # type: ignore[arg-type]
        metric=metric,
        join_path=join.path if join is not None else None,
        time_kind=time_kind,  # type: ignore[arg-type]
        rolling_days=rolling_days,
        time_point=time_point,
        filter_signature=signature,
        group_by=group_by,
        canonical=canonical,
        family_id=family_id,
    )


def fingerprint_human_case(case: HumanCaseBlueprint) -> FamilyFingerprint:
    return fingerprint_for(
        expected_action=case.expected_action,
        metric=case.metric,
        filters=case.filters,
        time_window=case.time_window,
        join=case.join,
        group_by=case.group_by,
        missing_slots=case.missing_slots,
        accepted_reason_codes=tuple(case.accepted_reason_codes),
    )
