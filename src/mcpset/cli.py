#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified MCP config manager
Usage:
  mcpset files [--verbose]
  mcpset templates [--show NAME]
  mcpset list [-f NAME ...] [--values] [--json]
  mcpset add KEY (--from-json JSON | --from-file PATH | --template NAME [--set VAR=VAL ...]) [-f NAME ...] [--force] [--dry-run]
  mcpset remove KEY [-f NAME ...] [--dry-run]
  mcpset init [-f NAME ...] [--apply] [--json]
  mcpset sync [-f NAME ...] [--dry-run]
  mcpset clipboard [-f NAME ...] [-p PATH ...] [--stdout]

Defaults:
  - Without -f, commands apply to ALL targets.
  - The global/central target is named 'root'.

Config:
  targets: ~/.mcp/mcpset.targets.json
  templates: ~/.mcp/mcpset.templates.json
"""
import argparse
import copy
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import tomlkit  # type: ignore
except Exception:
    print("tomlkit 모듈이 필요합니다. pip install tomlkit", file=sys.stderr)
    sys.exit(1)

HOME = Path.home()
TARGETS_PATH = HOME / ".mcp" / "mcpset.targets.json"
TEMPLATES_PATH = HOME / ".mcp" / "mcpset.templates.json"

class Target(Dict[str, Any]):
    @property
    def name(self) -> str:
        return self.get("name")

    @property
    def path(self) -> Path:
        return Path(os.path.expanduser(self.get("path")))

    @property
    def type(self) -> str:
        return self.get("type")  # json | toml

    @property
    def root(self) -> str:
        return self.get("root")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent), encoding="utf-8") as tf:
        json.dump(data, tf, ensure_ascii=False, indent=2, sort_keys=True)
        tmp_name = tf.name
    os.replace(tmp_name, path)


def _load_toml(path: Path):
    if not path.exists():
        return tomlkit.document()
    with path.open("r", encoding="utf-8") as f:
        return tomlkit.parse(f.read())


def _save_toml_atomic(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = tomlkit.dumps(doc)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent), encoding="utf-8") as tf:
        tf.write(txt)
        tmp_name = tf.name
    os.replace(tmp_name, path)

# ---- Merge helpers (append-only semantics) ----

def _is_mapping(x: Any) -> bool:
    return isinstance(x, Mapping)


def _is_list(x: Any) -> bool:
    return isinstance(x, list)


def _to_plain(v: Any) -> Any:
    # convert tomlkit containers to plain Python types
    if isinstance(v, dict):
        return {k: _to_plain(v[k]) for k in v}
    if isinstance(v, list):
        return [_to_plain(x) for x in v]
    return v


def _append_only(a: Any, b: Any) -> Any:
    """Append-only deep merge: keep existing scalar; add missing keys; lists unique-extend."""
    if _is_mapping(a) and _is_mapping(b):
        out = dict(a)
        for k, bv in b.items():
            if k in out:
                av = out[k]
                if _is_mapping(av) and _is_mapping(bv):
                    out[k] = _append_only(av, bv)
                elif _is_list(av) and _is_list(bv):
                    out[k] = av + [x for x in bv if x not in av]
                else:
                    # keep existing scalar or mismatched types
                    out[k] = av
            else:
                out[k] = bv
        return out
    if _is_list(a) and _is_list(b):
        return a + [x for x in b if x not in a]
    return a


def load_targets() -> List[Target]:
    cfg = _load_json(TARGETS_PATH)
    tgs = cfg.get("targets", [])
    # filter valid schema minimally
    return [Target(x) for x in tgs if all(k in x for k in ("name", "path", "type", "root"))]


def load_templates() -> Dict[str, Any]:
    cfg = _load_json(TEMPLATES_PATH)
    return cfg.get("templates", {})


def list_targets(args):
    targets = load_targets()
    for t in targets:
        exists = t.path.exists()
        if args.verbose:
            print(f"{t.name}\t{t.type}\troot={t.root}\t{'EXISTS' if exists else 'MISSING'}\t{t.path}")
        else:
            print(f"{t.name}: {t.path} ({t.type}){'*' if exists else ''}")


def _get_subset_targets(names: Optional[List[str]], universe: Optional[List[Target]] = None) -> List[Target]:
    targets = universe or load_targets()
    if not names:
        return targets
    # Backward-compat synonyms
    synonyms = {"central": "root"}
    normalized = [synonyms.get(n, n) for n in names]
    name_set = set(normalized)
    filtered = [t for t in targets if t.name in name_set]
    missing = name_set - {t.name for t in filtered}
    if missing:
        print(f"알 수 없는 타겟: {', '.join(sorted(missing))}", file=sys.stderr)
    return filtered


def _resolve_central_target(targets: List[Target]) -> Target:
    for t in targets:
        if t.name in {"root", "central"}:
            return t
    return Target({
        "name": "root",
        "path": str(HOME / ".mcp" / "config.json"),
        "type": "json",
        "root": "mcpServers",
    })


def cmd_list(args):
    targets = _get_subset_targets(args.file)
    out: Dict[str, Any] = {}
    group: Dict[str, List[Dict[str, str]]] = {}

    # 수집 단계: 타겟별 키, 그리고 MCP 키별 역인덱스
    cache_per_target: Dict[str, Dict[str, Any]] = {}
    for t in targets:
        keys: List[str] = []
        if t.type == "json" and t.path.exists():
            obj = _load_json(t.path)
            cache_per_target[t.name] = obj
            keys = sorted(list((obj.get(t.root) or {}).keys()))
        elif t.type == "toml" and t.path.exists():
            doc = _load_toml(t.path)
            cache_per_target[t.name] = doc
            tbl = doc.get(t.root) or tomlkit.table()
            keys = sorted(list(tbl.keys()))
        else:
            cache_per_target[t.name] = {}
        out[t.name] = keys
        for k in keys:
            group.setdefault(k, []).append({
                "target": t.name,
                "path": str(t.path),
                "type": t.type,
            })

    # '--view-mcp' 모드: MCP 키로 묶어 어디에 존재하는지 보여줌
    if getattr(args, "view_mcp", False):
        if args.json:
            print(json.dumps(group, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            for k in sorted(group.keys()):
                print(f"* {k}")
                for entry in sorted(group[k], key=lambda x: x["target"]):
                    print(f"  - {entry['target']}: {entry['path']}")
        return

    # 기본/상세 모드
    if args.values:
        for t in targets:
            keys = out.get(t.name, [])
            print(f"# {t.name} -> {t.path}")
            if t.type == "json" and t.path.exists():
                obj = cache_per_target.get(t.name, {})
                data = (obj.get(t.root) or {}) if obj else {}
                if args.json:
                    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
                else:
                    for k in keys:
                        print(f"[{k}] {json.dumps(data.get(k), ensure_ascii=False)}")
            elif t.type == "toml" and t.path.exists():
                doc = cache_per_target.get(t.name)
                tbl = (doc.get(t.root) or tomlkit.table()) if doc else tomlkit.table()
                for k in keys:
                    v = tbl.get(k)
                    print(f"[{k}] {v}")
            print()
    else:
        print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))


def _get_clipboard() -> str:
    """Get clipboard content using OS-native commands"""
    system = platform.system()
    try:
        if system == "Darwin":  # macOS
            return subprocess.check_output(["pbpaste"], text=True)
        elif system == "Linux":
            # Try xclip first, then xsel
            for cmd in [["xclip", "-selection", "clipboard", "-o"], ["xsel", "--clipboard", "--output"]]:
                try:
                    return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
                except (FileNotFoundError, subprocess.CalledProcessError):
                    continue
            raise RuntimeError("클립보드 접근 실패: xclip 또는 xsel 설치 필요 (sudo apt install xclip)")
        elif system == "Windows":
            return subprocess.check_output(["powershell", "-command", "Get-Clipboard"], text=True)
        else:
            raise RuntimeError(f"지원하지 않는 OS: {system}")
    except Exception as e:
        raise SystemExit(f"클립보드 읽기 실패: {e}")


def _parse_clipboard_json() -> Dict[str, Any]:
    """Parse JSON from clipboard and return {key: payload, ...} dict"""
    try:
        clip_text = _get_clipboard()
        data = json.loads(clip_text)
    except json.JSONDecodeError as e:
        raise SystemExit(f"클립보드 내용이 유효한 JSON이 아닙니다: {e}")
    
    # Case 1: {"mcpServers": {...}} → extract mcpServers
    if isinstance(data, dict) and "mcpServers" in data:
        return data["mcpServers"]
    # Case 2: {"key": {...}} → single entry
    elif isinstance(data, dict) and len(data) == 1:
        return data
    # Case 3: {"key1": {...}, "key2": {...}} → multiple entries
    elif isinstance(data, dict):
        return data
    else:
        raise SystemExit("클립보드 JSON 형식이 올바르지 않습니다. 'key': {...} 또는 {mcpServers: {...}} 형태여야 합니다.")


def _set_clipboard(text: str) -> None:
    system = platform.system()
    try:
        if system == "Darwin":
            proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, text=True)
            proc.communicate(text)
            if proc.returncode != 0:
                raise RuntimeError("pbcopy 실패")
        elif system == "Linux":
            for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
                try:
                    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, text=True, stderr=subprocess.DEVNULL)
                    proc.communicate(text)
                    if proc.returncode == 0:
                        return
                except FileNotFoundError:
                    continue
            raise RuntimeError("클립보드 접근 실패: xclip 또는 xsel 설치 필요")
        elif system == "Windows":
            proc = subprocess.Popen(["powershell", "-command", "Set-Clipboard"], stdin=subprocess.PIPE, text=True)
            proc.communicate(text)
            if proc.returncode != 0:
                raise RuntimeError("Set-Clipboard 실패")
        else:
            raise RuntimeError(f"지원하지 않는 OS: {system}")
    except Exception as exc:
        raise SystemExit(f"클립보드 쓰기 실패: {exc}")


def _parse_inline_json_or_file(json_str: Optional[str], file_path: Optional[str]) -> Dict[str, Any]:
    if json_str:
        return json.loads(json_str)
    if file_path:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    raise ValueError("no payload provided")


def _template_payload(name: str, sets: List[str]) -> Dict[str, Any]:
    templates = load_templates()
    if name not in templates:
        raise SystemExit(f"템플릿을 찾을 수 없습니다: {name}")
    data = copy.deepcopy(templates[name].get("data", {}))
    kv = {}
    for s in sets or []:
        if "=" not in s:
            raise SystemExit(f"--set는 KEY=VAL 형식이어야 합니다: {s}")
        k, v = s.split("=", 1)
        kv[k] = v
    pattern = re.compile(r"\{\{([^{}]+)\}\}")

    def sub(v):
        if isinstance(v, str):
            def repl(m):
                key = m.group(1)
                return str(kv.get(key, os.environ.get(key, m.group(0))))
            return pattern.sub(repl, v)
        if isinstance(v, list):
            return [sub(x) for x in v]
        if isinstance(v, dict):
            return {k: sub(val) for k, val in v.items()}
        return v

    return sub(data)


def _ensure_root_json(obj: Dict[str, Any], root: str) -> None:
    if root not in obj or not isinstance(obj[root], dict):
        obj[root] = {}


def _ensure_root_toml(doc, root: str):
    if root not in doc:
        doc[root] = tomlkit.table()


def cmd_add(args):
    targets = _get_subset_targets(args.file)
    
    # Handle clipboard mode: extract multiple keys
    if args.from_clipboard:
        entries = _parse_clipboard_json()
        total_added = 0
        for key, payload in entries.items():
            changed = []
            for t in targets:
                # 파일 존재 여부 체크
                if not t.path.exists():
                    print(f"[WARNING] 파일이 존재하지 않음: {t.name} -> {t.path}")
                    continue
                    
                if t.type == "json":
                    obj = _load_json(t.path)
                    _ensure_root_json(obj, t.root)
                    exists = key in obj[t.root]
                    if exists and not args.force:
                        print(f"[SKIP] 이미 존재: {t.name}:{key}")
                        continue
                    if args.dry_run:
                        print(f"[DRY] 추가 예정: {t.name}:{key} -> {t.path}")
                        # 상세 정보 출력
                        payload_str = json.dumps(payload, ensure_ascii=False, indent=2)
                        print(f"      내용: {payload_str[:100]}..." if len(payload_str) > 100 else f"      내용: {payload_str}")
                    else:
                        obj[t.root][key] = payload
                        _save_json_atomic(t.path, obj)
                        # 상세 정보 출력
                        cmd = payload.get('command', 'N/A')
                        args_info = payload.get('args', [])
                        print(f"[ADD] {t.name}:{key} -> {t.path}")
                        print(f"      command: {cmd}")
                        if args_info:
                            print(f"      args: {args_info}")
                        changed.append(t.name)
                elif t.type == "toml":
                    doc = _load_toml(t.path)
                    _ensure_root_toml(doc, t.root)
                    tbl = doc[t.root]
                    exists = key in tbl
                    if exists and not args.force:
                        print(f"[SKIP] 이미 존재: {t.name}:{key}")
                        continue
                    if args.dry_run:
                        print(f"[DRY] 추가 예정: {t.name}:{key} -> {t.path}")
                        payload_str = json.dumps(payload, ensure_ascii=False, indent=2)
                        print(f"      내용: {payload_str[:100]}..." if len(payload_str) > 100 else f"      내용: {payload_str}")
                    else:
                        entry = tomlkit.table()
                        for k, v in payload.items():
                            if isinstance(v, list):
                                entry[k] = tomlkit.array(v)
                            else:
                                entry[k] = v
                        tbl[key] = entry
                        _save_toml_atomic(t.path, doc)
                        # 상세 정보 출력
                        cmd = payload.get('command', 'N/A')
                        args_info = payload.get('args', [])
                        print(f"[ADD] {t.name}:{key} -> {t.path}")
                        print(f"      command: {cmd}")
                        if args_info:
                            print(f"      args: {args_info}")
                        changed.append(t.name)
            if changed:
                total_added += 1
        if total_added == 0 and not args.dry_run:
            print("변경 없음")
        return
    
    # Original single-key mode
    if not args.key:
        raise SystemExit("KEY 인자가 필요합니다 (클립보드 사용 시 -c)")
    
    if args.template:
        payload = _template_payload(args.template, args.set or [])
    else:
        payload = _parse_inline_json_or_file(args.from_json, args.from_file)

    key = args.key
    changed = []
    for t in targets:
        # 파일 존재 여부 체크
        if not t.path.exists():
            print(f"[WARNING] 파일이 존재하지 않음: {t.name} -> {t.path}")
            continue
            
        if t.type == "json":
            obj = _load_json(t.path)
            _ensure_root_json(obj, t.root)
            exists = key in obj[t.root]
            if exists and not args.force:
                print(f"[SKIP] 이미 존재: {t.name}:{key}")
                continue
            if args.dry_run:
                print(f"[DRY] 추가 예정: {t.name}:{key} -> {t.path}")
                payload_str = json.dumps(payload, ensure_ascii=False, indent=2)
                print(f"      내용: {payload_str[:100]}..." if len(payload_str) > 100 else f"      내용: {payload_str}")
            else:
                obj[t.root][key] = payload
                _save_json_atomic(t.path, obj)
                cmd = payload.get('command', 'N/A')
                args_info = payload.get('args', [])
                print(f"[ADD] {t.name}:{key} -> {t.path}")
                print(f"      command: {cmd}")
                if args_info:
                    print(f"      args: {args_info}")
                changed.append(t.name)
        elif t.type == "toml":
            doc = _load_toml(t.path)
            _ensure_root_toml(doc, t.root)
            tbl = doc[t.root]
            exists = key in tbl
            if exists and not args.force:
                print(f"[SKIP] 이미 존재: {t.name}:{key}")
                continue
            if args.dry_run:
                print(f"[DRY] 추가 예정: {t.name}:{key} -> {t.path}")
                payload_str = json.dumps(payload, ensure_ascii=False, indent=2)
                print(f"      내용: {payload_str[:100]}..." if len(payload_str) > 100 else f"      내용: {payload_str}")
            else:
                entry = tomlkit.table()
                for k, v in payload.items():
                    if isinstance(v, list):
                        entry[k] = tomlkit.array(v)
                    else:
                        entry[k] = v
                tbl[key] = entry
                _save_toml_atomic(t.path, doc)
                cmd = payload.get('command', 'N/A')
                args_info = payload.get('args', [])
                print(f"[ADD] {t.name}:{key} -> {t.path}")
                print(f"      command: {cmd}")
                if args_info:
                    print(f"      args: {args_info}")
                changed.append(t.name)
    if not changed and not args.dry_run:
        print("변경 없음")


def cmd_remove(args):
    targets = _get_subset_targets(args.file)
    key = args.key
    changed = []
    for t in targets:
        if t.type == "json" and t.path.exists():
            obj = _load_json(t.path)
            root = obj.get(t.root) or {}
            if key in root:
                if args.dry_run:
                    print(f"[DRY] 제거 예정: {t.name}:{key} -> {t.path}")
                else:
                    del root[key]
                    obj[t.root] = root
                    _save_json_atomic(t.path, obj)
                    print(f"[DEL] {t.name}:{key} -> {t.path}")
                    changed.append(t.name)
            else:
                print(f"[SKIP] 없음: {t.name}:{key}")
        elif t.type == "toml" and t.path.exists():
            doc = _load_toml(t.path)
            tbl = doc.get(t.root) or tomlkit.table()
            if key in tbl:
                if args.dry_run:
                    print(f"[DRY] 제거 예정: {t.name}:{key} -> {t.path}")
                else:
                    del tbl[key]
                    _save_toml_atomic(t.path, doc)
                    print(f"[DEL] {t.name}:{key} -> {t.path}")
                    changed.append(t.name)
            else:
                print(f"[SKIP] 없음: {t.name}:{key}")
    if not changed and not args.dry_run:
        print("변경 없음")


def templates_cmd(args):
    tmpls = load_templates()
    if args.show:
        name = args.show
        if name not in tmpls:
            print(f"템플릿 없음: {name}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(tmpls[name], ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("\n".join(sorted(tmpls.keys())))


def _read_target_servers(t: Target) -> Dict[str, Any]:
    """타겟 파일에서 서버 맵(name -> config)을 가져오기 (없으면 빈 dict)."""
    if t.type == "json" and t.path.exists():
        obj = _load_json(t.path)
        data = obj.get(t.root) or {}
        return data if isinstance(data, dict) else {}
    if t.type == "toml" and t.path.exists():
        doc = _load_toml(t.path)
        tbl = doc.get(t.root) or tomlkit.table()
        # tomlkit 테이블을 plain dict로 변환
        plain = _to_plain(tbl)
        return plain if isinstance(plain, dict) else {}
    return {}


def cmd_init(args):
    targets = load_targets()
    central = _resolve_central_target(targets)
    base_servers = _read_target_servers(central)
    merged: Dict[str, Any] = {k: _to_plain(v) for k, v in base_servers.items()}

    non_central = [t for t in targets if t.name != central.name]
    sources = _get_subset_targets(args.file, non_central)

    for t in sources:
        servers = _read_target_servers(t)
        for name, conf in servers.items():
            conf_plain = _to_plain(conf)
            if name not in merged:
                merged[name] = conf_plain
            else:
                merged[name] = _append_only(merged[name], conf_plain)

    # 출력 또는 적용
    if args.apply:
        # central JSON 로드 후 root 보장, 병합 결과로 교체
        obj = _load_json(central.path) if central.path.exists() else {}
        if central.root not in obj or not isinstance(obj.get(central.root), dict):
            obj[central.root] = {}
        obj[central.root] = merged
        _save_json_atomic(central.path, obj)
        print(f"[SYNC] 중앙 파일 갱신: {central.path}")

    if args.json:
        print(json.dumps(sorted(list(merged.keys())), ensure_ascii=False, indent=2))
    elif not args.apply:
        print(f"총 서버 수: {len(merged)}")


def cmd_sync(args):
    targets = load_targets()
    central = _resolve_central_target(targets)
    central_servers = _read_target_servers(central)
    if not central_servers:
        print("[WARN] 중앙 설정이 비어 있습니다. 적용해도 변경이 없을 수 있습니다.", file=sys.stderr)

    candidates = [t for t in targets if t.name != central.name]
    dests = _get_subset_targets(args.file, candidates)
    if not dests:
        print("대상 타겟이 없습니다.")
        return

    changed = 0
    for t in dests:
        if t.type == "json":
            obj = _load_json(t.path) if t.path.exists() else {}
            _ensure_root_json(obj, t.root)
            current = obj[t.root]
            updated = _append_only(current, central_servers)
            if updated != current:
                changed += 1
                if args.dry_run:
                    print(f"[DRY] {t.name}: {t.path} 업데이트 예정 ({len(updated)}개 항목)")
                else:
                    obj[t.root] = updated
                    _save_json_atomic(t.path, obj)
                    print(f"[APPLY] {t.name}: {t.path}")
            else:
                print(f"[SKIP] {t.name}: 변경 없음")
        elif t.type == "toml":
            doc = _load_toml(t.path)
            _ensure_root_toml(doc, t.root)
            tbl = doc[t.root]
            current = _to_plain(tbl)
            updated = _append_only(current, central_servers)
            if updated != current:
                changed += 1
                if args.dry_run:
                    print(f"[DRY] {t.name}: {t.path} 업데이트 예정 ({len(updated)}개 항목)")
                else:
                    for key in list(tbl.keys()):
                        del tbl[key]
                    for key, value in updated.items():
                        tbl[key] = value
                    _save_toml_atomic(t.path, doc)
                    print(f"[APPLY] {t.name}: {t.path}")
            else:
                print(f"[SKIP] {t.name}: 변경 없음")
        else:
            print(f"[WARN] 지원하지 않는 타입: {t.name} ({t.type})")

    if args.dry_run:
        print(f"[DRY] {changed}개 타겟에서 변경 예상")


def _read_file_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def cmd_clipboard(args):
    targets = load_targets()
    central = _resolve_central_target(targets)
    all_known = list(targets)
    if not any(t.name == central.name for t in targets):
        all_known.append(central)

    selected = _get_subset_targets(args.file, all_known) if args.file else [central]

    blocks: List[str] = []
    for t in selected:
        path = t.path
        if not path.exists():
            print(f"[WARN] 파일 없음: {path}", file=sys.stderr)
            continue
        text = _read_file_text(path)
        blocks.append(f"##### {t.name}: {path}\n{text}")

    for raw in args.path or []:
        p = Path(os.path.expanduser(raw))
        if not p.exists():
            print(f"[WARN] 파일 없음: {p}", file=sys.stderr)
            continue
        text = _read_file_text(p)
        blocks.append(f"##### custom: {p}\n{text}")

    if not blocks:
        raise SystemExit("복사할 파일이 없습니다.")

    payload = "\n\n".join(blocks)
    if args.stdout:
        print(payload)
    else:
        _set_clipboard(payload)
        print(f"클립보드에 {len(blocks)}개 파일 내용을 복사했습니다.")


def build_parser():
    p = argparse.ArgumentParser(prog="mcpset", description="Unified MCP config manager")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_files = sub.add_parser("files", help="관리 대상 파일 목록 출력")
    sp_files.add_argument("--verbose", action="store_true")
    sp_files.set_defaults(func=list_targets)

    sp_tmpl = sub.add_parser("templates", help="템플릿 목록/보기")
    sp_tmpl.add_argument("--show", metavar="NAME")
    sp_tmpl.set_defaults(func=templates_cmd)

    sp_list = sub.add_parser("list", help="서버 키 목록 출력")
    sp_list.add_argument("-f", "--file", nargs="*", help="대상 파일 이름 필터")
    sp_list.add_argument("--values", action="store_true", help="값까지 출력")
    # MCP 키로 그룹핑하여 어느 툴(타겟)에 존재하는지 보기
    sp_list.add_argument("--view-mcp", dest="view_mcp", action="store_true", help="MCP별 그룹 뷰 (각 키가 어느 타겟에 있는지)")
    sp_list.add_argument("--json", action="store_true", help="JSON 포맷 출력")
    sp_list.set_defaults(func=cmd_list)

    sp_add = sub.add_parser("add", help="서버 추가")
    sp_add.add_argument("key", metavar="KEY", nargs="?", help="서버 키 (클립보드 사용 시 생략 가능)")
    src = sp_add.add_mutually_exclusive_group(required=True)
    src.add_argument("-j", "--from-json", dest="from_json", help="인라인 JSON")
    src.add_argument("-i", "--from-file", dest="from_file", help="JSON 파일 경로")
    src.add_argument("-c", "--from-clipboard", dest="from_clipboard", action="store_true", help="클립보드에서 JSON 읽기")
    src.add_argument("-t", "--template", dest="template", help="템플릿 이름")
    sp_add.add_argument("-s", "--set", action="append", help="템플릿 치환 VAR=VAL", default=[])
    sp_add.add_argument("-f", "--file", nargs="*", help="대상 파일 이름 필터")
    sp_add.add_argument("--force", action="store_true", help="기존 항목 덮어쓰기")
    sp_add.add_argument("-n", "--dry-run", action="store_true")
    sp_add.set_defaults(func=cmd_add)

    sp_rm = sub.add_parser("remove", help="서버 삭제")
    sp_rm.add_argument("key", metavar="KEY")
    sp_rm.add_argument("-f", "--file", nargs="*", help="대상 파일 이름 필터")
    sp_rm.add_argument("--dry-run", action="store_true")
    sp_rm.set_defaults(func=cmd_remove)

    # sync: 모든 타겟을 병합하여 중앙 config.json 생성/갱신
    sp_init = sub.add_parser("init", help="여러 타겟을 병합하여 중앙 config.json 갱신")
    sp_init.add_argument("-f", "--file", nargs="*", help="병합에 포함할 타겟 이름")
    sp_init.add_argument("--apply", action="store_true", help="실제 중앙 파일에 적용")
    sp_init.add_argument("--json", action="store_true", help="병합 결과 키 목록을 JSON으로 출력")
    sp_init.set_defaults(func=cmd_init)

    sp_sync = sub.add_parser("sync", help="중앙 config.json 내용을 다른 타겟에 append-only 적용")
    sp_sync.add_argument("-f", "--file", nargs="*", help="적용할 타겟 이름")
    sp_sync.add_argument("--dry-run", action="store_true", help="파일을 건드리지 않고 변경 요약만 출력")
    sp_sync.set_defaults(func=cmd_sync)

    sp_clip = sub.add_parser("clipboard", help="중앙 또는 지정한 파일 내용을 클립보드/STDOUT으로 복사")
    sp_clip.add_argument("-f", "--file", nargs="*", help="등록된 타겟 이름")
    sp_clip.add_argument("-p", "--path", action="append", help="직접 경로 추가")
    sp_clip.add_argument("--stdout", action="store_true", help="클립보드 대신 표준출력으로 내보내기")
    sp_clip.set_defaults(func=cmd_clipboard)

    return p


def main(argv=None):
    argv = argv or sys.argv[1:]
    p = build_parser()
    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
