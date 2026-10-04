from customer360.contracts.semantic import Filter, RollingWindow, SemanticSpec
from customer360.tasks.audit import _extract_pairs_and_templates, audit_splits


class DummyCase:
    def __init__(self, spec):
        self.semantic_spec = spec


def test_extract_pairs_and_templates():
    spec1 = SemanticSpec(
        metric="active_customer_count",
        filters=(Filter(field="customer_level", operator="eq", values=("VIP",)),),
        time_window=RollingWindow(days=90, anchor_date="2025-06-30"),
    )
    spec2 = SemanticSpec(
        metric="active_customer_count",
        filters=(Filter(field="region", operator="eq", values=("华东",)),),
    )

    cases = [DummyCase(spec1), DummyCase(spec2)]
    pairs, templates = _extract_pairs_and_templates(cases)

    assert ("active_customer_count", "customer_level") in pairs
    assert ("active_customer_count", "region") in pairs
    assert len(templates) == 2


def test_audit_splits_orthogonality():
    pub_spec = SemanticSpec(
        metric="active_customer_count",
        filters=(Filter(field="customer_level", operator="eq", values=("VIP",)),),
    )
    hid_spec_1 = SemanticSpec(
        metric="active_customer_count",
        filters=(Filter(field="customer_level", operator="eq", values=("VIP",)),),
    )
    hid_spec_2 = SemanticSpec(
        metric="active_customer_count",
        filters=(Filter(field="region", operator="eq", values=("华南",)),),
    )

    public_cases = [DummyCase(pub_spec)]
    hidden_cases = [DummyCase(hid_spec_1), DummyCase(hid_spec_2)]

    report = audit_splits(
        public_cases=public_cases,
        hidden_cases=hidden_cases,
        empty_coincidence_cases=0,
    )

    # 1 of 2 pairs in hidden is novel: (active_customer_count, region)
    assert report.orthogonality_metric.public_pairs == 1
    assert report.orthogonality_metric.hidden_pairs == 2
    assert report.orthogonality_metric.novel_pairs == 1
    assert report.orthogonality_metric.orthogonality_rate == 0.5
    assert report.audit_passed is True
