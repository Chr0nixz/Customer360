"""Stable identifier formatting. Tiny keeps C001 / T0001 widths."""

PREFIX_MIN_WIDTH = {"C": 3, "M": 3, "P": 3, "B": 3, "T": 4, "F": 4}


def numbered_id(prefix: str, index: int, total: int) -> str:
    width = max(PREFIX_MIN_WIDTH[prefix], len(str(total)))
    return f"{prefix}{index:0{width}d}"
