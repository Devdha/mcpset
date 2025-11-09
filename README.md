# mcpset

> Unified CLI for keeping MCP client configs in sync.<br/>
> MCP 클라이언트 설정을 한 번에 관리하는 통합 CLI.

Language: [English](#english) · [한국어](#한국어)

---

## English

### Overview
`mcpset` collects MCP server definitions from Cursor, Claude, Codex CLI, and other clients, stores them in a single `~/.mcp/config.json`, and applies them back whenever you need every client in lockstep. The workflow is always **init → sync → clipboard**.

### Features
- One CLI flow covers collect, apply, and share.
- Append-only merge keeps local tweaks intact.
- Works with JSON (Cursor, Claude) and TOML (Codex CLI) targets.
- Template-driven `mcpset add` for repeatable server definitions.
- Pytest coverage for merge helpers and CLI flows.

### Installation
```bash
git clone https://github.com/Devdha/mcpset.git
cd mcpset
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
mcpset --help
```

### Configure targets
Targets live in `~/.mcp/mcpset.targets.json`. Copy the example files to get started:

```bash
mkdir -p ~/.mcp
cp examples/mcpset.targets.example.json ~/.mcp/mcpset.targets.json
cp examples/config.json.example ~/.mcp/config.json
cp examples/mcpset.templates.example.json ~/.mcp/mcpset.templates.json
```

Example snippet:
```json
{
  "targets": [
    {"name": "root",   "path": "~/.mcp/config.json", "type": "json", "root": "mcpServers"},
    {"name": "cursor", "path": "~/.cursor/mcp.json", "type": "json", "root": "mcpServers"},
    {"name": "claude", "path": "~/Library/Application Support/Claude/claude_desktop_config.json", "type": "json", "root": "mcpServers"},
    {"name": "codex",  "path": "~/.codex/config.toml", "type": "toml", "root": "mcp_servers"}
  ]
}
```

### Core commands
```bash
# Collect existing client configs into ~/.mcp/config.json
mcpset init --apply
mcpset init -f cursor claude      # limit sources

# Push the central config back down to targets
mcpset sync --dry-run
mcpset sync

# Share safely
mcpset clipboard
mcpset clipboard -f cursor --stdout
mcpset clipboard --path ~/custom.json

# Utilities
mcpset files --verbose
mcpset list --view-mcp
mcpset add KEY -j '{"command":"python3"}' -f cursor root
mcpset remove KEY -f cursor
mcpset templates --show NAME
```

### Workflow example
```bash
mcpset init --apply          # refresh central config on your main machine
mcpset sync --dry-run        # verify what will change on a new machine
mcpset sync                  # apply for real
mcpset clipboard --stdout > shared-mcp.txt
```

### Development & tests
```bash
ruff check .
pytest
```
When opening PRs, update README/examples/tests together and keep real server endpoints or tokens out of commits. See `CONTRIBUTING.md` and `CODE_OF_CONDUCT.md` for details.

### Project status
- [x] init/sync/clipboard workflow tests
- [x] PyPI metadata + MIT license
- [x] GitHub Actions CI (lint + pytest)

### License
Released under the MIT License (see `LICENSE`).

---

## 한국어

### 개요
`mcpset`는 Cursor, Claude, Codex CLI 등 여러 MCP 클라이언트의 `mcpServers` 설정을 모아 `~/.mcp/config.json`으로 통합하고, 필요 시 각 클라이언트에 다시 배포해 장비 간/팀 간 설정을 손쉽게 맞출 수 있게 해줍니다. 항상 **init → sync → clipboard** 흐름으로 동작합니다.

### 특징
- 하나의 CLI 흐름으로 수집·배포·공유 모두 처리
- 기존 값을 덮어쓰지 않는 append-only 병합
- JSON/TOML 타겟 동시 지원
- 템플릿 기반 `mcpset add`로 반복 작업 단축
- pytest로 머지 로직과 CLI 시나리오 검증

### 설치
```bash
git clone https://github.com/Devdha/mcpset.git
cd mcpset
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
mcpset --help
```

### 타겟 구성
관리 대상 파일 목록은 `~/.mcp/mcpset.targets.json`에 정의하며, 예제 파일을 그대로 복사 후 경로만 수정하면 됩니다.

```bash
mkdir -p ~/.mcp
cp examples/mcpset.targets.example.json ~/.mcp/mcpset.targets.json
cp examples/config.json.example ~/.mcp/config.json
cp examples/mcpset.templates.example.json ~/.mcp/mcpset.templates.json
```

### 주요 명령
```bash
# 여러 클라이언트 설정을 읽어 중앙 config.json 갱신
mcpset init --apply
mcpset init -f cursor claude

# 중앙 config 내용을 각 타겟에 append-only 적용
mcpset sync --dry-run
mcpset sync

# 공유/백업용 출력
mcpset clipboard
mcpset clipboard -f cursor --stdout
mcpset clipboard --path ~/custom.json

# 유틸리티
mcpset files --verbose
mcpset list --view-mcp
mcpset add KEY -j '{"command":"python3"}' -f cursor root
mcpset remove KEY -f cursor
mcpset templates --show NAME
```

### 워크플로 예시
```bash
mcpset init --apply
mcpset sync --dry-run
mcpset sync
mcpset clipboard --stdout > shared-mcp.txt
```

### 개발 & 테스트
```bash
ruff check .
pytest
```
PR을 만들 때는 README·예제·테스트를 함께 갱신하고, 실제 서버 주소나 토큰이 커밋에 포함되지 않도록 주의하세요. 자세한 기여 지침은 `CONTRIBUTING.md`, 행동 강령은 `CODE_OF_CONDUCT.md`에 있습니다.

### 현재 상태
- [x] init/sync/clipboard 흐름 테스트
- [x] PyPI 메타데이터 및 MIT 라이선스 정비
- [x] GitHub Actions 등 CI 구성 (lint + pytest)

### 라이선스
MIT License (자세한 내용은 `LICENSE` 참조).
