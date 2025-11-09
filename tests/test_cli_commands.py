import json
from types import SimpleNamespace

from mcpset import cli


def _target(name, path, root="mcpServers", type_="json"):
    return {"name": name, "path": str(path), "type": type_, "root": root}


def test_init_collects_sources_into_central(cli_env, tmp_path):
    central = cli_env.config_dir / "config.json"
    cursor = tmp_path / "cursor.json"
    claude = tmp_path / "claude.json"

    cli_env.write_targets([
        _target("root", central),
        _target("cursor", cursor),
        _target("claude", claude),
    ])

    cursor.write_text(json.dumps({
        "mcpServers": {
            "cursor-server": {"command": "python", "args": ["cursor"]}
        }
    }, ensure_ascii=False))
    claude.write_text(json.dumps({
        "mcpServers": {
            "claude-server": {"command": "python", "args": ["claude"]}
        }
    }, ensure_ascii=False))
    central.write_text(json.dumps({"mcpServers": {}}, ensure_ascii=False))

    cli.cmd_init(SimpleNamespace(file=None, apply=True, json=False))

    data = json.loads(central.read_text())
    assert set(data["mcpServers"].keys()) == {"cursor-server", "claude-server"}


def test_sync_applies_central_to_targets(cli_env, tmp_path):
    central = cli_env.config_dir / "config.json"
    cursor = tmp_path / "cursor.json"

    cli_env.write_targets([
        _target("root", central),
        _target("cursor", cursor),
    ])

    central.write_text(json.dumps({
        "mcpServers": {
            "shared": {"command": "python", "args": ["central"]},
            "new": {"command": "python", "args": ["added"]},
        }
    }, ensure_ascii=False))

    cursor.write_text(json.dumps({
        "mcpServers": {
            "shared": {"command": "python", "args": ["cursor"]}
        }
    }, ensure_ascii=False))

    cli.cmd_sync(SimpleNamespace(file=None, dry_run=False))

    updated = json.loads(cursor.read_text())
    assert "new" in updated["mcpServers"]
    # append-only semantics keep existing cursor arg first while adding the central arg at the tail
    shared_args = updated["mcpServers"]["shared"]["args"]
    assert shared_args[0] == "cursor"
    assert "central" in shared_args


def test_clipboard_stdout_includes_requested_files(cli_env, tmp_path, capsys):
    central = cli_env.config_dir / "config.json"
    extra = tmp_path / "notes.txt"

    cli_env.write_targets([
        _target("root", central),
    ])

    central.write_text("central data\n")
    extra.write_text("extra data\n")

    cli.cmd_clipboard(
        SimpleNamespace(file=None, path=[str(extra)], stdout=True)
    )

    out = capsys.readouterr().out
    assert "##### root" in out
    assert "custom" in out
    assert "extra data" in out
