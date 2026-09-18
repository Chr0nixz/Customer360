"""Private matrix artifacts and public desensitized reports. No official scores."""

from pathlib import Path

from customer360.artifacts import write_json_new, write_jsonl_new
from customer360.contracts.matrix import (
    PUBLIC_MATRIX_FORBIDDEN,
    MatrixRunReport,
    PublicCaseSummary,
    PublicMatrixSummary,
    PublicSnapshotSummary,
)

LIMITATIONS = (
    "Public summary is desensitized; Gold SQL, specs and candidate SQL stay private",
    "Not an official weighted score or hidden-split result",
)


def public_summary(report: MatrixRunReport) -> PublicMatrixSummary:
    cases = []
    for item in report.cases:
        cases.append(
            PublicCaseSummary(
                case_id=item.case_id,
                split=item.split,
                snapshots=tuple(
                    PublicSnapshotSummary(
                        snapshot_id=snapshot.snapshot_id,
                        applicable=snapshot.applicable,
                        stage=snapshot.stage,
                        outcome=snapshot.outcome,
                        reason_code=snapshot.reason_code,
                        failure_class=snapshot.failure_class,
                    )
                    for snapshot in item.snapshots
                ),
            )
        )
    return PublicMatrixSummary(
        replay_mode=report.replay_mode,
        agent_id=report.agent_id,
        integrity_passed=report.integrity_passed,
        limitations=report.limitations + LIMITATIONS,
        cases=tuple(cases),
    )


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def render_markdown(summary: PublicMatrixSummary) -> str:
    lines = [
        "# Customer360 matrix evaluation",
        "",
        "Desensitized public summary. Not an official score.",
        "",
        f"- integrity_passed: `{summary.integrity_passed}`",
        f"- replay_mode: `{summary.replay_mode}`",
        f"- agent_id: `{summary.agent_id}`",
        f"- scoring_applied: `{summary.scoring_applied}`",
        f"- m4_scored: `{summary.m4_scored}`",
        f"- case_count: `{summary.case_count}`",
        "",
        "## Snapshots",
        "",
    ]
    lines.extend(f"- `{item}`" for item in summary.snapshot_ids)
    header = "| case | " + " | ".join(summary.snapshot_ids) + " |"
    divider = "| --- | " + " | ".join("---" for _ in summary.snapshot_ids) + " |"
    lines.extend(["", "## Cases", "", header, divider])
    for case in summary.cases:
        cells = []
        for snapshot in case.snapshots:
            label = snapshot.outcome
            if snapshot.reason_code and snapshot.outcome != "pass":
                label = f"{snapshot.outcome}/{snapshot.reason_code}"
            cells.append(label)
        lines.append("| " + case.case_id + " | " + " | ".join(cells) + " |")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in summary.limitations)
    lines.append("")
    return "\n".join(lines)


def render_html(summary: PublicMatrixSummary) -> str:
    rows = []
    header = "".join(f"<th>{_escape(item)}</th>" for item in ("case", *summary.snapshot_ids))
    for case in summary.cases:
        cells = [f"<td>{_escape(case.case_id)}</td>"]
        for snapshot in case.snapshots:
            label = snapshot.outcome
            if snapshot.reason_code and snapshot.outcome != "pass":
                label = f"{snapshot.outcome}/{snapshot.reason_code}"
            cells.append(f"<td>{_escape(label)}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    limits = "".join(f"<li>{_escape(item)}</li>" for item in summary.limitations)
    return (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        "<title>Customer360 matrix evaluation</title></head><body>"
        "<h1>Customer360 matrix evaluation</h1>"
        "<p>Desensitized public summary. Not an official score.</p>"
        f"<ul><li>integrity_passed: {_escape(str(summary.integrity_passed))}</li>"
        f"<li>replay_mode: {_escape(summary.replay_mode)}</li>"
        f"<li>agent_id: {_escape(summary.agent_id)}</li>"
        f"<li>scoring_applied: {summary.scoring_applied}</li>"
        f"<li>m4_scored: {summary.m4_scored}</li></ul>"
        f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        f"<h2>Limitations</h2><ul>{limits}</ul></body></html>\n"
    )


def write_matrix_run(output_dir: Path, report: MatrixRunReport) -> dict:
    output_dir.mkdir(parents=True, exist_ok=False)
    private_dir = output_dir / "private"
    public_dir = output_dir / "public"
    private_dir.mkdir()
    public_dir.mkdir()
    summary = public_summary(report)
    write_json_new(private_dir / "matrix.json", report.model_dump(mode="json"))
    write_jsonl_new(
        private_dir / "records.jsonl",
        (item.baseline_record.model_dump(mode="json") for item in report.cases),
    )
    write_json_new(public_dir / "summary.json", summary.model_dump(mode="json"))
    (public_dir / "report.md").write_text(render_markdown(summary), encoding="utf-8")
    (public_dir / "report.html").write_text(render_html(summary), encoding="utf-8")
    public_text = (public_dir / "summary.json").read_text(encoding="utf-8")
    public_text += (public_dir / "report.md").read_text(encoding="utf-8")
    public_text += (public_dir / "report.html").read_text(encoding="utf-8")
    for field in PUBLIC_MATRIX_FORBIDDEN:
        if f'"{field}"' in public_text:
            raise ValueError(f"public matrix artifacts leaked {field}")
    return {
        "integrity_passed": report.integrity_passed,
        "replay_mode": report.replay_mode,
        "scoring_applied": report.scoring_applied,
        "m4_scored": report.m4_scored,
        "case_count": report.case_count,
        "independent_oracle_matches": report.independent_oracle_matches,
        "agent_id": report.agent_id,
    }


def load_private_matrix(input_dir: Path) -> MatrixRunReport:
    path = input_dir / "private" / "matrix.json"
    if not path.is_file():
        path = input_dir / "matrix.json"
    if not path.is_file():
        raise ValueError("private matrix.json not found")
    return MatrixRunReport.model_validate_json(path.read_text(encoding="utf-8"))
