"""Tree builder — uses tree-sitter to parse source files and build entity graph.

This module provides deterministic code parsing (Condition 4 infrastructure).
The actual semantic labeling happens in zonny-ai (tree enrich command).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from tree_sitter import Language, Parser
except ImportError:
    Parser = None  # type: ignore[assignment, misc]
    Language = None  # type: ignore[assignment, misc]


@dataclass
class Entity:
    """A code entity (function, class, method, etc.)."""
    
    name: str
    type: str  # "function" | "class" | "method" | "variable" | "import"
    file: str
    start_line: int
    end_line: int
    parent: str | None = None  # Parent entity name (for methods in classes)
    calls: list[str] | None = None  # Function calls made by this entity
    references: list[str] | None = None  # Variables/imports referenced
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class Tree:
    """Complete codebase entity tree."""
    
    entities: list[Entity]
    files: list[str]
    languages: dict[str, int]  # language -> file_count
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "entities": [e.to_dict() for e in self.entities],
            "files": self.files,
            "languages": self.languages,
            "total_entities": len(self.entities),
        }
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2)
    
    def write(self, path: Path) -> None:
        """Write tree to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
    
    @classmethod
    def load(cls, path: Path) -> Tree:
        """Load tree from JSON file."""
        data = json.loads(path.read_text(encoding="utf-8"))
        entities = [
            Entity(
                name=e["name"],
                type=e["type"],
                file=e["file"],
                start_line=e["start_line"],
                end_line=e["end_line"],
                parent=e.get("parent"),
                calls=e.get("calls"),
                references=e.get("references"),
            )
            for e in data["entities"]
        ]
        return cls(
            entities=entities,
            files=data["files"],
            languages=data["languages"],
        )


class TreeBuilder:
    """Builds entity trees from source code using tree-sitter."""
    
    def __init__(self, root: Path, languages: list[str] | None = None, max_depth: int | None = None):
        """Initialize tree builder.
        
        Args:
            root: Repository root directory
            languages: List of languages to parse (None = all supported)
            max_depth: Maximum directory depth to scan (None = unlimited)
        """
        self.root = root
        # If languages is None, accept ALL languages (no filter)
        # If languages is a list, only accept those languages
        self.languages = languages
        self.max_depth = max_depth
        self._parsers: dict[str, Any] = {}
        
    def build(self) -> Tree:
        """Build the entity tree by parsing all source files."""
        entities: list[Entity] = []
        files: list[str] = []
        lang_counts: dict[str, int] = {}
        
        # Walk directory and parse files
        for file_path in self._walk_files():
            lang = self._detect_language(file_path)
            
            # Skip if language filter is set and this language is not in it
            if self.languages is not None and lang not in self.languages:
                continue
            
            # Skip completely unknown files (no extension)
            if lang == "unknown" and not file_path.suffix:
                continue
            
            rel_path = str(file_path.relative_to(self.root))
            files.append(rel_path)
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
            
            # Parse file and extract entities
            file_entities = self._parse_file(file_path, rel_path, lang)
            entities.extend(file_entities)
        
        return Tree(
            entities=entities,
            files=files,
            languages=lang_counts,
        )
    
    def _walk_files(self) -> list[Path]:
        """Walk directory tree and collect source files."""
        files: list[Path] = []
        
        def should_ignore(path: Path) -> bool:
            """Check if path should be ignored."""
            ignore_dirs = {
                ".git", ".zonny", "node_modules", "__pycache__", ".pytest_cache",
                "venv", ".venv", "env", ".env", "dist", "build", "target",
                ".idea", ".vscode", "coverage", ".coverage"
            }
            ignore_patterns = {".pyc", ".pyo", ".so", ".dll", ".dylib", ".exe"}
            
            # Check if any parent is an ignored directory
            for part in path.parts:
                if part in ignore_dirs:
                    return True
            
            # Check file suffix
            if any(str(path).endswith(pat) for pat in ignore_patterns):
                return True
            
            return False
        
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            
            # Check depth
            if self.max_depth is not None:
                depth = len(path.relative_to(self.root).parts) - 1
                if depth > self.max_depth:
                    continue
            
            if should_ignore(path):
                continue
            
            files.append(path)
        
        return files
    
    def _detect_language(self, path: Path) -> str:
        """Detect programming language from file extension.
        
        Supports 20+ languages. Unknown extensions are marked as 'unknown'
        but will still be parsed with universal patterns.
        """
        suffix = path.suffix.lower()
        mapping = {
            # Python
            ".py": "python",
            ".pyw": "python",
            # JavaScript/TypeScript
            ".js": "javascript",
            ".mjs": "javascript",
            ".jsx": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            # Java/JVM
            ".java": "java",
            ".kt": "kotlin",
            ".scala": "scala",
            # C/C++
            ".c": "c",
            ".h": "c",
            ".cpp": "cpp",
            ".cc": "cpp",
            ".cxx": "cpp",
            ".hpp": "cpp",
            # C#
            ".cs": "csharp",
            # Go
            ".go": "go",
            # Rust
            ".rs": "rust",
            # Ruby
            ".rb": "ruby",
            # PHP
            ".php": "php",
            # Swift
            ".swift": "swift",
            # Objective-C
            ".m": "objc",
            ".mm": "objc",
            # Shell
            ".sh": "shell",
            ".bash": "shell",
            # Perl
            ".pl": "perl",
            ".pm": "perl",
            # Lua
            ".lua": "lua",
            # R
            ".r": "r",
            # Dart
            ".dart": "dart",
        }
        return mapping.get(suffix, "unknown")
    
    def _parse_file(self, path: Path, rel_path: str, language: str) -> list[Entity]:
        """Parse a source file and extract entities.
        
        If tree-sitter is not available or parsing fails, falls back to
        simple regex-based extraction.
        """
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return []
        
        # Try tree-sitter parsing
        if Parser is not None:
            try:
                from zonny_core.tree.languages import get_parser
                parser = get_parser(language)
                if parser:
                    return self._parse_with_treesitter(content, rel_path, language, parser)
            except Exception:  # noqa: BLE001, S110
                pass  # Fall back to regex
        
        # Fallback: regex-based extraction
        return self._parse_with_regex(content, rel_path, language)
    
    def _parse_with_treesitter(
        self, content: str, file: str, language: str, parser: Any
    ) -> list[Entity]:
        """Parse using tree-sitter (deterministic structural parsing)."""
        from zonny_core.tree.languages import extract_entities
        
        tree = parser.parse(bytes(content, "utf-8"))
        return extract_entities(tree, file, language)
    
    def _parse_with_regex(self, content: str, file: str, language: str) -> list[Entity]:
        """Fallback regex-based parsing when tree-sitter unavailable."""
        import re
        
        entities: list[Entity] = []
        lines = content.splitlines()
        
        if language == "python":
            # Match: def function_name( or class ClassName
            for i, line in enumerate(lines, start=1):
                if match := re.match(r"^\s*def\s+(\w+)\s*\(", line):
                    entities.append(Entity(
                        name=match.group(1),
                        type="function",
                        file=file,
                        start_line=i,
                        end_line=i,  # Approximation
                    ))
                elif match := re.match(r"^\s*class\s+(\w+)", line):
                    entities.append(Entity(
                        name=match.group(1),
                        type="class",
                        file=file,
                        start_line=i,
                        end_line=i,
                    ))
        
        elif language in ("javascript", "typescript"):
            # Match: function name( or const name = or class Name
            for i, line in enumerate(lines, start=1):
                if match := re.match(r"^\s*(?:function|async function)\s+(\w+)\s*\(", line):
                    entities.append(Entity(
                        name=match.group(1),
                        type="function",
                        file=file,
                        start_line=i,
                        end_line=i,
                    ))
                elif match := re.match(r"^\s*(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(", line):
                    entities.append(Entity(
                        name=match.group(1),
                        type="function",
                        file=file,
                        start_line=i,
                        end_line=i,
                    ))
                elif match := re.match(r"^\s*class\s+(\w+)", line):
                    entities.append(Entity(
                        name=match.group(1),
                        type="class",
                        file=file,
                        start_line=i,
                        end_line=i,
                    ))
        
        elif language == "java":
            # Match: public/private/protected type name( or class Name
            for i, line in enumerate(lines, start=1):
                if match := re.match(r"^\s*(?:public|private|protected)?\s*\w+\s+(\w+)\s*\(", line):
                    entities.append(Entity(
                        name=match.group(1),
                        type="method",
                        file=file,
                        start_line=i,
                        end_line=i,
                    ))
                elif match := re.match(r"^\s*(?:public|private)?\s*class\s+(\w+)", line):
                    entities.append(Entity(
                        name=match.group(1),
                        type="class",
                        file=file,
                        start_line=i,
                        end_line=i,
                    ))
        
        else:
            # UNIVERSAL FALLBACK: Works with most C-style and functional languages
            # Matches common patterns: function declarations, classes, structs, etc.
            entities.extend(self._parse_universal(content, file, lines))
        
        return entities
    
    def _parse_universal(self, content: str, file: str, lines: list[str]) -> list[Entity]:
        """Universal parser that works with most programming languages.
        
        Extracts common patterns that appear across many languages:
        - Function definitions: func name(...)
        - Class/struct definitions: class Name, struct Name
        - Method definitions with visibility modifiers
        """
        import re
        entities: list[Entity] = []
        
        # Pattern 1: func/function/def/fn keyword
        # Matches: func foo(), function bar(), def baz(), fn qux()
        func_pattern = r"^\s*(?:function|func|fn|def|fun|proc|sub)\s+(\w+)\s*\("
        
        # Pattern 2: Class/Struct/Interface/Trait declarations
        # Matches: class Foo, struct Bar, interface Baz, trait Qux
        class_pattern = r"^\s*(?:class|struct|interface|trait|protocol|enum|type)\s+(\w+)"
        
        # Pattern 3: Method with visibility (public/private/protected)
        method_pattern = r"^\s*(?:public|private|protected|internal|open)?\s+(?:static|final|override)?\s*(?:func|fun|fn|def)?\s+(\w+)\s*\("
        
        # Pattern 4: C-style function: type name(...)
        c_func_pattern = r"^\s*(?:void|int|float|double|char|long|short|bool|auto|const|static|extern)?\s*\*?\s*(\w+)\s*\([^;]*\)\s*\{"
        
        for i, line in enumerate(lines, start=1):
            # Try function/def pattern
            if match := re.match(func_pattern, line):
                entities.append(Entity(
                    name=match.group(1),
                    type="function",
                    file=file,
                    start_line=i,
                    end_line=i,
                ))
            # Try class/struct pattern
            elif match := re.match(class_pattern, line):
                entities.append(Entity(
                    name=match.group(1),
                    type="class",
                    file=file,
                    start_line=i,
                    end_line=i,
                ))
            # Try method pattern
            elif match := re.match(method_pattern, line):
                name = match.group(1)
                # Avoid common noise words
                if name not in ("if", "for", "while", "switch", "case", "return", "new"):
                    entities.append(Entity(
                        name=name,
                        type="method",
                        file=file,
                        start_line=i,
                        end_line=i,
                    ))
            # Try C-style function (with opening brace)
            elif match := re.match(c_func_pattern, line):
                name = match.group(1)
                if name not in ("if", "for", "while", "switch", "return", "main"):
                    entities.append(Entity(
                        name=name,
                        type="function",
                        file=file,
                        start_line=i,
                        end_line=i,
                    ))
        
        return entities


def build_tree(root: Path, languages: list[str] | None = None, max_depth: int | None = None) -> Tree:
    """Build entity tree for a repository.
    
    Args:
        root: Repository root directory
        languages: List of languages to parse (None = all supported)
        max_depth: Maximum directory depth to scan (None = unlimited)
    
    Returns:
        Complete entity tree
    """
    builder = TreeBuilder(root, languages, max_depth)
    return builder.build()
