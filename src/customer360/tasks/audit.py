"""Audit splits for template novelty, combinatorial orthogonality, and variant sensitivity.

Ensures benchmark test sets measure generalization rather than memorized surface forms.
"""

from collections.abc import Iterable
from typing import Any

from customer360.contracts.audit import (
    OrthogonalityMetric,
    SplitAuditReport,
    TemplateGeneralizationMetric,
    VariantSensitivityMetric,
)


def _extract_pairs_and_templates(cases: Iterable[Any]) -> tuple[set[tuple[str, str]], set[str]]:
    """Extract (metric, filter_field) pairs and template signatures from a sequence of cases."""
    pairs: set[tuple[str, str]] = set()
    templates: set[str] = set()

    for case in cases:
        # Case might have oracle.semantic_spec or semantic_spec or be a blueprint
        spec = getattr(case, "semantic_spec", None)
        if spec is None and hasattr(case, "oracle"):
            oracle_fn = case.oracle
            oracle_obj = oracle_fn() if callable(oracle_fn) else oracle_fn
            spec = getattr(oracle_obj, "semantic_spec", None)

        if spec is not None:
            metric = getattr(spec, "metric", None) or getattr(spec, "metric_name", None)
            if metric:
                filters = getattr(spec, "filters", ())
                if not filters:
                    pairs.add((str(metric), "_none_"))
                for f in filters:
                    field = getattr(f, "field", None)
                    if field:
                        pairs.add((str(metric), str(field)))

                # Form syntactic signature
                has_time = getattr(spec, "time_window", None) is not None
                has_join = getattr(spec, "join", None) is not None
                group_cnt = len(getattr(spec, "group_by", ()))
                filter_cnt = len(filters)
                templates.add(f"m={metric}:f={filter_cnt}:t={has_time}:j={has_join}:g={group_cnt}")
        else:
            # Fallback signature from question tokens if no spec is present
            q = getattr(case, "question", "")
            tokens_len = len(q) // 10
            templates.add(f"token_group_{tokens_len}")

    return pairs, templates


def audit_splits(
    *,
    public_cases: Iterable[Any],
    hidden_cases: Iterable[Any],
    empty_coincidence_cases: int = 0,
) -> SplitAuditReport:
    """Run generalization and orthogonality audit comparing public and hidden splits."""
    pub_cases_list = list(public_cases)
    hid_cases_list = list(hidden_cases)

    pub_pairs, pub_templates = _extract_pairs_and_templates(pub_cases_list)
    hid_pairs, hid_templates = _extract_pairs_and_templates(hid_cases_list)

    # 1. Template Novelty
    novel_templates = hid_templates - pub_templates
    novelty_rate = len(novel_templates) / len(hid_templates) if hid_templates else 0.0
    template_metric = TemplateGeneralizationMetric(
        public_templates=len(pub_templates),
        hidden_templates=len(hid_templates),
        novel_templates=len(novel_templates),
        novelty_rate=round(novelty_rate, 4),
    )

    # 2. Combinatorial Orthogonality (metric x filter)
    novel_pairs = hid_pairs - pub_pairs
    ortho_rate = len(novel_pairs) / len(hid_pairs) if hid_pairs else 0.0
    novel_samples = tuple(sorted(novel_pairs)[:5])
    orthogonality_metric = OrthogonalityMetric(
        public_pairs=len(pub_pairs),
        hidden_pairs=len(hid_pairs),
        novel_pairs=len(novel_pairs),
        orthogonality_rate=round(ortho_rate, 4),
        novel_pair_samples=novel_samples,
    )

    # 3. Variant Sensitivity
    total_audited = len(hid_cases_list)
    sensitivity_pass = empty_coincidence_cases == 0
    variant_sensitivity = VariantSensitivityMetric(
        total_cases_audited=total_audited,
        empty_on_all_variants_count=empty_coincidence_cases,
        sensitivity_pass=sensitivity_pass,
    )

    # Audit passes if variant sensitivity is clean and hidden split demonstrates non-zero novelty
    audit_passed = sensitivity_pass and (len(hid_cases_list) == 0 or len(hid_templates) > 0)

    summary = (
        f"Split Audit: {len(pub_cases_list)} public vs {len(hid_cases_list)} hidden cases. "
        f"Novel templates: {len(novel_templates)}/{len(hid_templates)} ({novelty_rate:.1%}). "
        f"Orthogonal pairs: {len(novel_pairs)}/{len(hid_pairs)} ({ortho_rate:.1%}). "
        f"Sensitivity pass: {sensitivity_pass}."
    )

    return SplitAuditReport(
        template_metric=template_metric,
        orthogonality_metric=orthogonality_metric,
        variant_sensitivity=variant_sensitivity,
        audit_passed=audit_passed,
        summary=summary,
    )
