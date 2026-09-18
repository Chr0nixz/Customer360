"""Trusted-side Gold construction for the fixed human-case catalog."""

from pathlib import Path

from customer360.artifacts import digest, write_json_new
from customer360.contracts.generation import DatasetManifest
from customer360.evaluator.compare import compare_results
from customer360.metadata.metrics import MetadataRepository
from customer360.tasks.compiler import compile_semantic
from customer360.tasks.coverage import load_human_cases
from customer360.tasks.independent import compute_independent
from customer360.tasks.slices import load_table_slices
from customer360.tasks.trusted_data import load_verified_dataset, normalize_sql_result


def build_gold_package(dataset_dir: Path, output_dir: Path, oracles: Path | None = None) -> dict:
    database, manifest = load_verified_dataset(dataset_dir)
    if not isinstance(manifest, DatasetManifest) or manifest.artifact_kind != "tiny_dataset":
        raise ValueError("gold build requires a Tiny dataset, not a public fixture")
    catalog = load_human_cases(oracles=oracles)
    repository = MetadataRepository()
    slices = load_table_slices(database, repository.catalog)
    records = []
    for case in catalog.cases:
        record = {
            "case_id": case.case_id,
            "task_version": case.task_version,
            "split": case.split,
            "question": case.question,
            "rewrites": list(case.rewrites),
            "expected_action": case.expected_action,
            "material_status": case.material_status,
            "intended_failure_class": case.intended_failure_class,
            "required_probes": list(case.required_probes),
        }
        if case.material_status == "compilable_answer":
            spec = case.semantic_spec()
            compiled = compile_semantic(spec, repository)
            result = normalize_sql_result(database, compiled)
            independent = compute_independent(spec, repository, slices)
            if not compare_results(independent, result):
                raise ValueError(f"independent oracle mismatch for {case.case_id}")
            record.update(
                {
                    "semantic_spec": spec.model_dump(mode="json"),
                    "sql": compiled.sql,
                    "columns": [item.model_dump(mode="json") for item in compiled.columns],
                    "result": result.model_dump(mode="json"),
                    "independent_match": True,
                }
            )
        elif case.material_status == "unsupported_capability":
            record["unsupported_reason"] = case.unsupported_reason
        elif case.expected_action == "clarification_needed":
            record.update(
                {
                    "missing_slots": list(case.missing_slots),
                    "slot_replies": [item.model_dump(mode="json") for item in case.slot_replies],
                    "completed_spec": case.semantic_spec().model_dump(mode="json"),
                }
            )
        else:
            record["accepted_reason_codes"] = list(case.accepted_reason_codes)
        records.append(record)
    payload = {
        "artifact_kind": "private_human_case_gold",
        "gold_version": "0.1",
        "task_version": "human-0.1",
        "protocol_version": "0.1",
        "metadata_version": repository.metrics.metrics_version,
        "metrics_hash": digest(repository.metrics.model_dump(mode="json")),
        "m2_complete": False,
        "catalog_version": catalog.catalog_version,
        "dataset_manifest_hash": digest(manifest.model_dump(mode="json")),
        "case_count": len(records),
        "compilable_answers": sum(
            item.material_status == "compilable_answer" for item in catalog.cases
        ),
        "unsupported_capabilities": sum(
            item.material_status == "unsupported_capability" for item in catalog.cases
        ),
        "non_answer_oracles": sum(item.expected_action != "answer" for item in catalog.cases),
        "cases": records,
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    write_json_new(output_dir / "gold.json", payload)
    with (output_dir / "README.txt").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(
            "Private trusted-side Gold artifact. Do not provide gold.json to an Agent "
            "or publish it.\n"
        )
    return payload
