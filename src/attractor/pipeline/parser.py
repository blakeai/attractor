"""Recursive descent parser for the Attractor DOT subset."""

from __future__ import annotations

import typing
from dataclasses import dataclass
from typing import Any

from attractor.pipeline.graph import Edge, Graph, Node


class ParseError(Exception):
    def __init__(self, message: str, line: int = 0, col: int = 0):
        self.line = line
        self.col = col
        super().__init__(f"Parse error at line {line}, col {col}: {message}")


@dataclass
class Token:
    kind: str  # "ident", "string", "int", "float", "bool", "keyword", "symbol", "eof"
    value: str
    line: int = 0
    col: int = 0


class Lexer:
    KEYWORDS: typing.ClassVar[set[str]] = {"digraph", "graph", "node", "edge", "subgraph", "true", "false"}
    SYMBOLS: typing.ClassVar[set[str]] = {"[", "]", "{", "}", "=", "->", ",", ";"}

    def __init__(self, source: str):
        self._source = source
        self._pos = 0
        self._line = 1
        self._col = 1
        self._tokens: list[Token] = []
        self._tokenize()
        self._index = 0

    def _advance(self, n: int = 1) -> None:
        for _ in range(n):
            if self._pos < len(self._source):
                if self._source[self._pos] == "\n":
                    self._line += 1
                    self._col = 1
                else:
                    self._col += 1
                self._pos += 1

    def _peek(self) -> str:
        if self._pos < len(self._source):
            return self._source[self._pos]
        return ""

    def _peek_ahead(self, n: int = 1) -> str:
        pos = self._pos + n
        if pos < len(self._source):
            return self._source[pos]
        return ""

    def _skip_whitespace_and_comments(self) -> None:
        while self._pos < len(self._source):
            c = self._peek()
            if c in " \t\r\n":
                self._advance()
            elif c == "/" and self._peek_ahead() == "/":
                # Line comment
                while self._pos < len(self._source) and self._peek() != "\n":
                    self._advance()
            elif c == "/" and self._peek_ahead() == "*":
                # Block comment
                self._advance(2)
                while self._pos < len(self._source):
                    if self._peek() == "*" and self._peek_ahead() == "/":
                        self._advance(2)
                        break
                    self._advance()
            else:
                break

    def _read_string(self) -> str:
        self._advance()  # Skip opening quote
        result: list[str] = []
        while self._pos < len(self._source):
            c = self._peek()
            if c == "\\":
                self._advance()
                nc = self._peek()
                if nc == '"':
                    result.append('"')
                elif nc == "n":
                    result.append("\n")
                elif nc == "t":
                    result.append("\t")
                elif nc == "\\":
                    result.append("\\")
                else:
                    result.append(nc)
                self._advance()
            elif c == '"':
                self._advance()
                return "".join(result)
            else:
                result.append(c)
                self._advance()
        raise ParseError("Unterminated string", self._line, self._col)

    def _read_number(self) -> tuple[str, str]:
        start = self._pos
        if self._peek() == "-":
            self._advance()
        while self._pos < len(self._source) and self._peek().isdigit():
            self._advance()

        # Check for duration suffix
        if self._pos < len(self._source) and self._peek() in "mshd":
            if self._peek() == "m" and self._peek_ahead() == "s":
                self._advance(2)
                return "string", self._source[start : self._pos]
            elif self._peek() in "smhd":
                self._advance()
                return "string", self._source[start : self._pos]

        if self._pos < len(self._source) and self._peek() == ".":
            self._advance()
            while self._pos < len(self._source) and self._peek().isdigit():
                self._advance()
            return "float", self._source[start : self._pos]

        return "int", self._source[start : self._pos]

    def _read_identifier(self) -> str:
        start = self._pos
        while self._pos < len(self._source) and (
            self._peek().isalnum() or self._peek() in "_."
        ):
            self._advance()
        return self._source[start : self._pos]

    def _tokenize(self) -> None:
        while self._pos < len(self._source):
            self._skip_whitespace_and_comments()
            if self._pos >= len(self._source):
                break

            line, col = self._line, self._col
            c = self._peek()

            if c == '"':
                value = self._read_string()
                self._tokens.append(Token("string", value, line, col))
            elif c == "-" and self._peek_ahead() == ">":
                self._advance(2)
                self._tokens.append(Token("symbol", "->", line, col))
            elif c in "[]{},;=":
                self._advance()
                self._tokens.append(Token("symbol", c, line, col))
            elif c == "-" or c.isdigit():
                kind, value = self._read_number()
                self._tokens.append(Token(kind, value, line, col))
            elif c.isalpha() or c == "_":
                value = self._read_identifier()
                if value in ("true", "false"):
                    self._tokens.append(Token("bool", value, line, col))
                elif value in self.KEYWORDS:
                    self._tokens.append(Token("keyword", value, line, col))
                else:
                    self._tokens.append(Token("ident", value, line, col))
            else:
                self._advance()  # Skip unknown chars

        self._tokens.append(Token("eof", "", self._line, self._col))

    def peek(self) -> Token:
        return self._tokens[self._index]

    def advance(self) -> Token:
        tok = self._tokens[self._index]
        if self._index < len(self._tokens) - 1:
            self._index += 1
        return tok

    def expect(self, kind: str, value: str | None = None) -> Token:
        tok = self.peek()
        if tok.kind != kind or (value is not None and tok.value != value):
            expected = f"{kind}:{value}" if value else kind
            raise ParseError(f"Expected {expected}, got {tok.kind}:{tok.value}", tok.line, tok.col)
        return self.advance()

    def match(self, kind: str, value: str | None = None) -> Token | None:
        tok = self.peek()
        if tok.kind == kind and (value is None or tok.value == value):
            return self.advance()
        return None


class Parser:
    def __init__(self, source: str):
        self._lexer = Lexer(source)

    def parse(self) -> Graph:
        self._lexer.expect("keyword", "digraph")
        tok = self._lexer.peek()
        name = ""
        if tok.kind == "ident":
            name = self._lexer.advance().value
        self._lexer.expect("symbol", "{")

        graph = Graph(name=name)
        self._parse_statements(graph, graph.node_defaults, graph.edge_defaults)

        self._lexer.expect("symbol", "}")
        return graph

    def _parse_statements(
        self,
        graph: Graph,
        node_defaults: dict[str, Any],
        edge_defaults: dict[str, Any],
    ) -> None:
        while True:
            tok = self._lexer.peek()
            if tok.kind == "symbol" and tok.value == "}":
                break
            if tok.kind == "eof":
                break

            self._parse_statement(graph, node_defaults, edge_defaults)
            self._lexer.match("symbol", ";")

    def _parse_statement(
        self,
        graph: Graph,
        node_defaults: dict[str, Any],
        edge_defaults: dict[str, Any],
    ) -> None:
        tok = self._lexer.peek()

        if tok.kind == "keyword" and tok.value == "graph":
            self._lexer.advance()
            if self._lexer.peek().kind == "symbol" and self._lexer.peek().value == "[":
                attrs = self._parse_attr_block()
                graph.attrs.update(attrs)
            return

        if tok.kind == "keyword" and tok.value == "node":
            self._lexer.advance()
            if self._lexer.peek().kind == "symbol" and self._lexer.peek().value == "[":
                attrs = self._parse_attr_block()
                node_defaults.update(attrs)
            return

        if tok.kind == "keyword" and tok.value == "edge":
            self._lexer.advance()
            if self._lexer.peek().kind == "symbol" and self._lexer.peek().value == "[":
                attrs = self._parse_attr_block()
                edge_defaults.update(attrs)
            return

        if tok.kind == "keyword" and tok.value == "subgraph":
            self._parse_subgraph(graph, node_defaults, edge_defaults)
            return

        if tok.kind == "ident":
            # Could be: node_stmt, edge_stmt, or graph attr (id=value)
            ident = self._lexer.advance().value

            # Check for graph attribute: identifier = value
            if self._lexer.peek().kind == "symbol" and self._lexer.peek().value == "=":
                self._lexer.advance()
                value = self._parse_value()
                graph.attrs[ident] = value
                return

            # Check for edge chain: A -> B -> C [attrs]
            if self._lexer.peek().kind == "symbol" and self._lexer.peek().value == "->":
                self._parse_edge_chain(graph, ident, edge_defaults)
                return

            # Otherwise it's a node statement
            attrs = dict(node_defaults)
            if self._lexer.peek().kind == "symbol" and self._lexer.peek().value == "[":
                node_attrs = self._parse_attr_block()
                attrs.update(node_attrs)

            if ident not in graph.nodes:
                graph.nodes[ident] = Node(id=ident, attrs=attrs)
            else:
                graph.nodes[ident].attrs.update(attrs)

    def _parse_subgraph(
        self,
        graph: Graph,
        parent_node_defaults: dict[str, Any],
        parent_edge_defaults: dict[str, Any],
    ) -> None:
        self._lexer.expect("keyword", "subgraph")
        if self._lexer.peek().kind == "ident":
            self._lexer.advance()  # consume subgraph name (unused)
        self._lexer.expect("symbol", "{")

        # Subgraph inherits parent defaults
        sub_node_defaults = dict(parent_node_defaults)
        sub_edge_defaults = dict(parent_edge_defaults)

        self._parse_statements(graph, sub_node_defaults, sub_edge_defaults)
        self._lexer.expect("symbol", "}")

    def _parse_edge_chain(
        self, graph: Graph, first_id: str, edge_defaults: dict[str, Any]
    ) -> None:
        node_ids = [first_id]

        while self._lexer.match("symbol", "->"):
            tok = self._lexer.expect("ident")
            node_ids.append(tok.value)

        # Parse optional attrs that apply to ALL edges in chain
        attrs = dict(edge_defaults)
        if self._lexer.peek().kind == "symbol" and self._lexer.peek().value == "[":
            chain_attrs = self._parse_attr_block()
            attrs.update(chain_attrs)

        # Create edges between consecutive pairs
        for i in range(len(node_ids) - 1):
            edge = Edge(from_node=node_ids[i], to_node=node_ids[i + 1], attrs=dict(attrs))
            graph.edges.append(edge)

        # Ensure all referenced nodes exist
        for nid in node_ids:
            if nid not in graph.nodes:
                graph.nodes[nid] = Node(id=nid, attrs=dict(graph.node_defaults))

    def _parse_attr_block(self) -> dict[str, Any]:
        self._lexer.expect("symbol", "[")
        attrs: dict[str, Any] = {}

        while True:
            tok = self._lexer.peek()
            if tok.kind == "symbol" and tok.value == "]":
                self._lexer.advance()
                break
            if tok.kind == "eof":
                raise ParseError("Unterminated attribute block", tok.line, tok.col)

            # Parse key = value
            key = self._parse_key()
            self._lexer.expect("symbol", "=")
            value = self._parse_value()
            attrs[key] = value

            self._lexer.match("symbol", ",")

        return attrs

    def _parse_key(self) -> str:
        parts = [self._lexer.expect("ident").value]
        while self._lexer.peek().kind == "ident" and "." in self._lexer.peek().value:
            # Handle qualified IDs that the lexer already joined
            break
        # Handle dot-separated keys like "human.default_choice"
        while self._lexer.peek().kind == "symbol" and self._lexer.peek().value == ".":
            # The dot is part of ident in our lexer, so this may not trigger
            break
        return parts[0]

    def _parse_value(self) -> Any:
        tok = self._lexer.peek()
        if tok.kind == "string":
            self._lexer.advance()
            return tok.value
        elif tok.kind == "int":
            self._lexer.advance()
            return int(tok.value)
        elif tok.kind == "float":
            self._lexer.advance()
            return float(tok.value)
        elif tok.kind == "bool":
            self._lexer.advance()
            return tok.value == "true"
        elif tok.kind == "ident":
            # Bare identifier as value (e.g., LR, TB, box, Mdiamond)
            self._lexer.advance()
            return tok.value
        else:
            raise ParseError(f"Expected value, got {tok.kind}:{tok.value}", tok.line, tok.col)


def parse_dot(source: str) -> Graph:
    """Parse a DOT string into a Graph."""
    parser = Parser(source)
    return parser.parse()


def parse_dot_file(path: str) -> Graph:
    """Parse a DOT file into a Graph."""
    with open(path, encoding="utf-8") as f:
        return parse_dot(f.read())
