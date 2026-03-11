"""Basic integration tests for tree builder functionality."""
from pathlib import Path
import tempfile
import pytest
from zonny_core.tree.builder import Entity, Tree, TreeBuilder, build_tree


def test_entity_creation():
    """Test Entity dataclass creation."""
    entity = Entity(
        name="test_function",
        type="function",
        file="test.py",
        start_line=10,
        end_line=15,
    )
    assert entity.name == "test_function"
    assert entity.type == "function"
    assert entity.parent is None
    
    # Test to_dict
    data = entity.to_dict()
    assert "name" in data
    assert "type" in data
    assert "parent" not in data  # None values excluded


def test_tree_serialization():
    """Test Tree serialization and deserialization."""
    entities = [
        Entity(name="func1", type="function", file="a.py", start_line=1, end_line=5),
        Entity(name="Class1", type="class", file="a.py", start_line=10, end_line=20),
    ]
    tree = Tree(
        entities=entities,
        files=["a.py"],
        languages={"python": 1},
    )
    
    # Serialize
    json_str = tree.to_json()
    assert "func1" in json_str
    assert "Class1" in json_str
    
    # Write and load
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        tree.write(Path(f.name))
        loaded = Tree.load(Path(f.name))
    
    assert len(loaded.entities) == 2
    assert loaded.entities[0].name == "func1"
    assert loaded.languages["python"] == 1


def test_python_regex_fallback():
    """Test Python parsing with regex fallback (no tree-sitter)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.py"
        test_file.write_text("""
def hello_world():
    print("Hello")

class MyClass:
    def method(self):
        pass
""")
        
        builder = TreeBuilder(Path(tmpdir), languages=["python"])
        tree = builder.build()
        
        assert len(tree.entities) >= 2
        entity_names = [e.name for e in tree.entities]
        assert "hello_world" in entity_names
        assert "MyClass" in entity_names


def test_language_detection():
    """Test language detection from file extensions."""
    builder = TreeBuilder(Path("."))
    
    assert builder._detect_language(Path("test.py")) == "python"
    assert builder._detect_language(Path("app.js")) == "javascript"
    assert builder._detect_language(Path("main.ts")) == "typescript"
    assert builder._detect_language(Path("Main.java")) == "java"
    assert builder._detect_language(Path("main.go")) == "go"
    assert builder._detect_language(Path("app.rb")) == "ruby"
    assert builder._detect_language(Path("data.txt")) == "unknown"


def test_ignore_patterns():
    """Test that common directories are ignored."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        
        # Create files in ignored directories
        (root / "node_modules" / "lib").mkdir(parents=True)
        (root / "node_modules" / "lib" / "ignored.js").write_text("ignored")
        
        (root / ".git" / "objects").mkdir(parents=True)
        (root / ".git" / "objects" / "ignored").write_text("ignored")
        
        (root / "__pycache__").mkdir()
        (root / "__pycache__" / "ignored.pyc").write_text("ignored")
        
        # Create valid file
        (root / "app.py").write_text("def main(): pass")
        
        builder = TreeBuilder(root, languages=["python", "javascript"])
        files = builder._walk_files()
        
        # Only app.py should be included
        file_names = [f.name for f in files]
        assert "app.py" in file_names
        assert "ignored.js" not in file_names
        assert "ignored.pyc" not in file_names


def test_build_tree_integration():
    """Integration test for full tree building."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        
        # Create a mini project
        (root / "src").mkdir()
        (root / "src" / "main.py").write_text("""
def start():
    return "started"

class Application:
    def run(self):
        start()
""")
        
        (root / "src" / "utils.py").write_text("""
def helper():
    pass
""")
        
        # Build tree
        tree = build_tree(root, languages=["python"])
        
        # Verify results
        assert len(tree.files) == 2
        assert len(tree.entities) >= 3  # start, Application, Application.run, helper
        assert tree.languages["python"] == 2
        
        # Check entity details
        entity_names = [e.name for e in tree.entities]
        assert "start" in entity_names
        assert "Application" in entity_names
        assert "helper" in entity_names


def test_max_depth_limit():
    """Test max_depth parameter limits directory traversal."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        
        # Create nested directories
        (root / "level1" / "level2" / "level3").mkdir(parents=True)
        (root / "level1" / "a.py").write_text("def a(): pass")
        (root / "level1" / "level2" / "b.py").write_text("def b(): pass")
        (root / "level1" / "level2" / "level3" / "c.py").write_text("def c(): pass")
        
        # Build with max_depth=1 (only level1)
        tree = build_tree(root, max_depth=1)
        assert len(tree.files) == 1  # Only a.py
        
        # Build with max_depth=2 (level1 + level2)
        tree = build_tree(root, max_depth=2)
        assert len(tree.files) == 2  # a.py + b.py


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
