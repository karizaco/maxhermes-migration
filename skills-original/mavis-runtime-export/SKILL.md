# mavis-runtime-export

Exports the Mavis (MiniMax Code) agent runtime state into a public-safe
subtree on the user's `karizaco/agent-ops` GitHub repo, under the
`mavis-runtime/` directory. Mirrors the existing `agent-ops-sync` pattern but
**pushes** instead of pulls.

## What it exports

- `skills/<slug>/SKILL.md` — every user-installed Mavis skill
- `routines/<slug>.md` — every active cron routine (schedule + prompt body)
- `config/mcp-servers.public.yaml` — MCP server catalog with secrets stripped
- `config/routines-registry.md` — summary table of all cron routines
- `agents/mavis/memory/topics/*.md` — procedural memory topics (NOT `MEMORY.md`)
- `MANIFEST.json` — SHA-256 index of every exported file

## What it never exports (per user rule "no user data")

- `agents/mavis/memory/MEMORY.md` (durable user operating preferences)
- `projects/*/research/**` (watchlists, briefs, EOD history, logs)
- `projects/*/SPRB*.md` (per-project deliverables)
- runtime state (sessions, cache, background-tasks, auth, etc.)
- raw `mcp.json` — secrets are scrubbed first by `scripts/scrub_mcp_config.py`

## How to run (one-time or on a schedule)

**Recommended: the single-command entrypoint `run_backup.py`.**

This is what the `daily-mavis-runtime-backup` cron uses. It wraps scrub +
export + git into one subprocess tree, so only the outer `python run_backup.py`
crosses the runtime permission gate — once the user clicks "always allow" on that
one command, every subsequent run is silent (the git subprocesses do not
re-cross the gate).

```powershell
# 1. Populate the cron-list cache (the cron agent does this via the
#    native mavis tool + write tool; for manual runs, the helper reads
#    from MAVIS_CRON_LIST env var or the mavis CLI):
python "${mavisHome}\agents\mavis\skills\mavis-runtime-export\scripts\dump_cron_list.py" --out "<staging>/tmp/cron-list.json"

# 2. Run the wrapper. Defaults are pinned, so no args are required:
python "${mavisHome}\agents\mavis\skills\mavis-runtime-export\scripts\run_backup.py"
# --cron-json    default <staging>/tmp/cron-list.json
# --agent-ops    default <coding-shared>/repo-analysis/agent-ops
# --scrub-out    default <agent-ops>/mavis-runtime/config/mcp-servers.public.yaml
# --dry-run      scrub + export only, skip git
```

The wrapper does:
- `scrub_mcp_config.py --out <agent-ops>/mavis-runtime/config/mcp-servers.public.yaml`
- `export_mavis_runtime.py --subtree-root <agent-ops>/mavis-runtime --cron-json <cache>`
- `git pull --ff-only` (in agent-ops)
- `git add mavis-runtime/`
- `git diff --cached --quiet` → skip commit if clean
- `git commit -m "Mavis backup <iso>"`
- `git push origin main`
- append one audit line to `research/logs/audit.log`

**Manual two-script path** (use when you need finer control):

```powershell
# Step A: scrub mcp.json → writes config/mcp-servers.public.yaml
python "${mavisHome}\agents\mavis\skills\mavis-runtime-export\scripts\scrub_mcp_config.py"

# Step B: re-export everything (skills, routines, topics, manifest)
#         into the agent-ops clone at the mavis-runtime/ subtree.
python "${mavisHome}\agents\mavis\skills\mavis-runtime-export\scripts\export_mavis_runtime.py"
```

After running the scripts, commit + push:

```powershell
Set-Location "<path-to-agent-ops-clone>"
git pull --ff-only
git add mavis-runtime/
git commit -m "Mavis backup $(Get-Date -Format o)"
git push origin main
```

If `git pull` fails (non-fast-forward, network, auth), append an error line and
do NOT force-resolve. If `git push` fails the same way, do the same. The
expectation is that the daily cron runs this end-to-end and the operator only
investigates when something is red in `research/agent-ops/push-sync.log`.

## Idempotency

Both scripts are safe to re-run. The scrubber overwrites the public YAML. The
exporter overwrites all generated `.md` files and the `MANIFEST.json`. To
remove a stale routine from the public subtree, delete it locally and re-run.

## Fail modes and recovery

- **`mavis` CLI not on PATH** — the exporter accepts `--cron-json <path>` so
  it does not depend on the CLI. The `run_backup.py` wrapper requires the cron
  agent to populate `<staging>/tmp/cron-list.json` first (via the native `mavis`
  tool + the `write` tool). If the cache file is missing, `run_backup.py` exits
  non-zero with a clear error — do NOT chain to a subprocess `mavis cron list`,
  the CLI isn't installed.
- **Stale slug collisions** — slug normalization is in
  `scripts/export_mavis_runtime.py` → `slugify()`. If a new cron name breaks
  the slug, fix it there, not by renaming files manually.
- **Secret leak** — the scrubber is the only safe way to write the MCP YAML.
  If a real secret ever lands in the public repo, treat it as compromised:
  rotate the secret, rewrite history with `git filter-repo`, force-push.
- **Permission prompts on each run** — the cron prompt is designed to issue
  ONE bash call (`python run_backup.py`); the wrapper's git subprocesses do
  not re-cross the runtime permission gate. Once the user has clicked "always
  allow" on that one bash pattern, subsequent runs are silent. If you see new
  prompts, the cron prompt has been edited to issue more than one bash call —
  revert to the single-command shape.
