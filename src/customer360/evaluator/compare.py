from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from customer360.contracts.public import QueryResult


@dataclass(frozen=True)
class ComparisonPolicy:
    ordered: bool = False
    distinct: bool = False
    absolute_tolerance: Decimal = Decimal("0")
    relative_tolerance: Decimal = Decimal("0")

    def __post_init__(self):
        for tolerance in (self.absolute_tolerance, self.relative_tolerance):
            if not tolerance.is_finite() or tolerance < 0:
                raise ValueError("tolerance must be finite and nonnegative")


def compare_results(
    actual: QueryResult, expected: QueryResult, policy: ComparisonPolicy | None = None
) -> bool:
    policy = policy or ComparisonPolicy()
    if actual.truncated or expected.truncated or actual.columns != expected.columns:
        return False

    def normalize(rows):
        normalized = [
            tuple(
                Decimal(value) if col.kind == "decimal" and value is not None else value
                for col, value in zip(actual.columns, row, strict=True)
            )
            for row in rows
        ]
        return list(dict.fromkeys(normalized)) if policy.distinct else normalized

    left, right = normalize(actual.rows), normalize(expected.rows)
    if len(left) != len(right):
        return False

    def equal(a, b):
        for col, x, y in zip(actual.columns, a, b, strict=True):
            if x is None or y is None:
                if x is not y:
                    return False
            elif col.kind == "decimal":
                if abs(x - y) > max(policy.absolute_tolerance, policy.relative_tolerance * abs(y)):
                    return False
            elif type(x) is not type(y) or x != y:
                return False
        return True

    if policy.ordered:
        return all(equal(a, b) for a, b in zip(left, right, strict=True))
    if policy.absolute_tolerance == 0 and policy.relative_tolerance == 0:
        return Counter(left) == Counter(right)

    # Bipartite matching preserves multiplicity; greedy matching can falsely fail.
    matches: dict[int, int] = {}

    def augment(i: int, seen: set[int]) -> bool:
        for j, row in enumerate(right):
            if j in seen or not equal(left[i], row):
                continue
            seen.add(j)
            if j not in matches or augment(matches[j], seen):
                matches[j] = i
                return True
        return False

    return all(augment(i, set()) for i in range(len(left)))
