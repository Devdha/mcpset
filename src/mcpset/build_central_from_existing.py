#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
기존 MCP 설정들을 수집하여 중앙 ~/.mcp/config.json을 생성/갱신 (append-only 병합)
- 소스:
  - ~/.cursor/mcp.json (mcpServers)
  - ~/Library/Application Support/Claude/claude_desktop_config.json (mcpServers)
  - ~/.codex/config.toml ([mcp_servers])
- 정책: 키 단위 append-only 병합 (배열은 중복 제거하여 뒤에 추가, 스칼라는 최초 값 유지)
- 출력: { "mcpServers": { ... } }
- 보고서: 각 서버/키가 어느 소스에서 왔는지 리포트(JSON + 콘솔 요약)
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# TOML libs
USE_TOMLKIT = False
try:
    import tomlkit  # type: ignore
    USE_TOMLKIT = True
except Exception:
    pass

if not USE_TOMLKIT:
    try:
        import toml  # type: ignore
    except Exception:
        toml = None  # type: ignore

HOME = Path.home()
CURSOR_JSON = HOME/".cursor"/"mcp.json"
CLAUDE_DESKTOP_JSON = HOME/"Library"/"Application Support"/"Claude"/"claude_desktop_config.json"
CODEX_TOML = HOME/".codex"/"config.toml"
CENTRAL_DEFAULT = HOME/".mcp"/"config.json"
BUILD_REPORT_DEFAULT = HOME/".mcp"/"last_build_report.json"


def is_mapping(x: Any) -> bool:
    return isinstance(x, dict)


def is_list(x: Any) -> bool:
    return isinstance(x, list)


def to_plain(v: Any) -> Any:
    """Convert tomlkit/toml values to plain Python types recursively."""
    if isinstance(v, dict):
        return {k: to_plain(v[k]) for k in v}
    if isinstance(v, list):
        return [to_plain(x) for x in v]
    return v


def append_only(a: Any, b: Any) -> Any:
    """Append-only deep merge: keep existing in a; add missing from b; arrays = a + (b - a)."""
    if is_mapping(a) and is_mapping(b):
        out = dict(a)
        for k, bv in b.items():
            if k in out:
                av = out[k]
                if is_mapping(av) and is_mapping(bv):
                    out[k] = append_only(av, bv)
                elif is_list(av) and is_list(bv):
                    out[k] = av + [x for x in bv if x not in av]
                else:
                    out[k] = av  # keep existing scalar
            else:
                out[k] = bv
        return out
    if is_list(a) and is_list(b):
        return a + [x for x in b if x not in a]
    return a


def read_json_servers(path: Path) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        servers = data.get("mcpServers", {})
        if isinstance(servers, dict):
            return servers
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"경고: JSON 읽기 실패 {path}: {e}", file=sys.stderr)
    return {}


def read_codex_servers(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        if USE_TOMLKIT:
            txt = path.read_text(encoding="utf-8")
            doc = tomlkit.parse(txt)  # type: ignore
        else:
            if not toml:  # type: ignore
                return {}
            doc = toml.load(str(path))  # type: ignore
        tbl = doc.get("mcp_servers", {})
        if isinstance(tbl, dict):
            return to_plain(tbl)
    except Exception as e:
        print(f"경고: TOML 읽기 실패 {path}: {e}", file=sys.stderr)
    return {}


def write_json(path: Path, obj: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            import shutil
            shutil.copy2(path, str(path) + ".bak")
        except Exception:
            pass
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")


def build(out_path: Path, apply: bool, report_path: Path | None) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    provenance: Dict[str, Any] = {}

    sources: List[Tuple[str, Dict[str, Any], str]] = [
        ("cursor", read_json_servers(CURSOR_JSON), str(CURSOR_JSON)),
        ("claude_desktop", read_json_servers(CLAUDE_DESKTOP_JSON), str(CLAUDE_DESKTOP_JSON)),
        ("codex", read_codex_servers(CODEX_TOML), str(CODEX_TOML)),
    ]

    for src_name, servers, src_path in sources:
        for name, conf in servers.items():
            if name not in merged:
                merged[name] = conf
                provenance[name] = {
                    "introduced_by": src_name,
                    "sources": [src_name],
                    "source_paths": {src_name: src_path},
                    "added_keys": list(conf.keys()) if isinstance(conf, dict) else [],
                    "added_env_keys": list(conf.get("env", {}).keys()) if isinstance(conf, dict) and isinstance(conf.get("env"), dict) else [],
                    "added_array_items": {
                        k: list(conf[k]) for k in conf.keys() if isinstance(conf.get(k), list)
                    } if isinstance(conf, dict) else {},
                }
            else:
                # track contributions per top-level key
                if src_name not in provenance[name]["sources"]:
                    provenance[name]["sources"].append(src_name)
                    provenance[name]["source_paths"][src_name] = src_path
                if isinstance(conf, dict) and isinstance(merged[name], dict):
                    for k, v in conf.items():
                        if k not in merged[name]:
                            merged[name][k] = v
                            provenance[name].setdefault("added_keys", []).append(k)
                            if k == "env" and isinstance(v, dict):
                                provenance[name].setdefault("added_env_keys", []).extend(list(v.keys()))
                            if isinstance(v, list):
                                provenance[name].setdefault("added_array_items", {}).setdefault(k, [])
                                provenance[name]["added_array_items"][k].extend([x for x in v])
                        else:
                            # nested merge behavior tracking (one level for env + arrays)
                            if k == "env" and isinstance(v, dict) and isinstance(merged[name][k], dict):
                                added = [ek for ek in v.keys() if ek not in merged[name][k]]
                                if added:
                                    provenance[name].setdefault("added_env_keys", []).extend(added)
                                    for ek in added:
                                        merged[name][k][ek] = v[ek]
                            elif isinstance(v, list) and isinstance(merged[name][k], list):
                                to_add = [x for x in v if x not in merged[name][k]]
                                if to_add:
                                    merged[name][k].extend(to_add)
                                    provenance[name].setdefault("added_array_items", {}).setdefault(k, [])
                                    provenance[name]["added_array_items"][k].extend(to_add)
                            elif is_mapping(v) and is_mapping(merged[name][k]):
                                # generic object: add missing keys
                                for subk, subv in v.items():
                                    if subk not in merged[name][k]:
                                        merged[name][k][subk] = subv
                                        provenance[name].setdefault("added_keys", []).append(f"{k}.{subk}")
                else:
                    # keep existing scalar/object, append-only semantics
                    pass

    central = {"mcpServers": merged}

    # Build report
    report = {
        "sources": {s: p for s, _, p in sources},
        "stats": {
            "total_servers": len(merged),
            "by_source_presence": {
                s: len([1 for name in merged.keys() if s in provenance.get(name, {}).get("sources", [])])
                for s, _, _ in sources
            },
        },
        "servers": provenance,
    }

    if apply:
        write_json(out_path, central)
        print(f"[APPLY] 중앙 파일 갱신: {out_path}")

    # Write report JSON
    if report_path is None:
        report_path = BUILD_REPORT_DEFAULT
    write_json(Path(report_path), report)

    # Console summary
    print(f"[REPORT] 통합 서버 수: {report['stats']['total_servers']}")
    for name, info in sorted(provenance.items()):
        introduced = info.get("introduced_by")
        sources_list = ",".join(info.get("sources", []))
        added_keys = ",".join(info.get("added_keys", [])) if info.get("added_keys") else "-"
        added_env = ",".join(info.get("added_env_keys", [])) if info.get("added_env_keys") else "-"
        print(f" - {name}: introduced_by={introduced}; sources=[{sources_list}]; added_keys=[{added_keys}]; added_env=[{added_env}]")

    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(CENTRAL_DEFAULT))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report-json", default=str(BUILD_REPORT_DEFAULT))
    args = ap.parse_args()

    out_path = Path(args.out)
    build(out_path, args.apply, Path(args.report_json))


if __name__ == "__main__":
    main()
