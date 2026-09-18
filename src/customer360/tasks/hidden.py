"""Independent hidden pack and isolated Tiny profile. Trusted-side only."""

from __future__ import annotations

from pathlib import Path
from random import Random

import yaml

from customer360.artifacts import write_json_new
from customer360.contracts.family import (
    DEFAULT_HIDDEN_DATA_SEED,
    ERROR_CLASSES_REQUIRED,
    FORBIDDEN_HIDDEN_DATA_SEEDS,
    HIDDEN_CASE_ID_MIN,
    HIDDEN_DEFAULT_COUNT,
)
from customer360.contracts.hidden import (
    HiddenCaseBlueprint,
    HiddenDataProfile,
    HiddenTaskPack,
    PublicHiddenCase,
    PublicHiddenCatalog,
    TrustedHiddenOracle,
)
from customer360.contracts.pack import GeneratedTaskPack
from customer360.metadata.metrics import MetadataRepository
from customer360.synth.generator import generate_dataset, load_generation_config
from customer360.tasks.catalog import load_human_cases
from customer360.tasks.family import fingerprint_human_case
from customer360.tasks.generator import (
    REQUIRED_COUNT,
    Draft,
    _fingerprint,
    _render,
    unique_pool_drafts,
)
from customer360.tasks.isolation import check_hidden_isolation
from customer360.tasks.trusted_data import load_verified_dataset

HIDDEN_PACK_JSON = "pack.json"
HIDDEN_PROFILE_NAME = "hidden_profile.json"


def _hidden_required(candidates: list[tuple[str, Draft]]) -> list[Draft]:
    chosen: list[Draft] = []
    seen: set[str] = set()
    for _family_id, draft in candidates:
        if draft.intended_failure_class in ERROR_CLASSES_REQUIRED - seen:
            chosen.append(draft)
            seen.add(draft.intended_failure_class)
        if seen == ERROR_CLASSES_REQUIRED:
            break
    missing = ERROR_CLASSES_REQUIRED - seen
    if missing:
        raise ValueError("not enough isolated families for hidden error classes")
    return chosen


def generate_hidden_pack(
    public: GeneratedTaskPack,
    *,
    seed: int = 42,
    count: int = HIDDEN_DEFAULT_COUNT,
    repository: MetadataRepository | None = None,
    oracles: Path | None = None,
) -> HiddenTaskPack:
    if count < REQUIRED_COUNT:
        raise ValueError(f"hidden pack needs at least {REQUIRED_COUNT} cases")
    repository = repository or MetadataRepository()
    if (
        public.metrics_version != repository.metrics.metrics_version
        or public.join_paths_version != repository.join_paths.join_paths_version
    ):
        raise ValueError("public generated pack metadata version does not match the repository")
    human = load_human_cases(oracles=oracles, check_rewrites=False)
    blocked = {fingerprint_human_case(case).family_id for case in human.cases}
    blocked.update(item.family.family_id for item in public.cases)
    unique = unique_pool_drafts(repository, blocked)
    ordered = sorted(unique.items())
    required = _hidden_required(ordered)
    required_ids = {_fingerprint(draft).family_id for draft in required}
    fill_pool = [item for item in ordered if item[0] not in required_ids]
    fill_needed = count - REQUIRED_COUNT
    if len(fill_pool) < fill_needed:
        raise ValueError("not enough independent families for the hidden pack")
    rng = Random(seed)
    fill_ids = [family_id for family_id, _draft in fill_pool]
    rng.shuffle(fill_ids)
    fill_map = dict(fill_pool)
    chosen = required + [fill_map[family_id] for family_id in fill_ids[:fill_needed]]
    cases: list[HiddenCaseBlueprint] = []
    questions: set[str] = set()
    public_questions = {item.question for item in public.cases}
    for index, draft in enumerate(chosen, start=HIDDEN_CASE_ID_MIN):
        family = _fingerprint(draft)
        question, rewrites = _render(draft, repository)
        if question in questions or question in public_questions:
            raise ValueError(f"duplicate hidden question: {question}")
        questions.add(question)
        cases.append(
            HiddenCaseBlueprint(
                case_id=f"C360_{index:04d}",
                family=family,
                expected_action=draft.expected_action,  # type: ignore[arg-type]
                category=draft.category,  # type: ignore[arg-type]
                material_status=draft.material_status,  # type: ignore[arg-type]
                intended_failure_class=draft.intended_failure_class,
                question=question,
                rewrites=rewrites,
                metric=draft.metric,
                filters=draft.filters,
                time_window=draft.time_window,
                join=draft.join,
                group_by=draft.group_by,
                missing_slots=draft.missing_slots,
                slot_replies=draft.slot_replies,
                accepted_reason_codes=draft.accepted_reason_codes,
            )
        )
    pack = HiddenTaskPack(
        seed=seed,
        case_count=len(cases),
        public_pack_id=public.pack_id,
        metrics_version=repository.metrics.metrics_version,
        join_paths_version=repository.join_paths.join_paths_version,
        cases=tuple(cases),
    )
    isolation = check_hidden_isolation(human, public, pack)
    if not isolation.passed:
        raise ValueError("hidden pack failed split isolation")
    return pack


def write_hidden_pack(
    output_dir: Path,
    pack: HiddenTaskPack,
    public: GeneratedTaskPack,
    *,
    oracles: Path | None = None,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    human = load_human_cases(oracles=oracles, check_rewrites=False)
    isolation = check_hidden_isolation(human, public, pack)
    agent_cases = PublicHiddenCatalog(
        cases=tuple(
            PublicHiddenCase(
                case_id=item.case_id,
                split=item.split,
                question=item.question,
                rewrites=item.rewrites,
            )
            for item in pack.cases
        )
    )
    trusted = tuple(
        TrustedHiddenOracle(
            case_id=item.case_id,
            split=item.split,
            family=item.family,
            expected_action=item.expected_action,
            category=item.category,
            material_status=item.material_status,
            intended_failure_class=item.intended_failure_class,
            metric=item.metric,
            filters=item.filters,
            time_window=item.time_window,
            join=item.join,
            group_by=item.group_by,
            missing_slots=item.missing_slots,
            slot_replies=item.slot_replies,
            accepted_reason_codes=item.accepted_reason_codes,
        )
        for item in pack.cases
    )
    (output_dir / "agent_cases.yaml").write_text(
        yaml.safe_dump(agent_cases.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (output_dir / "hidden_oracles.yaml").write_text(
        yaml.safe_dump(
            {
                "catalog_version": "0.5",
                "artifact_kind": "trusted_hidden_oracles",
                "pack_id": pack.pack_id,
                "cases": [item.model_dump(mode="json") for item in trusted],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    write_json_new(output_dir / HIDDEN_PACK_JSON, pack.model_dump(mode="json"))
    write_json_new(output_dir / "isolation.json", isolation.model_dump(mode="json"))
    return {
        "pack_id": pack.pack_id,
        "case_count": pack.case_count,
        "hidden": True,
        "scoring_applied": pack.scoring_applied,
        "isolation_passed": isolation.passed,
        "seed": pack.seed,
    }


def load_hidden_pack(pack_dir: Path) -> HiddenTaskPack:
    path = pack_dir / HIDDEN_PACK_JSON
    if not path.is_file():
        raise ValueError("hidden pack.json not found")
    pack = HiddenTaskPack.model_validate_json(path.read_text(encoding="utf-8"))
    if pack.pack_kind != "hidden_task_pack":
        raise ValueError("pack is not a hidden task pack")
    return pack


def generate_hidden_dataset(
    output_dir: Path,
    *,
    seed: int = DEFAULT_HIDDEN_DATA_SEED,
    config: Path | None = None,
) -> HiddenDataProfile:
    if seed in FORBIDDEN_HIDDEN_DATA_SEEDS:
        raise ValueError("hidden Tiny cannot reuse public seeds 42 or 43")
    config_path = config or Path("configs/data_generation.yaml")
    generation_config = load_generation_config(config_path, scale="tiny", seed=seed)
    manifest, quality = generate_dataset(generation_config, output_dir)
    if not quality["all_passed"]:
        raise ValueError("hidden Tiny quality assertions failed")
    profile = HiddenDataProfile(
        seed=seed,
        snapshot_version=manifest["snapshot_version"],
        generator_version=manifest["generator_version"],
    )
    write_json_new(output_dir / HIDDEN_PROFILE_NAME, profile.model_dump(mode="json"))
    return profile


def load_hidden_dataset(dataset_dir: Path):
    profile_path = dataset_dir / HIDDEN_PROFILE_NAME
    if not profile_path.is_file():
        raise ValueError("hidden dataset requires hidden_profile.json")
    profile = HiddenDataProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
    database, manifest = load_verified_dataset(dataset_dir)
    if manifest.seed != profile.seed:
        raise ValueError("hidden profile seed does not match dataset manifest")
    if manifest.artifact_kind != "tiny_dataset":
        raise ValueError("hidden dataset must use a generated Tiny manifest")
    if manifest.seed in FORBIDDEN_HIDDEN_DATA_SEEDS:
        raise ValueError("hidden Tiny cannot reuse public seeds 42 or 43")
    if manifest.scale != "tiny":
        raise ValueError("hidden evaluation currently requires Tiny")
    if manifest.snapshot_version != profile.snapshot_version:
        raise ValueError("hidden profile snapshot version does not match dataset manifest")
    if manifest.generator_version != profile.generator_version:
        raise ValueError("hidden profile generator version does not match dataset manifest")
    return database, manifest, profile
