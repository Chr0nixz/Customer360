"""Split isolation for human and generated packs. No Gold, DuckDB or Agent."""

from customer360.contracts.coverage import HumanCaseCatalog
from customer360.contracts.family import (
    ALLOWED_GENERATED_SPLITS,
    ALLOWED_HIDDEN_SPLITS,
    ERROR_CLASSES_REQUIRED,
    FORBIDDEN_SPLITS,
    HIDDEN_CASE_ID_MIN,
    PUBLIC_GENERATED_ID_MAX,
    PUBLIC_GENERATED_ID_MIN,
    RESERVED_HUMAN_CASE_IDS,
    IsolationIssue,
    IsolationReport,
)
from customer360.contracts.hidden import HiddenTaskPack
from customer360.contracts.pack import GeneratedTaskPack
from customer360.tasks.family import fingerprint_human_case


def _issue(
    code: str, detail: str, case_id: str | None = None, family_id: str | None = None
) -> IsolationIssue:
    return IsolationIssue(code=code, detail=detail, case_id=case_id, family_id=family_id)


def check_human_pack_frozen(human: HumanCaseCatalog) -> tuple[IsolationIssue, ...]:
    issues: list[IsolationIssue] = []
    ids = tuple(item.case_id for item in human.cases)
    if ids != RESERVED_HUMAN_CASE_IDS:
        issues.append(
            _issue(
                "human_ids_changed",
                "human pack must remain C360_0001 through C360_0020 in order",
            )
        )
    for case in human.cases:
        if case.split != "dev":
            issues.append(
                _issue(
                    "human_split_relabel",
                    f"{case.case_id} split is {case.split}; hidden/private relabel is forbidden",
                    case_id=case.case_id,
                )
            )
        if case.split in FORBIDDEN_SPLITS:
            issues.append(
                _issue(
                    "hidden_relabel",
                    f"{case.case_id} uses a hidden split",
                    case_id=case.case_id,
                )
            )
        if case.task_version != "human-0.1":
            issues.append(
                _issue(
                    "human_version_changed",
                    f"{case.case_id} task_version is {case.task_version}",
                    case_id=case.case_id,
                )
            )
    return tuple(issues)


def check_generated_isolation(human: HumanCaseCatalog, pack: GeneratedTaskPack) -> IsolationReport:
    issues = list(check_human_pack_frozen(human))
    human_families = {fingerprint_human_case(case).family_id: case.case_id for case in human.cases}
    family_split: dict[str, str] = {}
    error_classes: set[str] = set()
    for case in pack.cases:
        if case.case_id in RESERVED_HUMAN_CASE_IDS:
            issues.append(
                _issue(
                    "reserved_id",
                    "generated pack reused a human case_id",
                    case_id=case.case_id,
                )
            )
        if case.split not in ALLOWED_GENERATED_SPLITS:
            issues.append(
                _issue(
                    "hidden_split",
                    f"generated {case.case_id} split {case.split} is not train/dev",
                    case_id=case.case_id,
                )
            )
        try:
            case_number = int(case.case_id[5:])
        except (TypeError, ValueError):
            case_number = None
        if case_number is None or not (
            PUBLIC_GENERATED_ID_MIN <= case_number <= PUBLIC_GENERATED_ID_MAX
        ):
            issues.append(
                _issue(
                    "generated_id_range",
                    "generated case_id must be within C360_1001 through C360_3999",
                    case_id=case.case_id,
                )
            )
        family_id = case.family.family_id
        if family_id in human_families:
            issues.append(
                _issue(
                    "cross_pack_family",
                    f"family also used by {human_families[family_id]}",
                    case_id=case.case_id,
                    family_id=family_id,
                )
            )
        previous = family_split.get(family_id)
        if previous is None:
            family_split[family_id] = case.split
        elif previous != case.split:
            issues.append(
                _issue(
                    "cross_split_family",
                    f"family appears in both {previous} and {case.split}",
                    case_id=case.case_id,
                    family_id=family_id,
                )
            )
        error_classes.add(case.intended_failure_class)
    missing_errors = ERROR_CLASSES_REQUIRED - error_classes
    if missing_errors:
        issues.append(
            _issue(
                "missing_error_class",
                "generated pack missing error classes: " + ",".join(sorted(missing_errors)),
            )
        )
    return IsolationReport(
        passed=not issues,
        human_pack_untouched=all(item.code != "human_split_relabel" for item in issues)
        and all(item.code != "human_ids_changed" for item in issues),
        generated_case_count=len(pack.cases),
        family_count=len({item.family.family_id for item in pack.cases}),
        error_classes=tuple(sorted(error_classes)),
        issues=tuple(issues),
    )


def check_hidden_isolation(
    human: HumanCaseCatalog, public: GeneratedTaskPack, hidden: HiddenTaskPack
) -> IsolationReport:
    report = check_generated_isolation(human, public)
    issues = list(report.issues)
    if hidden.public_pack_id != public.pack_id:
        issues.append(
            _issue(
                "public_pack_mismatch",
                "hidden pack must identify the exact public generated pack",
            )
        )
    public_families = {item.family.family_id: item.case_id for item in public.cases}
    human_families = {fingerprint_human_case(case).family_id: case.case_id for case in human.cases}
    hidden_families: dict[str, str] = {}
    error_classes: set[str] = set()
    for case in hidden.cases:
        if case.case_id in RESERVED_HUMAN_CASE_IDS:
            issues.append(
                _issue(
                    "reserved_id",
                    "hidden pack reused a human case_id",
                    case_id=case.case_id,
                )
            )
        if int(case.case_id[5:]) < HIDDEN_CASE_ID_MIN:
            issues.append(
                _issue(
                    "hidden_id_range",
                    "hidden case_id must be C360_4001 or higher",
                    case_id=case.case_id,
                )
            )
        if case.split not in ALLOWED_HIDDEN_SPLITS:
            issues.append(
                _issue(
                    "hidden_split",
                    f"hidden {case.case_id} split {case.split} is not private",
                    case_id=case.case_id,
                )
            )
        family_id = case.family.family_id
        if family_id in human_families:
            issues.append(
                _issue(
                    "cross_pack_family",
                    f"hidden family also used by {human_families[family_id]}",
                    case_id=case.case_id,
                    family_id=family_id,
                )
            )
        if family_id in public_families:
            issues.append(
                _issue(
                    "cross_pack_family",
                    f"hidden family also used by public {public_families[family_id]}",
                    case_id=case.case_id,
                    family_id=family_id,
                )
            )
        previous = hidden_families.get(family_id)
        if previous is None:
            hidden_families[family_id] = case.case_id
        elif previous != case.case_id:
            issues.append(
                _issue(
                    "duplicate_hidden_family",
                    "hidden pack reused a family_id",
                    case_id=case.case_id,
                    family_id=family_id,
                )
            )
        error_classes.add(case.intended_failure_class)
    missing_errors = ERROR_CLASSES_REQUIRED - error_classes
    if missing_errors:
        issues.append(
            _issue(
                "missing_error_class",
                "hidden pack missing error classes: " + ",".join(sorted(missing_errors)),
            )
        )
    return IsolationReport(
        passed=not issues,
        human_pack_untouched=report.human_pack_untouched,
        generated_case_count=len(public.cases),
        hidden_case_count=len(hidden.cases),
        family_count=len(public_families) + len(hidden_families),
        error_classes=tuple(sorted(set(report.error_classes) | error_classes)),
        issues=tuple(issues),
    )
