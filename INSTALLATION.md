# WWT Installation Guide

## System Requirements

### Minimum

- **Python**: 3.10 or higher
- **OS**: macOS (Big Sur+), Linux (Ubuntu 20.04+), Windows (untested)
- **Disk**: 1.4GB free (dependencies + embedding model)
- **RAM**: 2GB (during search)

### Recommended

- **Python**: 3.12+ (faster, better compatibility)
- **Disk**: 2GB free (future growth)
- **RAM**: 4GB (comfortable operation)

### Optional

- **Claude Code**: For MCP integration
- **Gemini CLI**: For Gemini session collection
- **Codex CLI**: For Codex session collection
- **Git**: For branch tracking (automatically detected)

## Installation Methods

### Method 1: pip (Default)

```bash
pip install whatwasthat
```

Installs to user site-packages. Requires `pip` from Python 3.10+.

**Verify:**
```bash
wwt --help
```

### Method 2: uv (Recommended)

[uv](https://github.com/astral-sh/uv) is a fast Rust-based package manager.

```bash
# Install uv if not present
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install WWT
uv tool install whatwasthat
```

**Advantages**
- Faster resolution and installation
- Better dependency management
- Isolated tool environment

**Verify:**
```bash
wwt --help
```

### Method 3: pip --user (Isolated)

For user-only installation without sudo:

```bash
pip install --user whatwasthat
```

Installs to `~/.local/bin/` (add to PATH if needed).

**Verify:**
```bash
~/.local/bin/wwt --help
```

### Method 4: pip with venv (Development)

For development or isolated environment:

```bash
# Create virtual environment
python3.12 -m venv ~/.wwt-venv

# Activate
source ~/.wwt-venv/bin/activate

# Install
pip install whatwasthat

# Verify
wwt --help
```

**Note**: Activate venv before running WWT commands.

## Initial Setup

### Step 1: Initialize Database

```bash
wwt init
```

Creates `~/.wwt/data/vector/` directory and initializes ChromaDB.

**Output**
```
WWT 초기화 완료: /Users/user/.wwt
```

### Step 2: Full Setup (Recommended)

```bash
wwt setup
```

One-command setup that includes:
1. Database initialization
2. Stop Hook installation (auto-ingest on session end)
3. MCP server registration (Claude Code, Gemini CLI, Codex CLI)
4. Hook registration in platform settings
5. Auto-ingest of existing session logs

**First Run Takes 2-3 Minutes**

- ~470MB embedding model download (HuggingFace hub)
- Model lazy-loading (first query ~2s, subsequent <100ms)
- Scans and ingests existing session logs

**Output Example**
```
DB 초기화 중... (최초 실행 시 임베딩 모델 ~470MB 다운로드)
✓ DB 초기화 완료
✓ Stop Hook 스크립트 설치 완료
✓ Stop Hook 등록 완료 (settings.json)
✓ MCP 서버 글로벌 등록 완료
✓ Gemini CLI MCP 서버 등록 완료
✓ Codex CLI MCP 서버 등록 완료

[Claude Code] 120개 세션 적재 중...
  [Claude Code] 50% (60/120) — 45 세션, 1200 청크
  [Claude Code] 100% (120/120) — 95 세션, 2340 청크
✓ [Claude Code] 완료: 95 세션, 2340 청크 (340 신규 임베딩)

설정 완료! 각 플랫폼을 재시작하여 확인하세요.
```

### Step 3: Verify Setup

#### From Terminal

```bash
wwt search "test query"
```

Should return "관련 기억을 찾지 못했습니다." (no results yet) or existing results.

#### From Claude Code

In Claude Code, use MCP:
```
Tell me: search_memory(query='recent work')
```

If registered, returns results or "관련 기억을 찾지 못했습니다."

#### From Gemini CLI

Type: "What was that about recent work?"

Should trigger `search_memory` automatically.

#### Check MCP Registration

```bash
# Claude Code
claude mcp list | grep whatwasthat

# Gemini CLI
gemini mcp list | grep whatwasthat

# Codex CLI
codex mcp list | grep whatwasthat
```

Should show `whatwasthat` server.

## Platform-Specific Setup

### Claude Code

After `wwt setup`:

1. Settings should auto-register MCP
2. Stop Hook auto-installs

**Verify:**
```bash
cat ~/.claude/settings.json | grep -A5 "hooks"
```

Should contain:
```json
{
  "hooks": {
    "Stop": [{
      "hooks": [{
        "command": "bash ~/.claude/hooks/wwt_auto_ingest.sh"
      }]
    }]
  }
}
```

**If Hook Not Registered:**
```bash
wwt setup  # Re-run to re-register
```

**If MCP Not Available:**
```bash
claude mcp add whatwasthat --scope user -- wwt-mcp
```

### Gemini CLI

After `wwt setup`:

1. AfterAgent Hook auto-installs
2. MCP auto-registers

**Verify:**
```bash
cat ~/.gemini/settings.json | grep -A10 "AfterAgent"
```

Should contain:
```json
{
  "hooks": {
    "AfterAgent": [{
      "matcher": "*",
      "hooks": [{
        "command": "bash ~/.wwt/hooks/gemini_ingest.sh",
        "name": "wwt-ingest"
      }]
    }]
  }
}
```

**If Hook Not Registered:**
```bash
wwt setup  # Re-run
```

**If MCP Not Available:**
```bash
gemini mcp add whatwasthat wwt-mcp --scope user
```

### Codex CLI

After `wwt setup`:

1. Stop Hook auto-installs
2. MCP auto-registers
3. Hook auto-registers in `~/.codex/hooks.json`

**Verify:**
```bash
cat ~/.codex/hooks.json | grep -A5 "Stop"
```

Should contain Stop Hook entry.

**If Hook Not Registered:**
```bash
wwt setup  # Re-run
```

**If MCP Not Available:**
```bash
codex mcp add whatwasthat -- wwt-mcp
```

## Troubleshooting Installation

### Python Version Check

```bash
python3 --version
```

Should be 3.10+. If not:

```bash
# macOS (Homebrew)
brew install python@3.12

# Ubuntu
sudo apt install python3.12 python3.12-venv

# Then install WWT:
python3.12 -m pip install whatwasthat
```

### pip Not Found

```bash
# Verify pip is installed
python3 -m pip --version

# If not, install:
python3 -m ensurepip --upgrade

# Then install WWT:
python3 -m pip install whatwasthat
```

### wwt Command Not Found After Install

Likely PATH issue. Try:

```bash
# Find where wwt was installed
python3 -m pip show -f whatwasthat | grep Location

# Or use Python directly
python3 -m whatwasthat.cli.app --help
```

**Fix PATH:**

For `pip install --user`:
```bash
# Add to ~/.bashrc or ~/.zshrc:
export PATH="$HOME/.local/bin:$PATH"

# Then reload:
source ~/.bashrc  # or source ~/.zshrc
```

For `uv tool`:
```bash
# uv auto-manages PATH, should work automatically
# If not, check:
ls ~/.local/bin/wwt
```

### HuggingFace Download Stuck

If `wwt setup` hangs on model download:

```bash
# Check connectivity
ping huggingface.co

# Or manually pre-download:
python3 -c "from huggingface_hub import snapshot_download; snapshot_download('intfloat/multilingual-e5-small')"

# Then retry setup:
wwt setup
```

**Network Issues**

If behind corporate proxy, set environment variables:

```bash
export HTTP_PROXY=http://proxy.company.com:8080
export HTTPS_PROXY=http://proxy.company.com:8080
wwt setup
```

### Permission Denied

```bash
# Fix ownership
sudo chown -R $USER:$GROUP ~/.wwt
sudo chown -R $USER:$GROUP ~/.cache/huggingface

# Or reinstall with --user flag:
pip install --user --force-reinstall whatwasthat
```

### DB Already Exists

If you run `wwt setup` multiple times:

```bash
# Safe to re-run (idempotent)
# Will not re-download model or re-ingest unchanged files
wwt setup
```

**To Reset Everything:**
```bash
wwt reset --force
wwt setup
```

## Uninstall

### Remove WWT

```bash
pip uninstall whatwasthat
```

### Keep Data (Optional)

Data stays in `~/.wwt/` and `~/.cache/huggingface/` for re-installation.

### Full Cleanup

```bash
# Remove all data
rm -rf ~/.wwt
rm -rf ~/.cache/huggingface/hub/models--intfloat--multilingual-e5-small

# Remove hooks (optional)
rm ~/.claude/hooks/wwt_auto_ingest.sh
rm ~/.wwt/hooks/*.sh

# Remove settings (manual editing required)
# Edit ~/.claude/settings.json and remove wwt Stop Hook
# Edit ~/.gemini/settings.json and remove wwt AfterAgent Hook
# Edit ~/.codex/hooks.json and remove wwt Stop Hook
```

## Upgrade

### Check Current Version

```bash
pip show whatwasthat | grep Version
```

### Upgrade to Latest

```bash
pip install --upgrade whatwasthat
```

### Upgrade with uv

```bash
uv tool upgrade whatwasthat
```

## Post-Installation

### Test Search

```bash
# Create test session
mkdir -p ~/.claude/projects/test/sessions
echo '[{"type":"user","message":{"role":"user","content":"Test message"}}]' > \
  ~/.claude/projects/test/sessions/test.jsonl

# Ingest test data
wwt ingest ~/.claude/projects/test/sessions/test.jsonl

# Search
wwt search "test"
```

Expected output:
```
1개 세션에서 관련 기억을 찾았습니다:

  1. test (main) [claude-code] (점수: 0.92)
     [user]: Test message
```

### Configure CLI (Optional)

Add aliases for convenience:

```bash
# In ~/.bashrc or ~/.zshrc:
alias wws='wwt search'
alias wwy='wwt why'
alias wwi='wwt ingest'
```

Then reload shell:
```bash
source ~/.bashrc  # or ~/.zshrc
```

Usage:
```bash
wws "Redis 설정"        # Same as: wwt search "Redis 설정"
wwy "왜 MongoDB"        # Same as: wwt why "왜 MongoDB"
wwi ~/path/to/logs     # Same as: wwt ingest ~/path/to/logs
```

## Dependency Details

WWT depends on:

| Package | Version | Size | Purpose |
|---------|---------|------|---------|
| typer | ≥0.15 | ~150KB | CLI framework |
| chromadb | ≥0.6 | ~47MB | Vector database |
| onnxruntime | ≥1.17 | ~64MB | ONNX inference (CPU) |
| tokenizers | ≥0.19 | ~10MB | Tokenization |
| huggingface-hub | ≥0.23 | ~20MB | Model download |
| numpy | ≥1.24 | ~30MB | Numerical operations |
| pydantic | ≥2.10 | ~15MB | Data validation |
| mcp | ≥1.0 | ~5MB | Model Context Protocol |
| rank-bm25 | ≥0.2.2 | ~100KB | BM25 ranking |
| kiwipiepy | ≥0.23.1 | ~114MB | Korean morphological analysis |
| **Embedding Model** (HuggingFace) | intfloat/multilingual-e5-small | ~470MB | Lazy-loaded on first use |

**Total:** ~750MB installed + ~470MB model on first run

## Supported Python Versions

- **3.10**: Minimum supported (works but slower)
- **3.11**: Good
- **3.12+**: Recommended (20-30% faster)

Check compatibility:
```bash
python3 --version
```

## macOS-Specific Notes

### M1/M2/M3 (Apple Silicon)

All dependencies (including ONNX runtime) have native ARM64 wheels.

```bash
# Confirm M-series detected:
uname -m  # Should output: arm64
```

Performance: ~50ms per query on M1 MacBook.

### Intel Macs

All dependencies have x86_64 wheels (older Macs work fine).

Performance: ~100-150ms per query on Intel.

## Linux-Specific Notes

### Ubuntu / Debian

```bash
# Ensure Python 3.10+ is installed
sudo apt update
sudo apt install python3.12 python3.12-pip python3.12-venv

# Install WWT
python3.12 -m pip install whatwasthat
```

### Fedora / RHEL

```bash
sudo dnf install python3.12 python3.12-pip

python3.12 -m pip install whatwasthat
```

## Windows Notes

WWT is untested on Windows. Likely issues:

- Path separators (use `/` in queries, not `\`)
- Hook scripts (bash scripts need WSL or Git Bash)
- Line endings (CRLF vs LF)

**Workaround**: Use WSL 2 (Windows Subsystem for Linux)

```bash
# Inside WSL:
pip install whatwasthat
wwt setup
```

## Next Steps

After installation:

1. **Try CLI**: `wwt search "your query"`
2. **Enable MCP**: Wait for Claude Code/Gemini to reconnect
3. **Check hooks**: Run a session and verify auto-ingest
4. **Read docs**: See [ARCHITECTURE.md](ARCHITECTURE.md) and [CLI_REFERENCE.md](CLI_REFERENCE.md)

## Support

### Check Logs

```bash
# Auto-ingest log
tail -f ~/.wwt/ingest.log

# Check db
ls -lah ~/.wwt/data/vector/
```

### Test Connectivity

```bash
# Test HuggingFace access
python3 -c "from huggingface_hub import snapshot_download; print(snapshot_download('intfloat/multilingual-e5-small'))"

# Test CLI
wwt --version
```

