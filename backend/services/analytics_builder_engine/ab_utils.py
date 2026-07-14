"""NBACore v8.3.2 — Engine pure helpers (no DB, no SQL).

Contains:
    - ``safe_arithmetic_eval``: a tokenizer + recursive-descent evaluator for
      derived-column expressions. Accepts ONLY identifiers, numbers, the four
      arithmetic operators, parentheses, and unary minus. NO eval/exec, NO
      function calls, NO column access beyond the supplied row dict
      (v8 §6 "无 eval/exec" + "前端零计算" — the only correct backend impl).
    - ``build_table`` / ``truncate`` / ``infer_type``: in-memory Table model
      helpers (rows are capped at ROW_LIMIT and flagged).
"""
from __future__ import annotations

import re
from typing import Any

from backend.services.analytics_builder_engine import ab_constants as C


# ── Type inference ──
def infer_type(value: Any) -> str:
    """Map a python value to one of {text, int, float, bool}."""
    if value is None:
        return "text"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "text"


def _pg_type_to_logical(pg_type: str) -> str:
    """Map a PostgreSQL information_schema data_type to our logical type."""
    t = (pg_type or "").lower()
    if t in ("integer", "bigint", "smallint", "serial", "bigserial"):
        return "int"
    if t in ("numeric", "real", "double precision", "money"):
        return "float"
    if t == "boolean":
        return "bool"
    return "text"


# ── In-memory Table model ──
def build_table(columns: list[dict], rows: list[dict]) -> dict:
    """Construct a Table dict from columns + rows, inferring nothing extra."""
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": False,
    }


def truncate(table: dict) -> dict:
    """Cap a Table to ROW_LIMIT rows in place, setting ``truncated`` flag."""
    rows = table.get("rows", [])
    if len(rows) > C.ROW_LIMIT:
        table["rows"] = rows[: C.ROW_LIMIT]
        table["truncated"] = True
    table["row_count"] = len(table["rows"])
    return table


# ── Safe arithmetic evaluator (derived columns) ──
_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
    |(?P<num>\d+\.\d+|\d+)
    |(?P<ident>[A-Za-z_][A-Za-z0-9_]*)
    |(?P<op>[+\-*/()])
    """,
    re.VERBOSE,
)


class _Token:
    __slots__ = ("kind", "value")

    def __init__(self, kind: str, value: str) -> None:
        self.kind = kind
        self.value = value


def _tokenize(expr: str) -> list[_Token]:
    tokens: list[_Token] = []
    pos = 0
    n = len(expr)
    while pos < n:
        m = _TOKEN_RE.match(expr, pos)
        if not m:
            raise ValueError(f"非法字符 (位置 {pos}): {expr[pos]!r}")
        pos = m.end()
        kind = m.lastgroup
        assert kind is not None
        if kind == "ws":
            continue
        tokens.append(_Token(kind, m.group(kind)))
    return tokens


class _Parser:
    """Recursive-descent parser for: expr -> term (('+'|'-') term)*."""

    def __init__(self, tokens: list[_Token], columns: set[str]) -> None:
        self.tokens = tokens
        self.columns = columns
        self.i = 0

    def peek(self) -> _Token | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def next(self) -> _Token:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def parse(self) -> "Any":
        if not self.tokens:
            raise ValueError("表达式为空白")
        node = self._expr()
        if self.i != len(self.tokens):
            raise ValueError("表达式存在多余内容")
        return node

    def _expr(self):
        node = self._term()
        while True:
            tok = self.peek()
            if tok and tok.kind == "op" and tok.value in ("+", "-"):
                self.next()
                rhs = self._term()
                node = ("binop", tok.value, node, rhs)
            else:
                return node

    def _term(self):
        node = self._factor()
        while True:
            tok = self.peek()
            if tok and tok.kind == "op" and tok.value in ("*", "/"):
                self.next()
                rhs = self._factor()
                node = ("binop", tok.value, node, rhs)
            else:
                return node

    def _factor(self):
        tok = self.peek()
        if tok is None:
            raise ValueError("表达式意外结束")
        if tok.kind == "op" and tok.value == "(":
            self.next()
            node = self._expr()
            close = self.peek()
            if not (close and close.kind == "op" and close.value == ")"):
                raise ValueError("括号未闭合")
            self.next()
            return node
        if tok.kind == "op" and tok.value == "-":
            self.next()
            return ("neg", self._factor())
        if tok.kind == "op" and tok.value == "+":
            self.next()
            return self._factor()
        if tok.kind == "num":
            self.next()
            val = tok.value
            return ("num", float(val) if "." in val else int(val))
        if tok.kind == "ident":
            self.next()
            if tok.value not in self.columns:
                raise ValueError(f"未知列: {tok.value}")
            return ("col", tok.value)
        raise ValueError(f"非预期符号: {tok.value!r}")


def _eval_node(node, row: dict) -> float:
    kind = node[0]
    if kind == "num":
        return float(node[1])
    if kind == "col":
        v = row.get(node[1])
        if v is None:
            return 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            raise ValueError(f"列 {node[1]} 不是数值: {v!r}")
    if kind == "neg":
        return -_eval_node(node[1], row)
    if kind == "binop":
        _, op, a, b = node
        lhs = _eval_node(a, row)
        rhs = _eval_node(b, row)
        if op == "+":
            return lhs + rhs
        if op == "-":
            return lhs - rhs
        if op == "*":
            return lhs * rhs
        if op == "/":
            if rhs == 0:
                raise ZeroDivisionError("除零")
            return lhs / rhs
    raise ValueError("内部错误: 无法求值节点")


def safe_arithmetic_eval(expr: str, row: dict) -> float:
    """Evaluate a derived-column expression ``expr`` against one ``row``.

    Only ``+ - * / ( )``, numbers, and identifiers (row columns) are allowed.
    Raises ``ValueError`` / ``ZeroDivisionError`` on any violation — callers
    turn these into a per-node error.
    """
    if not isinstance(expr, str) or not expr.strip():
        raise ValueError("表达式为空白")
    tokens = _tokenize(expr)
    columns = set(row.keys())
    tree = _Parser(tokens, columns).parse()
    return _eval_node(tree, row)
