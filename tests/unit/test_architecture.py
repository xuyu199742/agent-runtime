import ast
from pathlib import Path


def imports_under(directory: Path) -> set[str]:
    imports = set()
    for path in directory.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    return imports


def test_domain_and_application_dependency_boundaries():
    root = Path(__file__).resolve().parents[2] / "app"
    forbidden_domain = ("fastapi", "sqlalchemy", "redis", "langchain", "langgraph")
    forbidden_application = (
        "sqlalchemy",
        "redis",
        "langchain",
        "langgraph",
        "app.persistence.database",
    )
    assert not any(module.startswith(forbidden_domain) for module in imports_under(root / "domain"))
    assert not any(
        module.startswith(forbidden_application) for module in imports_under(root / "application")
    )
    assert "app.persistence.database" not in imports_under(root / "runtime")
