"""模型上下文回填迁移不得清除原有配置。"""

import json
from importlib import import_module

from app.context.model_limits import PUBLISHED_MODEL_CONTEXT


def test_upgrade_uses_frozen_limits_even_if_runtime_catalog_changes(monkeypatch):
    migration = import_module("migrations.versions.e7b4c2a91d08_backfill_known_model_context")

    class Bind:
        def __init__(self):
            self.updates = []

        def execute(self, statement, parameters=None):
            if parameters is not None:
                self.updates.append(parameters)
                return None

            class Rows:
                def mappings(self):
                    return [
                        {
                            "id": "legacy-model",
                            "model_name": "deepseek-flash",
                            "config": {},
                        }
                    ]

            return Rows()

    bind = Bind()
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
    monkeypatch.setitem(PUBLISHED_MODEL_CONTEXT, "deepseek-flash", (8192, 1024))

    migration.upgrade()

    assert json.loads(bind.updates[0]["config"]) == {
        "context_window": 1_048_576,
        "max_output_tokens": 393_216,
    }


def test_downgrade_preserves_preexisting_model_context(monkeypatch):
    migration = import_module("migrations.versions.e7b4c2a91d08_backfill_known_model_context")

    class Bind:
        def __init__(self):
            self.updates = []

        def execute(self, statement, parameters=None):
            if parameters is not None:
                self.updates.append(parameters)
                return None

            class Rows:
                def mappings(self):
                    return [
                        {
                            "id": "existing-model",
                            "model_name": "deepseek-flash",
                            "config": {
                                "context_window": 1_048_576,
                                "max_output_tokens": 393_216,
                            },
                        }
                    ]

            return Rows()

    bind = Bind()
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)

    migration.downgrade()

    assert bind.updates == []
