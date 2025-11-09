#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Append-only 병합으로 중앙 JSON(~/.mcp/config.json)의 mcpServers를 Codex TOML(~/.codex/config.toml)의 [mcp_servers]에 반영.
- 기존 값 유지, 새 키/값만 추가, 배열은 중복 제거 후 뒤에 추가
- tomlkit 우선 사용(서식 보존). 없으면 toml 사용.
- --report 옵션으로 대상 변경 리포트를 JSON으로 출력 파일에 기록
"""

import argparse
import json
import sys
from typing import Any, Dict, List

try:
    import tomlkit  # type: ignore
    USE_TOMLKIT = True
except Exception:
    tomlkit = None  # type: ignore
    USE_TOMLKIT = False

if not USE_TOMLKIT:
    try:
        import toml  # type: ignore
    except Exception:
        print("tomlkit 또는 toml 패키지가 필요합니다.\n  pip install tomlkit\n또는 pip install toml", file=sys.stderr)
        sys.exit(1)


def is_mapping(x: Any) -> bool:
    return isinstance(x, dict)


def is_list(x: Any) -> bool:
    return isinstance(x, list)


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
                    # append unique elements by simple equality
                    out[k] = av + [x for x in bv if x not in av]
                else:
                    # keep existing
                    out[k] = av
            else:
                out[k] = bv
        return out
    if is_list(a) and is_list(b):
        return a + [x for x in b if x not in a]
    return a


def to_toml_value(v: Any):
    return v


def load_toml(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        data = f.read()
    if USE_TOMLKIT:
        return tomlkit.parse(data)
    else:
        return toml.loads(data)


def dump_toml(doc) -> str:
    if USE_TOMLKIT:
        return tomlkit.dumps(doc)
    else:
        return toml.dumps(doc)


def ensure_table(doc, key: str):
    if key not in doc or doc[key] is None:
        if USE_TOMLKIT:
            doc[key] = tomlkit.table()
        else:
            doc[key] = {}
    return doc[key]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--central', required=True)
    ap.add_argument('--target', required=True)
    ap.add_argument('--report', help='변경 리포트 JSON을 저장할 경로')
    args = ap.parse_args()

    with open(args.central, 'r', encoding='utf-8') as f:
        central = json.load(f)

    try:
        doc = load_toml(args.target)
    except FileNotFoundError:
        if USE_TOMLKIT:
            doc = tomlkit.document()
        else:
            doc = {}

    mcp_servers = ensure_table(doc, 'mcp_servers')

    central_servers = central.get('mcpServers', {})
    if not isinstance(central_servers, dict):
        central_servers = {}

    if USE_TOMLKIT:
        existing = {k: mcp_servers[k] for k in mcp_servers}
    else:
        existing = dict(mcp_servers)

    merged = {}
    per_server_added_keys: Dict[str, List[str]] = {}
    per_server_added_env_keys: Dict[str, List[str]] = {}
    per_server_added_array_items: Dict[str, Dict[str, List]] = {}

    for name in set(list(existing.keys()) + list(central_servers.keys())):
        if name in existing and name in central_servers:
            # compute additions for report
            a = existing[name]
            b = central_servers[name]
            if is_mapping(a) and is_mapping(b):
                # keys added
                added_top = [k for k in b.keys() if k not in a]
                if added_top:
                    per_server_added_keys[name] = added_top
                # env subkeys
                if 'env' in b and is_mapping(b['env']):
                    aenv = a.get('env', {}) if is_mapping(a.get('env')) else {}
                    added_env = [k for k in b['env'].keys() if k not in aenv]
                    if added_env:
                        per_server_added_env_keys[name] = added_env
                # arrays
                for k, bv in b.items():
                    if is_list(bv):
                        av = a.get(k, []) if is_list(a.get(k)) else []
                        add_items = [x for x in bv if x not in av]
                        if add_items:
                            per_server_added_array_items.setdefault(name, {})[k] = add_items
            merged[name] = append_only(existing[name], central_servers[name])
        elif name in existing:
            merged[name] = existing[name]
        else:
            merged[name] = central_servers[name]
            # brand new server from central
            per_server_added_keys[name] = list(central_servers.get(name, {}).keys()) if is_mapping(central_servers.get(name)) else []
            if is_mapping(central_servers.get(name)) and is_mapping(central_servers[name].get('env')):
                per_server_added_env_keys[name] = list(central_servers[name]['env'].keys())
            if is_mapping(central_servers.get(name)):
                for k, v in central_servers[name].items():
                    if is_list(v):
                        per_server_added_array_items.setdefault(name, {})[k] = list(v)

    # Assign back preserving tomlkit table when possible
    if USE_TOMLKIT:
        for k in merged:
            v = to_toml_value(merged[k])
            mcp_servers[k] = v
    else:
        doc['mcp_servers'] = merged

    if args.report:
        report = {
            'target': args.target,
            'type': 'codex_toml',
            'addedServers': [k for k in merged.keys() if k not in existing],
            'perServer': {
                k: {
                    'addedKeys': per_server_added_keys.get(k, []),
                    'addedEnvKeys': per_server_added_env_keys.get(k, []),
                    'addedArrayItems': per_server_added_array_items.get(k, {}),
                } for k in merged.keys()
            }
        }
        with open(args.report, 'w', encoding='utf-8') as rf:
            json.dump(report, rf, ensure_ascii=False, indent=2)
            rf.write('\n')

    sys.stdout.write(dump_toml(doc))


if __name__ == '__main__':
    main()
