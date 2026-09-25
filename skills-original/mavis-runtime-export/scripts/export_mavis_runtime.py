#!/usr/bin/env python3
"""
export_mavis_runtime.py
Orchestrator. Read live Mavis runtime state and write the mavis-runtime/
subtree to disk for commit. Mirror of what the daily cron will run.

Idempotent: safe to re-run; overwrites generated files in place.

Excludes (deliberately, per user rule "no user data"):
  - agents/mavis/memory/MEMORY.md (durable user operating preferences)
  - all of projects/<name>/research/**
  - all runtime state (sessions, cache, background-tasks, auth, etc.)
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

Mavis_HOME = Path(r"C:\Users\admin\.minimax")
STAGING_ROOT = Path(r"C:\Users\admin\.minimax\projects\coding-shared\mavis-runtime-staging")
SUBTREE = STAGING_ROOT / "mavis-runtime"


def sha256_of_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def export_skills(out_root: Path) -> list[dict]:
    src_dir = Mavis_HOME / "agents" / "mavis" / "skills"
    dst_root = out_root / "skills"
    dst_root.mkdir(parents=True, exist_ok=True)

    entries: list[dict] = []
    for skill_dir in sorted(src_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            # Skip non-standard skill dirs (shouldn't happen).
            continue
        slug = skill_dir.name
        dst = dst_root / slug / "SKILL.md"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_md, dst)
        size = dst.stat().st_size
        sha = sha256_of_file(dst)
        entries.append({"path": f"skills/{slug}/SKILL.md", "bytes": size, "sha256": sha})

    return entries


def export_runtime_state_files(out_root: Path) -> list[dict]:
    """
    Copy public-safe runtime state files that have no user data and no secrets.

    Today this is just mcp-runtime-names.json — a tool-routing disambiguation
    table. Adding more here is fine as long as the file is structurally safe
    (no env, no tokens, no API keys).
    """
    dst_root = out_root / "config"
    dst_root.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    safe_files = [
        ("mcp-runtime-names.json", Mavis_HOME / "mcp-runtime-names.json"),
    ]
    for relname, src in safe_files:
        if not src.exists():
            continue
        dst = dst_root / relname
        shutil.copy2(src, dst)
        entries.append({
            "path": f"config/{relname}",
            "bytes": dst.stat().st_size,
            "sha256": sha256_of_file(dst),
        })
    return entries


def export_scrubbed_configs(out_root: Path) -> list[dict]:
    """
    Run the scrubbers that produce public-safe versions of the runtime configs.

    Each scrubber is responsible for writing into `out_root / config/` and
    for printing a one-line audit. Failures abort the export.
    """
    entries: list[dict] = []
    scrub_scripts = [
        ("scrub_config_yaml.py", "config/config.public.yaml"),
    ]
    for script_name, expected_relpath in scrub_scripts:
        script_path = out_root / "scripts" / script_name
        if not script_path.exists():
            print(f"WARN: scrubber script missing: {script_path}", file=sys.stderr)
            continue
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            print(f"ERROR: scrubber {script_name} failed:", file=sys.stderr)
            print(result.stdout, file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            sys.exit(result.returncode or 4)
        expected = out_root / expected_relpath
        if expected.exists():
            entries.append({
                "path": expected_relpath,
                "bytes": expected.stat().st_size,
                "sha256": sha256_of_file(expected),
            })
    return entries


def export_memory_topics(out_root: Path) -> list[dict]:
    src_dir = Mavis_HOME / "agents" / "mavis" / "memory" / "topics"
    dst_root = out_root / "agents" / "mavis" / "memory" / "topics"
    dst_root.mkdir(parents=True, exist_ok=True)

    entries: list[dict] = []
    for md in sorted(src_dir.glob("*.md")):
        dst = dst_root / md.name
        shutil.copy2(md, dst)
        size = dst.stat().st_size
        sha = sha256_of_file(dst)
        entries.append({"path": f"agents/mavis/memory/topics/{md.name}",
                        "bytes": size, "sha256": sha})
    return entries


def slugify(name: str) -> str:
    """Convert a cron-task name into a Windows-safe filename slug."""
    import re
    s = name.lower()
    # Replace time colons (e.g. "09:50") with empty so "09:50" becomes "0950".
    s = re.sub(r"(\d):(\d)", r"\1\2", s)
    # Replace em-dash / en-dash / hyphen / parentheses / other punctuation with hyphen.
    s = re.sub(r"[—–‐‑\-(){}\[\]<>]", "-", s)
    # Collapse whitespace into single hyphens.
    s = re.sub(r"[\s_]+", "-", s)
    # Strip any remaining non-alphanumeric / non-hyphen chars.
    s = re.sub(r"[^a-z0-9\-]", "", s)
    # Collapse repeated hyphens.
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def export_routines(out_root: Path, cron_json_path: Path | None = None) -> list[dict]:
    """
    Mirror every active cron task into a markdown routine file. Each file
    captures the full cron metadata (name, schedule, timezone, project root,
    prompt body) verbatim — same pattern as the Grok Bot routines/*.md files.

    Accepts cron data via:
      1. `--cron-json <path>` argument (preferred, avoids CLI dependency)
      2. `mavis cron list` subprocess fallback (if cron_json_path is None)
    """
    dst_root = out_root / "routines"
    dst_root.mkdir(parents=True, exist_ok=True)

    if cron_json_path is not None:
        payload = json.loads(cron_json_path.read_text(encoding="utf-8"))
    else:
        # subprocess fallback only when the mavis CLI is actually installed.
        import shutil as _shutil
        if _shutil.which("mavis") is None:
            print(
                "WARN: mavis CLI not on PATH and --cron-json not provided; "
                "skipping routines export. Pass --cron-json <path> to include them.",
                file=sys.stderr,
            )
            return []
        result = subprocess.run(
            ["mavis", "cron", "list"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            print(f"ERROR: mavis cron list failed: {result.stderr}", file=sys.stderr)
            sys.exit(1)
        payload = json.loads(result.stdout)

    tasks = payload.get("response", {}).get("tasks", []) if "response" in payload else payload.get("tasks", [])

    entries: list[dict] = []
    for t in tasks:
        if not t.get("enabled", True):
            continue
        name = t["cronName"]
        slug = slugify(name)
        dst = dst_root / f"{slug}.md"

        body = (
            f"# {name}\n\n"
            f"- **Cron ID:** `{t.get('cronId', '')}`\n"
            f"- **Agent:** `{t.get('agentName', '')}`\n"
            f"- **Schedule:** `{t.get('schedule', '')}` ({t.get('timezone', '')})\n"
            f"- **Schedule type:** `{t.get('scheduleType', '')}`\n"
            f"- **Project root:** `{t.get('project', '')}`\n"
            f"- **Model:** `{t.get('model', '')}`\n"
            f"- **Status:** `{t.get('status', '')}`\n"
            f"- **Enabled:** `{t.get('enabled', True)}`\n"
            f"- **Next run (ms):** `{t.get('nextRun', '')}`\n"
            f"- **Session mode:** `{t.get('session', {}).get('mode', '')}`\n\n"
            f"## Prompt body\n\n"
            f"```text\n"
            f"{t.get('prompt', '').rstrip()}\n"
            f"```\n"
        )

        dst.write_text(body, encoding="utf-8")
        size = dst.stat().st_size
        sha = sha256_of_file(dst)
        entries.append({"path": f"routines/{slug}.md", "bytes": size, "sha256": sha})

    return entries


def write_routines_registry(out_root: Path, routine_entries: list[dict],
                            cron_json_path: Path | None = None) -> int:
    """
    Write a summary table that mirrors agent-ops' config/routines-registry.md
    pattern. Pulls cron metadata via the CLI (or pre-saved JSON) and renders
    a markdown table.
    """
    dst = out_root / "config" / "routines-registry.md"
    dst.parent.mkdir(parents=True, exist_ok=True)

    if cron_json_path is not None:
        payload = json.loads(cron_json_path.read_text(encoding="utf-8"))
        tasks = payload.get("tasks", []) if "tasks" in payload else payload.get("response", {}).get("tasks", [])
    else:
        import shutil as _shutil
        if _shutil.which("mavis") is None:
            print(
                "WARN: mavis CLI not on PATH and --cron-json not provided; "
                "writing empty routines registry.",
                file=sys.stderr,
            )
            dst.write_text(
                "# Cron routines registry — Mavis\n\n"
                f"_Generated: {dt.datetime.now(dt.UTC).isoformat().replace('+00:00','Z')}_\n\n"
                "No roster available — pass --cron-json <path> to populate this table.\n",
                encoding="utf-8",
            )
            return 0
        result = subprocess.run(
            ["mavis", "cron", "list"],
            capture_output=True, text=True, check=False,
        )
        payload = json.loads(result.stdout)
        tasks = payload.get("response", {}).get("tasks", [])

    lines = [
        "# Cron routines registry — Mavis",
        "",
        f"_Generated: {dt.datetime.now(dt.UTC).isoformat().replace('+00:00','Z')}_",
        "",
        "Summary of all enabled scheduled cron routines attached to the `mavis` agent. "
        "Each row points to a per-routine mirror under `routines/<slug>.md`.",
        "",
        "| # | Name | Schedule | TZ | Project root | Mirror |",
        "|---|---|---|---|---|---|",
    ]
    idx = 1
    for t in tasks:
        if not t.get("enabled", True):
            continue
        name = t["cronName"]
        slug = slugify(name)
        lines.append(
            f"| {idx} | {name} | `{t.get('schedule','')}` | {t.get('timezone','')} "
            f"| `{t.get('project','')}` | `routines/{slug}.md` |"
        )
        idx += 1

    body = "\n".join(lines) + "\n"
    dst.write_text(body, encoding="utf-8")
    return idx - 1


def write_manifest(out_root: Path, file_entries: list[dict], summary: dict) -> None:
    manifest = {
        "subtree": "mavis-runtime",
        "exported_at": dt.datetime.now(dt.UTC).isoformat().replace('+00:00','Z'),
        "source": str(Mavis_HOME),
        "summary": summary,
        "files": file_entries,
    }
    dst = out_root / "MANIFEST.json"
    dst.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def write_readme(out_root: Path, summary: dict) -> None:
    body = f"""# mavis-runtime

Public, scrubbed backup of the **Mavis** agent's reusable knowledge base for
the [`karizaco/agent-ops`](https://github.com/karizaco/agent-ops) knowledge
repository. Parallel to the existing Grok Bot artifacts at the root of this
repo (which live under `agents/`, `config/`, `routines/`, `skills/`).

This subtree is **read-only knowledge**. It does not contain:
- secrets (MCP `env` blocks, API keys, auth tokens),
- runtime state (sessions, cache, background tasks),
- user data (watchlists, briefs, EOD history, research notes),
- per-project AGENTS.md or per-task deliverables.

## What lives here

| Path | Contents |
|---|---|
| `skills/<slug>/SKILL.md` | {summary['skills']} user-installed Mavis skill workflow definitions |
| `routines/<slug>.md` | {summary['routines']} active cron-routine mirrors (schedule + prompt body) |
| `config/mcp-servers.public.yaml` | Catalog of {summary['mcp_servers']} MCP servers, `env`/`headers` redacted |
| `config/config.public.yaml` | Scrubbed model provider catalog (`apiKey` and full `baseURL` stripped) |
| `config/mcp-runtime-names.json` | Runtime MCP tool-name routing table (no secrets, safe as-is) |
| `config/routines-registry.md` | Summary table of all cron routines |
| `agents/mavis/memory/topics/` | {summary['memory_topics']} procedural memory topic(s) |
| `MANIFEST.json` | Machine-readable index with SHA-256 for every file |
| `scripts/` | Orchestrator + scrubbers (re-runnable; idempotent) |

## How it stays in sync

The `mavis-runtime-export` skill + a daily cron in `~/.minimax/` push updates
to this subtree at **18:05 Asia/Bangkok**, five minutes before the existing
`agent-ops-sync` pull at 18:00 BKK. Mirror stays fresh without manual work.

## Path convention

Windows absolute paths in routine prompts (e.g.
`C:\\Users\\admin\\.minimax\\projects\\coding-shared`) are preserved as-is —
they are not secrets, only the local install layout. They document how the
runtime is wired on this machine.

## How to re-export manually

```powershell
python "{Mavis_HOME}\\projects\\coding-shared\\mavis-runtime-staging\\mavis-runtime\\scripts\\scrub_mcp_config.py"
python "{Mavis_HOME}\\projects\\coding-shared\\mavis-runtime-staging\\mavis-runtime\\scripts\\export_mavis_runtime.py"
```

## DO NOT

- Add any `*.env`, `*.key`, `*token*`, `*secret*`, `*credential*` files.
- Add per-project research outputs (`projects/*/research/**`).
- Add `agents/mavis/memory/MEMORY.md` (user operating preferences).
"""
    (out_root / "README.md").write_text(body, encoding="utf-8")


def write_gitignore(out_root: Path) -> None:
    body = """# Defense in depth — never commit these patterns.
# (The live `mcp.json` is included via its scrubbed public mirror;
#  `mcp-runtime-names.json` is included as-is since it has no secrets.)
*.env
*.env.*
*.key
*.pem
*.p12
*token*
*secret*
*credential*
*password*
auth/
sessions/
cache/
background-tasks/
run/
integrations/
projects/*/research/
projects/*/SPRB*.md
agents/*/memory/MEMORY.md
mcp.json
config.yaml
channel-bindings.yaml
channel-routes.yaml
"""
    (out_root / ".gitignore").write_text(body, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Export Mavis runtime state to mavis-runtime/ subtree.")
    ap.add_argument("--subtree-root", default=str(SUBTREE))
    ap.add_argument("--cron-json", default=None,
                    help="Optional path to a pre-saved `mavis cron list` JSON dump. "
                         "Avoids the subprocess dependency if the mavis CLI is not on PATH.")
    args = ap.parse_args()

    out_root = Path(args.subtree_root)
    out_root.mkdir(parents=True, exist_ok=True)
    cron_json_path = Path(args.cron_json) if args.cron_json else None

    print("[1/5] Exporting skills...")
    skill_entries = export_skills(out_root)
    print(f"      {len(skill_entries)} skill SKILL.md files copied")

    print("[2/5] Exporting memory topics...")
    topic_entries = export_memory_topics(out_root)
    print(f"      {len(topic_entries)} memory topic files copied")

    print("[3/6] Exporting cron routines...")
    routine_entries = export_routines(out_root, cron_json_path)
    print(f"      {len(routine_entries)} routine .md files written")

    print("[4/6] Copying public-safe runtime state files...")
    rt_entries = export_runtime_state_files(out_root)
    print(f"      {len(rt_entries)} runtime state files copied")

    print("[5/6] Running config scrubbers...")
    scrub_entries = export_scrubbed_configs(out_root)
    print(f"      {len(scrub_entries)} scrubbed config files written")

    print("[6/6] Writing routines registry + README + .gitignore + MANIFEST.json...")
    n_routines = write_routines_registry(out_root, routine_entries, cron_json_path)
    print(f"      registry covers {n_routines} active routines")
    summary = {
        "skills": len(skill_entries),
        "routines": len(routine_entries),
        "memory_topics": len(topic_entries),
        "mcp_servers": 7,
        "runtime_state_files": len(rt_entries),
        "scrubbed_configs": len(scrub_entries),
    }
    write_gitignore(out_root)
    write_readme(out_root, summary)

    # Re-list all files for the manifest (now includes registry + scripts + scrub YAML).
    file_entries: list[dict] = []
    for p in sorted(out_root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(out_root).as_posix()
            size = p.stat().st_size
            sha = sha256_of_file(p)
            file_entries.append({"path": rel, "bytes": size, "sha256": sha})

    write_manifest(out_root, file_entries, summary)

    print(f"\nDONE: {len(file_entries)} files in {out_root}")
    print(f"      total bytes: {sum(e['bytes'] for e in file_entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())