import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import sqlglot
from sqlglot import exp

from customer360.contracts.execution import AccessPolicy, SqlLimits
from customer360.errors import QueryRejected
from customer360.metadata.models import Catalog

_ALLOWED_PREDICATES = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)
_DENIED = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Command, exp.Copy)
_ALLOWED_NODES = {
    exp.Select,
    exp.From,
    exp.Table,
    exp.TableAlias,
    exp.Identifier,
    exp.Alias,
    exp.Count,
    exp.Sum,
    exp.Max,
    exp.Distinct,
    exp.Column,
    exp.Star,
    exp.Where,
    exp.And,
    exp.Or,
    exp.EQ,
    exp.NEQ,
    exp.GT,
    exp.GTE,
    exp.LT,
    exp.LTE,
    exp.In,
    exp.Is,
    exp.Null,
    exp.Literal,
    exp.Boolean,
    exp.Paren,
    exp.Not,
    exp.Join,
    exp.Group,
    exp.Subquery,
}
_ALLOWED_SELECT_KEYS = frozenset({"expressions", "from_", "where", "joins", "group"})


@dataclass(frozen=True)
class GuardedQuery:
    sql: str
    table: str
    output_names: tuple[str, ...]
    output_kinds: tuple[str, ...]
    referenced_columns: tuple[str, ...]
    tables: tuple[str, ...] = ()
    contributor_sql: str | None = None


def _fail(code: str, message: str) -> None:
    raise QueryRejected(code, message)


def _literal(node: exp.Expression) -> bool:
    return isinstance(node, (exp.Literal, exp.Boolean))


def _column(node: exp.Expression) -> str:
    if not isinstance(node, exp.Column) or node.table:
        _fail("UNSAFE_SQL", "only unqualified columns are supported")
    return node.name


def _join_column(node: exp.Expression, aliases: dict[str, str]) -> tuple[str, str]:
    if not isinstance(node, exp.Column) or not node.table or node.table not in aliases:
        _fail("UNSUPPORTED_QUERY", "join columns must use declared aliases")
    return aliases[node.table], node.name


def _join_condition(
    node: exp.Expression, aliases: dict[str, str], catalog: Catalog, grants
) -> set[str]:
    if isinstance(node, exp.And):
        return _join_condition(node.left, aliases, catalog, grants) | _join_condition(
            node.right, aliases, catalog, grants
        )
    if not isinstance(node, exp.EQ):
        _fail("UNSUPPORTED_QUERY", "join predicates must be equality")
    left, right = node.left, node.right
    if isinstance(left, exp.Column) and isinstance(right, exp.Column):
        ltable, lcol = _join_column(left, aliases)
        rtable, rcol = _join_column(right, aliases)
        if (
            {ltable, rtable} != {"dim_customer", "fact_transaction"}
            or lcol != "customer_id"
            or rcol != "customer_id"
        ):
            _fail("JOIN_ERROR", "only customer_id customer-to-transaction join is supported")
        return {f"{ltable}.{lcol}", f"{rtable}.{rcol}"}
    _fail("JOIN_ERROR", "join condition must compare the two customer_id columns")


def _predicate_column(node: exp.Expression) -> exp.Expression:
    if isinstance(node, _ALLOWED_PREDICATES):
        return node.left
    if isinstance(node, (exp.In, exp.Is)):
        return node.this
    _fail("UNSUPPORTED_QUERY", "predicate is not in the v0.1 safe subset")


def _predicate_literals_ok(node: exp.Expression) -> bool:
    if isinstance(node, _ALLOWED_PREDICATES):
        return _literal(node.right)
    if isinstance(node, exp.In):
        return bool(node.expressions) and all(_literal(value) for value in node.expressions)
    if isinstance(node, exp.Is):
        return isinstance(node.expression, exp.Null)
    return False


def _literal_matches_column(node: exp.Expression, column_kind: str) -> bool:
    """Return whether a parsed SQL literal can be compared to a catalog column.

    SQLGlot deliberately keeps literals fairly syntax-oriented.  The worker
    should not be the first place that discovers a boolean-vs-string or
    malformed-date comparison, so the guard performs this small type check
    before it accepts a predicate.  This is not a SQL type checker: it only
    covers the scalar kinds exposed by the v0.1 catalog.
    """

    if column_kind == "boolean":
        return isinstance(node, exp.Boolean)
    if not isinstance(node, exp.Literal):
        return False
    if column_kind == "string":
        return node.is_string
    if column_kind == "integer":
        if node.is_string:
            return False
        try:
            int(node.this)
        except (TypeError, ValueError):
            return False
        return True
    if column_kind == "decimal":
        if node.is_string:
            return False
        try:
            value = Decimal(str(node.this))
        except (InvalidOperation, TypeError, ValueError):
            return False
        return value.is_finite()
    if column_kind == "date":
        if not node.is_string:
            return False
        try:
            return date.fromisoformat(str(node.this)).isoformat() == str(node.this)
        except ValueError:
            return False
    return False


def _validate_condition(node: exp.Expression, catalog: Catalog, table_name: str) -> set[str]:
    if isinstance(node, exp.Paren):
        return _validate_condition(node.this, catalog, table_name)
    if isinstance(node, exp.Not) and isinstance(node.this, exp.Is):
        return _validate_condition(node.this, catalog, table_name)
    if isinstance(node, exp.And) or isinstance(node, exp.Or):
        return _validate_condition(node.left, catalog, table_name) | _validate_condition(
            node.right, catalog, table_name
        )
    if isinstance(node, _ALLOWED_PREDICATES + (exp.In, exp.Is)):
        column = _predicate_column(node)
        if not isinstance(column, exp.Column) or not _predicate_literals_ok(node):
            if isinstance(node, exp.In):
                _fail("UNSUPPORTED_QUERY", "IN requires a column and literals")
            if isinstance(node, exp.Is):
                _fail("UNSUPPORTED_QUERY", "only IS NULL is supported")
            _fail("UNSUPPORTED_QUERY", "predicates must compare a column with a literal")
        name = _column(column)
        if isinstance(node, exp.Is):
            return {name}
        try:
            kind = catalog.table(table_name).column(name).kind
        except KeyError:
            _fail("UNKNOWN_FIELD", "query references an unknown column")
        values = node.expressions if isinstance(node, exp.In) else (node.right,)
        if not all(_literal_matches_column(value, kind) for value in values):
            _fail("UNSUPPORTED_QUERY", "predicate literal does not match the column type")
        return {name}
    _fail("UNSUPPORTED_QUERY", "predicate is not in the v0.1 safe subset")


def _validate_join_filters(
    node: exp.Expression,
    aliases: dict[str, str],
    tables: tuple[str, ...],
    grants,
    catalog: Catalog,
) -> set[str]:
    if isinstance(node, exp.Paren):
        return _validate_join_filters(node.this, aliases, tables, grants, catalog)
    if isinstance(node, exp.Not) and isinstance(node.this, exp.Is):
        return _validate_join_filters(node.this, aliases, tables, grants, catalog)
    if isinstance(node, exp.And):
        return _validate_join_filters(
            node.left, aliases, tables, grants, catalog
        ) | _validate_join_filters(node.right, aliases, tables, grants, catalog)
    if not isinstance(node, _ALLOWED_PREDICATES + (exp.In, exp.Is)):
        _fail("UNSUPPORTED_QUERY", "join filters are outside the safe subset")
    column = _predicate_column(node)
    if not isinstance(column, exp.Column) or not _predicate_literals_ok(node):
        _fail("UNSUPPORTED_QUERY", "join filter must compare a column with a literal")
    table, name = _join_column(column, aliases)
    if table not in tables:
        _fail("UNKNOWN_FIELD", "unknown joined table")
    try:
        column_kind = catalog.table(table).column(name).kind
    except KeyError:
        _fail("UNKNOWN_FIELD", "query references an unknown joined column")
    values = node.expressions if isinstance(node, exp.In) else (node.right,)
    if not isinstance(node, exp.Is) and not all(
        _literal_matches_column(value, column_kind) for value in values
    ):
        _fail("UNSUPPORTED_QUERY", "join predicate literal does not match the column type")
    if name == "customer_id" and table != "dim_customer":
        _fail("JOIN_ERROR", "transaction customer_id cannot be a user filter")
    if name not in grants[table]:
        _fail("PERMISSION_DENIED", "joined column is not granted")
    return {f"{table}.{name}"}


def _validate_join_query(
    tree: exp.Select, catalog: Catalog, policy: AccessPolicy, limits: SqlLimits
) -> GuardedQuery:
    from_clause = tree.args.get("from_")
    joins = tree.args.get("joins") or []
    if not from_clause or len(joins) != 1 or not isinstance(from_clause.this, exp.Table):
        _fail("JOIN_ERROR", "exactly one supported join is required")
    right = joins[0].this
    if not isinstance(right, exp.Table):
        _fail("JOIN_ERROR", "joined source must be a table")
    join = joins[0]
    if (
        join.args.get("side")
        or join.args.get("method")
        or join.args.get("kind") not in (None, "", "INNER")
    ):
        _fail("UNSUPPORTED_QUERY", "only an inner join is supported")
    tables = (from_clause.this.name, right.name)
    if tables != ("dim_customer", "fact_transaction"):
        _fail("JOIN_ERROR", "join direction is not supported")
    aliases = {}
    for item, expected in ((from_clause.this, "c"), (right, "t")):
        alias = item.args.get("alias")
        if not alias or alias.name != expected:
            _fail("UNSUPPORTED_QUERY", "join aliases must be c and t")
        aliases[expected] = item.name
    grants = {grant.table: set(grant.columns) for grant in policy.grants}
    for table in tables:
        if table not in grants:
            _fail("PERMISSION_DENIED", "joined table is not granted")
    if tree.args.get("group"):
        _fail("UNSUPPORTED_QUERY", "joined queries cannot group")
    referenced = _join_condition(joins[0].args.get("on"), aliases, catalog, grants)
    projections = tree.expressions
    if len(projections) != 1 or not isinstance(projections[0], exp.Alias):
        _fail("UNSUPPORTED_QUERY", "one aliased aggregate is required")
    aggregate = projections[0].this
    if not isinstance(aggregate, exp.Count) or not isinstance(aggregate.this, exp.Distinct):
        _fail("JOIN_ERROR", "joined query must count distinct customers")
    values = aggregate.this.expressions
    if len(values) != 1 or _join_column(values[0], aliases) != ("dim_customer", "customer_id"):
        _fail("JOIN_ERROR", "joined query must count customer_id")
    alias = projections[0].alias
    if not re.fullmatch(r"[a-z][a-z0-9_]*", alias):
        _fail("UNSAFE_SQL", "unsafe output alias")
    where = tree.args.get("where")
    if where:
        referenced |= _validate_join_filters(where.this, aliases, tables, grants, catalog)
    return GuardedQuery(
        sql=tree.sql(dialect="duckdb"),
        table="dim_customer",
        output_names=(alias,),
        output_kinds=("integer",),
        referenced_columns=tuple(sorted(referenced)),
        tables=tables,
    )


def _aliased_column(node: exp.Expression) -> tuple[str, str]:
    if not isinstance(node, exp.Alias) or not re.fullmatch(r"[a-z][a-z0-9_]*", node.alias):
        _fail("UNSAFE_SQL", "unsafe output alias")
    column = node.this
    if not isinstance(column, exp.Column) or column.table:
        _fail("UNSUPPORTED_QUERY", "grouping keys must be unqualified columns")
    if column.name != node.alias:
        _fail("UNSUPPORTED_QUERY", "grouping alias must match the column")
    return column.name, node.alias


def _validate_grouped_query(
    tree: exp.Select, catalog: Catalog, policy: AccessPolicy, sql: str
) -> GuardedQuery:
    from_clause = tree.args.get("from_")
    table = from_clause.this if from_clause else None
    group = tree.args.get("group")
    if (
        not isinstance(table, exp.Table)
        or not isinstance(table.this, exp.Identifier)
        or any(value for key, value in table.args.items() if key != "this")
        or group is None
    ):
        _fail("UNSUPPORTED_QUERY", "grouped query requires one unaliased table")
    if table.name != "dim_customer":
        _fail("UNSUPPORTED_QUERY", "only region grouping on dim_customer is supported")
    group_exprs = list(group.expressions)
    if len(group_exprs) != 1 or not isinstance(group_exprs[0], exp.Column):
        _fail("UNSUPPORTED_QUERY", "exactly one grouping column is supported")
    group_name = _column(group_exprs[0])
    if group_name != "region":
        _fail("UNSUPPORTED_QUERY", "only region grouping on dim_customer is supported")
    grant = next((item for item in policy.grants if item.table == table.name), None)
    if grant is None:
        _fail("PERMISSION_DENIED", "table is not granted")
    granted = set(grant.columns)
    table_def = catalog.table(table.name)
    projections = tree.expressions
    if len(projections) != 2:
        _fail("UNSUPPORTED_QUERY", "grouped query needs the group key and one aggregate")
    key_name, key_alias = _aliased_column(projections[0])
    if key_name != group_name or key_alias != group_name:
        _fail("UNSUPPORTED_QUERY", "select list must start with the grouping column")
    aggregate_proj = projections[1]
    if not isinstance(aggregate_proj, exp.Alias):
        _fail("UNSUPPORTED_QUERY", "one aliased aggregate is required")
    alias = aggregate_proj.alias
    if not re.fullmatch(r"[a-z][a-z0-9_]*", alias):
        _fail("UNSAFE_SQL", "unsafe output alias")
    aggregate = aggregate_proj.this
    if not isinstance(aggregate, exp.Count) or not isinstance(aggregate.this, exp.Distinct):
        _fail("UNSUPPORTED_QUERY", "grouped query must count distinct customers")
    values = aggregate.this.expressions
    if len(values) != 1 or _column(values[0]) != "customer_id":
        _fail("UNSUPPORTED_QUERY", "grouped query must count customer_id")
    referenced = {group_name, "customer_id"}
    where = tree.args.get("where")
    if where:
        referenced |= _validate_condition(where.this, catalog, table.name)
    known = {column.column_name for column in table_def.columns}
    if not referenced <= known:
        _fail("UNKNOWN_FIELD", "query references an unknown column")
    if not referenced <= granted:
        _fail("PERMISSION_DENIED", "query references a denied column")
    return GuardedQuery(
        sql=sql,
        table=table.name,
        output_names=(key_alias, alias),
        output_kinds=("string", "integer"),
        referenced_columns=tuple(sorted(referenced)),
    )


def _latest_inner_select(node: exp.Expression) -> exp.Select | None:
    if isinstance(node, exp.Subquery) and isinstance(node.this, exp.Select):
        alias = node.args.get("alias")
        if alias is not None and alias.name == "latest":
            return node.this
    return None


def _is_latest_snapshot_query(tree: exp.Select) -> bool:
    from_clause = tree.args.get("from_")
    joins = tree.args.get("joins") or []
    if not from_clause or len(joins) != 1:
        return False
    source = from_clause.this
    return (
        isinstance(source, exp.Table)
        and source.name == "fact_asset_snapshot"
        and _latest_inner_select(joins[0].this) is not None
    )


def _validate_latest_snapshot(
    tree: exp.Select, catalog: Catalog, policy: AccessPolicy, sql: str
) -> GuardedQuery:
    from_clause = tree.args.get("from_")
    joins = tree.args.get("joins") or []
    source = from_clause.this if from_clause else None
    inner = _latest_inner_select(joins[0].this) if joins else None
    if not isinstance(source, exp.Table) or inner is None:
        _fail("UNSUPPORTED_QUERY", "latest-snapshot shape is invalid")
    if (
        joins[0].args.get("side")
        or joins[0].args.get("method")
        or joins[0].args.get("kind") not in (None, "", "INNER")
    ):
        _fail("UNSUPPORTED_QUERY", "only an inner join is supported")
    alias = source.args.get("alias")
    if not alias or alias.name != "s" or source.name != "fact_asset_snapshot":
        _fail("UNSUPPORTED_QUERY", "latest-snapshot alias must be s")
    if tree.args.get("group") or tree.args.get("where"):
        _fail("UNSUPPORTED_QUERY", "latest-snapshot outer query cannot filter or group")
    inner_from = inner.args.get("from_")
    inner_table = inner_from.this if inner_from else None
    if (
        not isinstance(inner_table, exp.Table)
        or inner_table.name != "fact_asset_snapshot"
        or inner_table.args.get("alias")
        or inner.args.get("joins")
        or inner.args.get("group") is None
    ):
        _fail("UNSUPPORTED_QUERY", "latest-snapshot inner query is invalid")
    group_exprs = list(inner.args["group"].expressions)
    if len(group_exprs) != 1 or not isinstance(group_exprs[0], exp.Column):
        _fail("UNSUPPORTED_QUERY", "latest-snapshot must group by customer_id")
    if _column(group_exprs[0]) != "customer_id":
        _fail("UNSUPPORTED_QUERY", "latest-snapshot must group by customer_id")
    inner_projections = inner.expressions
    if len(inner_projections) != 2:
        _fail("UNSUPPORTED_QUERY", "latest-snapshot inner select is invalid")
    customer_proj = inner_projections[0]
    if not isinstance(customer_proj, exp.Column) or customer_proj.table:
        if not (
            isinstance(customer_proj, exp.Alias)
            and isinstance(customer_proj.this, exp.Column)
            and customer_proj.this.name == "customer_id"
        ):
            _fail("UNSUPPORTED_QUERY", "latest-snapshot inner select must start with customer_id")
    elif customer_proj.name != "customer_id":
        _fail("UNSUPPORTED_QUERY", "latest-snapshot inner select must start with customer_id")
    max_proj = inner_projections[1]
    if not isinstance(max_proj, exp.Alias) or max_proj.alias != "snapshot_date":
        _fail("UNSUPPORTED_QUERY", "latest-snapshot must select MAX(snapshot_date)")
    if not isinstance(max_proj.this, exp.Max) or not isinstance(max_proj.this.this, exp.Column):
        _fail("UNSUPPORTED_QUERY", "latest-snapshot must select MAX(snapshot_date)")
    if _column(max_proj.this.this) != "snapshot_date":
        _fail("UNSUPPORTED_QUERY", "latest-snapshot must select MAX(snapshot_date)")
    inner_where = inner.args.get("where")
    if inner_where is None:
        _fail("TIME_RANGE_ERROR", "latest-snapshot requires snapshot_date <= anchor")
    predicate = inner_where.this
    if not isinstance(predicate, exp.LTE) or not isinstance(predicate.left, exp.Column):
        _fail("TIME_RANGE_ERROR", "latest-snapshot requires snapshot_date <= anchor")
    if (
        _column(predicate.left) != "snapshot_date"
        or not _literal(predicate.right)
        or not _literal_matches_column(predicate.right, "date")
    ):
        _fail("TIME_RANGE_ERROR", "latest-snapshot requires snapshot_date <= anchor")
    on_clause = joins[0].args.get("on")
    if not isinstance(on_clause, exp.And):
        _fail("JOIN_ERROR", "latest-snapshot join must match customer_id and snapshot_date")
    aliases = {"s": "fact_asset_snapshot", "latest": "fact_asset_snapshot"}
    seen_keys: set[str] = set()
    for node in (on_clause.left, on_clause.right):
        if not isinstance(node, exp.EQ):
            _fail("JOIN_ERROR", "latest-snapshot join predicates must be equality")
        left, right = node.left, node.right
        if not isinstance(left, exp.Column) or not isinstance(right, exp.Column):
            _fail("JOIN_ERROR", "latest-snapshot join must compare columns")
        if {left.table, right.table} != {"s", "latest"} or left.name != right.name:
            _fail("JOIN_ERROR", "latest-snapshot join keys are invalid")
        if left.name not in {"customer_id", "snapshot_date"}:
            _fail("JOIN_ERROR", "latest-snapshot join keys are invalid")
        seen_keys.add(left.name)
        _join_column(left, aliases)
        _join_column(right, aliases)
    if seen_keys != {"customer_id", "snapshot_date"}:
        _fail("JOIN_ERROR", "latest-snapshot join must match customer_id and snapshot_date")
    projections = tree.expressions
    if len(projections) != 1 or not isinstance(projections[0], exp.Alias):
        _fail("UNSUPPORTED_QUERY", "one aliased aggregate is required")
    alias_name = projections[0].alias
    if not re.fullmatch(r"[a-z][a-z0-9_]*", alias_name):
        _fail("UNSAFE_SQL", "unsafe output alias")
    aggregate = projections[0].this
    if not isinstance(aggregate, exp.Sum) or not isinstance(aggregate.this, exp.Column):
        _fail("UNSUPPORTED_QUERY", "latest-snapshot must SUM total_asset")
    measure_table, measure_name = _join_column(aggregate.this, aliases)
    if measure_table != "fact_asset_snapshot" or measure_name != "total_asset":
        _fail("UNSUPPORTED_QUERY", "latest-snapshot must SUM total_asset")
    grant = next((item for item in policy.grants if item.table == "fact_asset_snapshot"), None)
    if grant is None:
        _fail("PERMISSION_DENIED", "table is not granted")
    needed = {"customer_id", "snapshot_date", "total_asset"}
    if not needed <= set(grant.columns):
        _fail("PERMISSION_DENIED", "query references a denied column")
    catalog.table("fact_asset_snapshot")
    anchor_sql = predicate.right.sql(dialect="duckdb")
    contributor_sql = (
        'SELECT COUNT(DISTINCT "customer_id") FROM "fact_asset_snapshot" '
        f'WHERE "snapshot_date" <= {anchor_sql}'
    )
    return GuardedQuery(
        sql=sql,
        table="fact_asset_snapshot",
        output_names=(alias_name,),
        output_kinds=("decimal",),
        referenced_columns=tuple(sorted(needed)),
        contributor_sql=contributor_sql,
    )


def _validate_single_table(
    tree: exp.Select, catalog: Catalog, policy: AccessPolicy, sql: str
) -> GuardedQuery:
    from_clause = tree.args.get("from_")
    table = from_clause.this if from_clause else None
    if (
        not isinstance(table, exp.Table)
        or not isinstance(table.this, exp.Identifier)
        or any(v for k, v in table.args.items() if k != "this")
    ):
        _fail("UNSUPPORTED_QUERY", "exactly one unaliased table is required")
    table_name = table.name
    try:
        table_def = catalog.table(table_name)
    except KeyError:
        _fail("UNKNOWN_FIELD", "unknown table")
    grant = next((g for g in policy.grants if g.table == table_name), None)
    if grant is None:
        _fail("PERMISSION_DENIED", "table is not granted")
    granted = set(grant.columns)
    projections = tree.expressions
    if len(projections) != 1 or not isinstance(projections[0], exp.Alias):
        _fail("UNSUPPORTED_QUERY", "one aliased aggregate is required")
    alias = projections[0].alias
    if not re.fullmatch(r"[a-z][a-z0-9_]*", alias):
        _fail("UNSAFE_SQL", "unsafe output alias")
    aggregate = projections[0].this
    if any(v for k, v in aggregate.args.items() if k not in {"this", "big_int"}):
        _fail("UNSUPPORTED_QUERY", "aggregate modifiers are not supported")
    if isinstance(aggregate, exp.Count):
        source = aggregate.this
        if isinstance(source, exp.Distinct):
            values = source.expressions
            if len(values) != 1 or not isinstance(values[0], exp.Column):
                _fail("UNSUPPORTED_QUERY", "COUNT DISTINCT supports one column")
            source_name = _column(values[0])
        elif isinstance(source, exp.Star):
            if any(source.args.values()):
                _fail("UNSUPPORTED_QUERY", "star modifiers are not supported")
            source_name = "*"
        elif isinstance(source, exp.Column):
            source_name = _column(source)
        else:
            _fail("UNSUPPORTED_QUERY", "COUNT supports * or one DISTINCT column")
        output_kind = "integer"
    elif isinstance(aggregate, exp.Sum) and isinstance(aggregate.this, exp.Column):
        source_name = _column(aggregate.this)
        output_kind = "decimal"
        try:
            source_def = table_def.column(source_name)
        except KeyError:
            _fail("UNKNOWN_FIELD", "unknown measure column")
        if source_def.kind != "decimal":
            _fail("UNSUPPORTED_QUERY", "SUM requires a decimal measure")
    else:
        _fail("UNSUPPORTED_QUERY", "only COUNT and SUM aggregates are supported")
    referenced = set()
    if source_name != "*":
        referenced.add(source_name)
    where = tree.args.get("where")
    if where:
        referenced |= _validate_condition(where.this, catalog, table_name)
    known = {c.column_name for c in table_def.columns}
    if not referenced <= known:
        _fail("UNKNOWN_FIELD", "query references an unknown column")
    if not referenced <= granted:
        _fail("PERMISSION_DENIED", "query references a denied column")
    if source_name == "*" and table_def.scope == "customer" and "customer_id" not in granted:
        _fail("PERMISSION_DENIED", "customer scope must include customer_id")
    return GuardedQuery(
        sql=sql,
        table=table_name,
        output_names=(alias,),
        output_kinds=(output_kind,),
        referenced_columns=tuple(sorted(referenced)),
    )


def validate_sql(
    sql: str, catalog: Catalog, policy: AccessPolicy, limits: SqlLimits
) -> GuardedQuery:
    if not isinstance(sql, str) or not sql.strip():
        _fail("UNSAFE_SQL", "empty SQL")
    if len(sql) > limits.max_sql_chars:
        _fail("UNSAFE_SQL", "SQL exceeds configured size limit")
    try:
        statements = sqlglot.parse(sql, read="duckdb")
    except (sqlglot.errors.ParseError, sqlglot.errors.TokenError):
        _fail("UNSAFE_SQL", "SQL could not be parsed")
    if len(statements) != 1:
        _fail("UNSAFE_SQL", "exactly one statement is required")
    tree = statements[0]
    if tree is None:
        _fail("UNSAFE_SQL", "no executable statement")
    if tree.find(*_DENIED):
        _fail("UNSAFE_SQL", "statement contains a denied construct")
    if not isinstance(tree, exp.Select):
        _fail("UNSAFE_SQL", "only a SELECT statement is supported")
    if any(type(node) not in _ALLOWED_NODES for node in tree.walk()):
        _fail("UNSUPPORTED_QUERY", "AST node is outside the v0.1 allowlist")
    for key, value in tree.args.items():
        if value and key not in _ALLOWED_SELECT_KEYS:
            _fail("UNSUPPORTED_QUERY", "query clause is outside the v0.1 subset")
    # Every SELECT, including a nested SELECT if one is ever admitted by the
    # safe subset, must obey the same clause allowlist.  Checking only the
    # outer query lets a future special-case validator accidentally inherit a
    # permissive nested clause.
    for node in tree.walk():
        if isinstance(node, exp.Select):
            for key, value in node.args.items():
                if value and key not in _ALLOWED_SELECT_KEYS:
                    _fail("UNSUPPORTED_QUERY", "query clause is outside the v0.1 subset")
    if tree.find(exp.Join):
        if _is_latest_snapshot_query(tree):
            return _validate_latest_snapshot(tree, catalog, policy, sql)
        return _validate_join_query(tree, catalog, policy, limits)
    if tree.args.get("group"):
        return _validate_grouped_query(tree, catalog, policy, sql)
    return _validate_single_table(tree, catalog, policy, sql)
