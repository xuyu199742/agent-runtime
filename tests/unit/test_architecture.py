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


def test_http_routes_do_not_write_sqlalchemy_crud():
    root = Path(__file__).resolve().parents[2] / "app"
    routes = root / "transport" / "http"
    for path in routes.glob("*.py"):
        if path.name == "common.py":
            continue  # FastAPI composition root owns AsyncSession construction.
        source = path.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("sqlalchemy")
                assert node.module != "app.persistence.database"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"commit", "scalars", "execute", "refresh"}


def test_domain_model_definition_has_no_stored_secret():
    from app.domain.agent import ModelDefinition

    assert "api_key_encrypted" not in ModelDefinition.__dataclass_fields__
