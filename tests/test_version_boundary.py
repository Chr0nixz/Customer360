from customer360.contracts.hidden import HIDDEN_TASK_VERSION
from customer360.contracts.pack import GENERATED_TASK_VERSION
from customer360.metadata.metrics import MetadataRepository
from customer360.tasks.generator import generate_task_pack
from customer360.tasks.hidden import generate_hidden_pack


def test_metadata_and_task_versions_bumped_and_locked():
    repo = MetadataRepository()
    # Verified bumped versions for expansion
    assert repo.metrics.metrics_version == "0.4"
    assert repo.join_paths.join_paths_version == "0.2"

    assert GENERATED_TASK_VERSION == "generated-0.2"
    assert HIDDEN_TASK_VERSION == "hidden-0.2"


def test_generated_and_hidden_packs_carry_bumped_versions():
    repo = MetadataRepository()
    public = generate_task_pack(repository=repo, seed=42, count=120)
    assert public.task_version == "generated-0.2"
    assert public.metrics_version == "0.4"
    assert public.join_paths_version == "0.2"

    hidden = generate_hidden_pack(public, repository=repo, seed=42, count=8)
    assert hidden.task_version == "hidden-0.2"
    assert hidden.metrics_version == "0.4"
    assert hidden.join_paths_version == "0.2"
