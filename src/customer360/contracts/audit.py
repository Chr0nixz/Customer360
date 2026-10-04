"""Split generalization and orthogonality audit contracts.

Evaluates template novelty, (metric x filter) combinatorial orthogonality,
and variant sensitivity without leaking hidden gold values.
"""

from pydantic import Field

from customer360.contracts.base import Contract, Text


class TemplateGeneralizationMetric(Contract):
    """Novelty of syntactic question templates in hidden split."""

    public_templates: int = Field(ge=0)
    hidden_templates: int = Field(ge=0)
    novel_templates: int = Field(ge=0)
    novelty_rate: float = Field(ge=0.0, le=1.0)


class OrthogonalityMetric(Contract):
    """Combinatorial orthogonality between metrics and filter dimensions."""

    public_pairs: int = Field(ge=0)
    hidden_pairs: int = Field(ge=0)
    novel_pairs: int = Field(ge=0)
    orthogonality_rate: float = Field(ge=0.0, le=1.0)
    novel_pair_samples: tuple[tuple[Text, Text], ...] = Field(default_factory=tuple)


class VariantSensitivityMetric(Contract):
    """Variant distinction check: ensures no case passes merely by empty coincidences."""

    total_cases_audited: int = Field(ge=0)
    empty_on_all_variants_count: int = Field(ge=0)
    sensitivity_pass: bool


class SplitAuditReport(Contract):
    """Complete generalization audit for benchmark splits."""

    template_metric: TemplateGeneralizationMetric
    orthogonality_metric: OrthogonalityMetric
    variant_sensitivity: VariantSensitivityMetric
    audit_passed: bool
    summary: Text


class MetadataAuditIssue(Contract):
    """Specific referential or structural issue found during metadata audit."""

    code: Text
    target: Text
    message: Text


class MetadataAuditReport(Contract):
    """Complete static integrity audit for catalog, metrics, and join paths."""

    tables_count: int = Field(ge=0)
    metrics_count: int = Field(ge=0)
    join_paths_count: int = Field(ge=0)
    issues: tuple[MetadataAuditIssue, ...] = Field(default_factory=tuple)
    passed: bool
    summary: Text
