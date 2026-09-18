import hashlib
import json
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from pathlib import Path


def json_text(value: object) -> str:
    def encode(item):
        if isinstance(item, Decimal):
            return format(item, "f")
        if isinstance(item, date):
            return item.isoformat()
        raise TypeError(f"unsupported canonical value: {type(item).__name__}")

    return json.dumps(
        value, default=encode, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def digest(value: object) -> str:
    return hashlib.sha256(json_text(value).encode("utf-8")).hexdigest()


def write_json_new(path: Path, value: object) -> None:
    """Never silently overwrite a prior benchmark artifact."""
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json_text(value) + "\n")


def write_jsonl_new(path: Path, records: Iterable[object]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json_text(record) + "\n")
