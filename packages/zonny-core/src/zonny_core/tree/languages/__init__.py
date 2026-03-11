"""Language-specific parsers for tree-sitter integration.

This module provides tree-sitter parsers for supported languages and
extracts entities (functions, classes, methods) from ASTs.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tree_sitter import Parser
    from zonny_core.tree.builder import Entity

# Lazy-loaded parsers cache
_PARSERS: dict[str, Any] = {}


def get_parser(language: str) -> Any | None:
    """Get tree-sitter parser for a language.
    
    Args:
        language: Language name (python, javascript, typescript, etc.)
    
    Returns:
        Configured Parser instance, or None if unavailable
    """
    if language in _PARSERS:
        return _PARSERS[language]
    
    try:
        from tree_sitter import Language, Parser
    except ImportError:
        return None
    
    # Try to load language grammar
    # Note: In production, these would be pre-compiled .so files
    # For now, we'll use a fallback approach
    try:
        if language == "python":
            parser = _get_python_parser(Parser, Language)
        elif language in ("javascript", "typescript"):
            parser = _get_js_parser(Parser, Language)
        elif language == "java":
            parser = _get_java_parser(Parser, Language)
        elif language == "go":
            parser = _get_go_parser(Parser, Language)
        elif language == "ruby":
            parser = _get_ruby_parser(Parser, Language)
        else:
            return None
        
        _PARSERS[language] = parser
        return parser
    
    except Exception:  # noqa: BLE001
        # Grammar not available - will fall back to regex
        return None


def _get_python_parser(parser_cls: type[Parser], lang_cls: type) -> Parser | None:
    """Get Python parser (placeholder - requires grammar compilation)."""
    # In production: Language.build_library('build/my-languages.so', ['vendor/tree-sitter-python'])
    # For now, return None to use regex fallback
    return None


def _get_js_parser(parser_cls: type[Parser], lang_cls: type) -> Parser | None:
    """Get JavaScript/TypeScript parser."""
    return None


def _get_java_parser(parser_cls: type[Parser], lang_cls: type) -> Parser | None:
    """Get Java parser."""
    return None


def _get_go_parser(parser_cls: type[Parser], lang_cls: type) -> Parser | None:
    """Get Go parser."""
    return None


def _get_ruby_parser(parser_cls: type[Parser], lang_cls: type) -> Parser | None:
    """Get Ruby parser."""
    return None


def extract_entities(tree: Any, file: str, language: str) -> list[Entity]:
    """Extract entities from a tree-sitter parse tree.
    
    Args:
        tree: tree-sitter Tree object
        file: Relative file path
        language: Programming language
    
    Returns:
        List of extracted entities
    """
    from zonny_core.tree.builder import Entity
    
    entities: list[Entity] = []
    root = tree.root_node
    
    if language == "python":
        entities.extend(_extract_python(root, file))
    elif language in ("javascript", "typescript"):
        entities.extend(_extract_javascript(root, file))
    elif language == "java":
        entities.extend(_extract_java(root, file))
    elif language == "go":
        entities.extend(_extract_go(root, file))
    elif language == "ruby":
        entities.extend(_extract_ruby(root, file))
    
    return entities


def _extract_python(node: Any, file: str, parent: str | None = None) -> list[Entity]:
    """Extract Python entities from AST."""
    from zonny_core.tree.builder import Entity
    
    entities: list[Entity] = []
    
    if node.type == "function_definition":
        name_node = node.child_by_field_name("name")
        if name_node:
            entities.append(Entity(
                name=name_node.text.decode("utf-8"),
                type="function" if parent is None else "method",
                file=file,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                parent=parent,
            ))
    
    elif node.type == "class_definition":
        name_node = node.child_by_field_name("name")
        if name_node:
            class_name = name_node.text.decode("utf-8")
            entities.append(Entity(
                name=class_name,
                type="class",
                file=file,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
            ))
            # Recursively extract methods
            for child in node.children:
                entities.extend(_extract_python(child, file, parent=class_name))
    
    else:
        # Recurse into children
        for child in node.children:
            entities.extend(_extract_python(child, file, parent))
    
    return entities


def _extract_javascript(node: Any, file: str, parent: str | None = None) -> list[Entity]:
    """Extract JavaScript/TypeScript entities from AST."""
    from zonny_core.tree.builder import Entity
    
    entities: list[Entity] = []
    
    if node.type in ("function_declaration", "method_definition"):
        name_node = node.child_by_field_name("name")
        if name_node:
            entities.append(Entity(
                name=name_node.text.decode("utf-8"),
                type="function" if parent is None else "method",
                file=file,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                parent=parent,
            ))
    
    elif node.type == "class_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            class_name = name_node.text.decode("utf-8")
            entities.append(Entity(
                name=class_name,
                type="class",
                file=file,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
            ))
            for child in node.children:
                entities.extend(_extract_javascript(child, file, parent=class_name))
    
    else:
        for child in node.children:
            entities.extend(_extract_javascript(child, file, parent))
    
    return entities


def _extract_java(node: Any, file: str, parent: str | None = None) -> list[Entity]:
    """Extract Java entities from AST."""
    from zonny_core.tree.builder import Entity
    
    entities: list[Entity] = []
    
    if node.type == "method_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            entities.append(Entity(
                name=name_node.text.decode("utf-8"),
                type="method",
                file=file,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                parent=parent,
            ))
    
    elif node.type == "class_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            class_name = name_node.text.decode("utf-8")
            entities.append(Entity(
                name=class_name,
                type="class",
                file=file,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
            ))
            for child in node.children:
                entities.extend(_extract_java(child, file, parent=class_name))
    
    else:
        for child in node.children:
            entities.extend(_extract_java(child, file, parent))
    
    return entities


def _extract_go(node: Any, file: str, parent: str | None = None) -> list[Entity]:
    """Extract Go entities from AST."""
    from zonny_core.tree.builder import Entity
    
    entities: list[Entity] = []
    
    if node.type == "function_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            entities.append(Entity(
                name=name_node.text.decode("utf-8"),
                type="function",
                file=file,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
            ))
    
    elif node.type == "method_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            entities.append(Entity(
                name=name_node.text.decode("utf-8"),
                type="method",
                file=file,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                parent=parent,
            ))
    
    else:
        for child in node.children:
            entities.extend(_extract_go(child, file, parent))
    
    return entities


def _extract_ruby(node: Any, file: str, parent: str | None = None) -> list[Entity]:
    """Extract Ruby entities from AST."""
    from zonny_core.tree.builder import Entity
    
    entities: list[Entity] = []
    
    if node.type == "method":
        name_node = node.child_by_field_name("name")
        if name_node:
            entities.append(Entity(
                name=name_node.text.decode("utf-8"),
                type="function" if parent is None else "method",
                file=file,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                parent=parent,
            ))
    
    elif node.type == "class":
        name_node = node.child_by_field_name("name")
        if name_node:
            class_name = name_node.text.decode("utf-8")
            entities.append(Entity(
                name=class_name,
                type="class",
                file=file,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
            ))
            for child in node.children:
                entities.extend(_extract_ruby(child, file, parent=class_name))
    
    else:
        for child in node.children:
            entities.extend(_extract_ruby(child, file, parent))
    
    return entities


__all__ = ["get_parser", "extract_entities"]

