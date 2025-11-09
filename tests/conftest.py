import json
from types import SimpleNamespace

import pytest

from mcpset import cli


@pytest.fixture()
def cli_env(tmp_path, monkeypatch):
    """Provide a temporary HOME/.mcp layout for CLI tests."""
    home = tmp_path / "home"
    home.mkdir()
    config_dir = home / ".mcp"
    config_dir.mkdir()

    targets_path = config_dir / "mcpset.targets.json"
    templates_path = config_dir / "mcpset.templates.json"
    templates_path.write_text(json.dumps({"templates": {}}, ensure_ascii=False))

    monkeypatch.setattr(cli, "HOME", home)
    monkeypatch.setattr(cli, "TARGETS_PATH", targets_path)
    monkeypatch.setattr(cli, "TEMPLATES_PATH", templates_path)

    def write_targets(entries):
        targets_path.write_text(
            json.dumps({"targets": entries}, ensure_ascii=False, indent=2)
        )

    return SimpleNamespace(
        home=home,
        config_dir=config_dir,
        write_targets=write_targets,
    )
