from customer360.contracts.semantic import Filter, JoinSpec, SemanticSpec
from customer360.metadata.metrics import EXECUTABLE_JOIN_PATHS, MetadataRepository


def test_expansion_e1_supported_join_paths_contract() -> None:
    expected_paths = {
        "customer_transactions",
        "customer_cash_flows",
        "customer_holdings",
        "customer_asset_snapshots",
        "customer_service_relations",
    }
    assert EXECUTABLE_JOIN_PATHS == expected_paths

    for path in expected_paths:
        spec = JoinSpec(
            path=path,  # type: ignore[arg-type]
            filters=(Filter(field="status", operator="eq", values=("active",)),),
        )
        assert spec.path == path
        semantic = SemanticSpec(
            metric="distinct_customer_count",
            join=spec,
        )
        assert semantic.join.path == path


def test_expansion_e1_metadata_repository_reports_five_executable_paths() -> None:
    repo = MetadataRepository()
    report = repo.consistency_report()
    assert report["executable_join_paths"] == 5

    executable_in_catalog = [
        p.path_name for p in repo.get_join_paths("") if p.compile_status == "executable"
    ]
    assert set(executable_in_catalog) == EXECUTABLE_JOIN_PATHS
