#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Codex TOML에서 특정 서버 키 제거
- 입력: --target ~/.codex/config.toml, --server <KEY>
- 동작: [mcp_servers.KEY] 제거
- --report 경로 제공 시 리포트 JSON 기록 {target, type, removed:boolean, server}
"""

import argparse
import json
import sys

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
    ap.add_argument('--target', required=True)
    ap.add_argument('--server', required=True)
    ap.add_argument('--report')
    args = ap.parse_args()

    doc = load_toml(args.target)
    mcp_servers = ensure_table(doc, 'mcp_servers')

    existed = args.server in mcp_servers
    if existed:
        if USE_TOMLKIT:
            del mcp_servers[args.server]
        else:
            mcp_servers.pop(args.server, None)

    if args.report:
        with open(args.report, 'w', encoding='utf-8') as rf:
            json.dump({
                'target': args.target,
                'type': 'codex_toml',
                'server': args.server,
                'removed': bool(existed),
            }, rf, ensure_ascii=False, indent=2)
            rf.write('\n')

    sys.stdout.write(dump_toml(doc))


if __name__ == '__main__':
    main()
