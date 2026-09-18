import pytest

from customer360.application import fixture_policy
from customer360.contracts.generation import GenerationConfig
from customer360.metadata.metrics import MetadataRepository
from customer360.synth.fixture import build_public_fixture
from customer360.synth.generator import generate_dataset
from customer360.synth.variants import generate_named_variant


@pytest.fixture(scope="session")
def repository():
    return MetadataRepository()


@pytest.fixture(scope="session")
def policy():
    return fixture_policy()


@pytest.fixture(scope="session")
def database(tmp_path_factory):
    path = tmp_path_factory.mktemp("public-fixture") / "fixture.duckdb"
    build_public_fixture(path)
    return path


@pytest.fixture(scope="session")
def baseline(tmp_path_factory):
    output = tmp_path_factory.mktemp("tiny-baseline") / "data"
    generate_dataset(GenerationConfig(seed=42), output)
    return output


@pytest.fixture(scope="session")
def variant(tmp_path_factory):
    output = tmp_path_factory.mktemp("tiny-variant") / "data"
    generate_dataset(GenerationConfig(seed=43), output)
    return output


@pytest.fixture(scope="session")
def duplicate_variant(tmp_path_factory):
    output = tmp_path_factory.mktemp("tiny-dup") / "data"
    generate_named_variant("tiny_duplicate_fanout", output)
    return output


@pytest.fixture(scope="session")
def null_variant(tmp_path_factory):
    output = tmp_path_factory.mktemp("tiny-null") / "data"
    generate_named_variant("tiny_null_empty_groups", output)
    return output


@pytest.fixture(scope="session")
def date_variant(tmp_path_factory):
    output = tmp_path_factory.mktemp("tiny-date") / "data"
    generate_named_variant("tiny_date_boundary", output)
    return output
