from collections import Counter

from customer360.metadata.metrics import MetadataRepository
from customer360.tasks.catalog import load_human_cases
from customer360.tasks.generator import generate_task_pack
from customer360.tasks.isolation import check_generated_isolation
from customer360.tasks.pack_rewrites import check_generated_rewrite


def test_expansion_e3_rebalanced_pack_quotas_and_isolation() -> None:
    repo = MetadataRepository()
    pack = generate_task_pack(seed=42, count=300, repository=repo)

    assert pack.case_count == 300
    assert pack.m3_complete is True
    assert pack.m6_structure is True

    # 1. Split counts: 180 train / 120 dev
    splits = Counter(c.split for c in pack.cases)
    assert splits["train"] == 180
    assert splits["dev"] == 120

    # 2. Expected actions balance
    actions = Counter(c.expected_action for c in pack.cases)
    assert 240 <= actions["answer"] <= 275
    assert 20 <= actions["clarification_needed"] <= 30
    assert 10 <= actions["refuse"] <= 20

    # 3. Categories balance
    categories = Counter(c.category for c in pack.cases)
    assert 36 <= categories["join"] <= 48
    assert 30 <= categories["grouping"] <= 45
    assert 15 <= categories["null_handling"] <= 25
    assert 80 <= categories["customer_filter"] <= 100  # Skew fixed from 190

    # 4. All 5 join paths are covered
    joins = Counter(c.join.path for c in pack.cases if c.join)
    expected_paths = {
        "customer_transactions",
        "customer_cash_flows",
        "customer_holdings",
        "customer_asset_snapshots",
        "customer_service_relations",
    }
    assert set(joins.keys()) == expected_paths
    for path, cnt in joins.items():
        assert cnt >= 4, f"Join path {path} has too few cases: {cnt}"

    # 5. Group by cases presence
    grouped = [c for c in pack.cases if c.group_by]
    assert 30 <= len(grouped) <= 45

    # 6. All 30 metrics covered
    all_metrics = {m.metric_name for m in repo.metrics.metrics}
    used_metrics = {c.metric for c in pack.cases if c.metric}
    assert all_metrics == used_metrics

    # 7. Semantic rewrite checks zero issues
    issues = []
    for case in pack.cases:
        for text in (case.question, *case.rewrites):
            found = check_generated_rewrite(case, text, repo)
            if found:
                issues.extend(found)
    assert len(issues) == 0, f"Found rewrite issues: {issues[:5]}"

    # 8. Human isolation
    human = load_human_cases(check_rewrites=False)
    iso = check_generated_isolation(human, pack)
    assert iso.passed is True
    assert len(iso.issues) == 0
