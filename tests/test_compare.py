from decimal import Decimal

import pytest

from customer360.contracts.public import Column, QueryResult
from customer360.evaluator.compare import ComparisonPolicy, compare_results


def result(values, kind="integer", truncated=False):
    return QueryResult(
        columns=(Column(name="value", kind=kind),),
        rows=tuple((value,) for value in values),
        truncated=truncated,
    )


def test_multiset_preserves_duplicate_rows():
    assert compare_results(result([1, 2, 1]), result([1, 1, 2]))
    assert not compare_results(result([1, 1, 2]), result([1, 2, 2]))
    assert not compare_results(result([1, 1]), result([1]))


def test_explicit_set_semantics():
    assert compare_results(result([1, 1]), result([1]), ComparisonPolicy(distinct=True))


def test_order_is_explicit():
    assert not compare_results(result([2, 1]), result([1, 2]), ComparisonPolicy(ordered=True))


def test_null_zero_and_empty_are_distinct():
    assert not compare_results(result([None]), result([0]))
    assert not compare_results(result([None], "string"), result([""], "string"))


def test_decimal_precision_and_tolerance():
    assert compare_results(result(["1.00"], "decimal"), result(["1"], "decimal"))
    assert compare_results(
        result(["1.01"], "decimal"),
        result(["1.00"], "decimal"),
        ComparisonPolicy(absolute_tolerance=Decimal("0.01")),
    )
    assert not compare_results(
        result([1]), result([2]), ComparisonPolicy(absolute_tolerance=Decimal("10"))
    )


def test_tolerant_matching_is_not_greedy():
    assert compare_results(
        result(["1", "0"], "decimal"),
        result(["0", "2"], "decimal"),
        ComparisonPolicy(absolute_tolerance=Decimal("1")),
    )


def test_empty_and_truncated_results():
    assert compare_results(result([]), result([]))
    assert not compare_results(result([1], truncated=True), result([1]))


@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity"])
def test_invalid_tolerance(value):
    with pytest.raises(ValueError):
        ComparisonPolicy(absolute_tolerance=Decimal(value))
