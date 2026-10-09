from collections import Counter

from customer360.contracts.family import HIDDEN_CASE_ID_MIN
from customer360.metadata.metrics import MetadataRepository
from customer360.tasks.catalog import load_human_cases
from customer360.tasks.generator import generate_task_pack
from customer360.tasks.hidden import generate_hidden_pack
from customer360.tasks.isolation import check_hidden_isolation
from customer360.tasks.pack_rewrites import check_generated_rewrite


def test_expansion_e4_hidden_pack_60_cases_and_stratification() -> None:
    repo = MetadataRepository()
    public_pack = generate_task_pack(seed=42, count=300, repository=repo)
    hidden_pack = generate_hidden_pack(public_pack, count=60, repository=repo)

    # 1. Case count and ID range
    assert hidden_pack.case_count == 60
    assert len(hidden_pack.cases) == 60
    assert hidden_pack.cases[0].case_id == f"C360_{HIDDEN_CASE_ID_MIN:04d}"

    # 2. Four-quadrant golden stratification
    actions = Counter(c.expected_action for c in hidden_pack.cases)
    assert 30 <= actions["answer"] <= 45
    assert 12 <= actions["clarification_needed"] <= 20  # ~20-30%
    assert 8 <= actions["refuse"] <= 15  # ~15-20%

    categories = Counter(c.category for c in hidden_pack.cases)
    assert 7 <= categories["null_handling"] <= 15  # ~15% edge/error
    assert categories["grouping"] >= 3
    assert categories["join"] >= 2

    # 3. High metric coverage in hidden set
    metrics = {c.metric for c in hidden_pack.cases if c.metric}
    assert len(metrics) >= 20

    # 4. Zero rewrite issues
    issues = []
    for case in hidden_pack.cases:
        for text in (case.question, *case.rewrites):
            found = check_generated_rewrite(case, text, repo)
            if found:
                issues.extend(found)
    assert len(issues) == 0, f"Found hidden rewrite issues: {issues[:5]}"

    # 5. Perfect isolation with public pack and human oracle pack
    human = load_human_cases(check_rewrites=False)
    iso = check_hidden_isolation(human, public_pack, hidden_pack)
    assert iso.passed is True
    assert len(iso.issues) == 0
