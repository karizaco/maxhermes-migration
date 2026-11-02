# Weekly MCP and API health check (cron #01)

**The canonical prompt for this routine is `cron-prompts/01-weekly-mcp-health-check.md`.**
That is the file the deploy tooling reads and the byte-compare verification checks.

This file keeps only the *why* behind the prompt's design decisions. It is documentation —
it is NOT the prompt, and nothing in it is deployed.

## Why the three-state catalog distinction matters

On 2026-10-21 the catalog call failed with `error: invalid signature
(path=/minimax-cloud/api/v1/connectors/connected-tools/list)`. A naive probe would record that as
"0 financial tools — confirmed still absent" and the ledger would carry a false negative for
weeks. The distinction between *catalog healthy and empty* and *catalog unreachable* is the whole
reason the prompt has three states instead of two.

On 2026-10-31 the catalog returned **133 tools**: 118 `connector__github__*` (new), 13
`connector__matrix__*`, 2 `connector__email_workbench_credentials__*`. Still **zero** financial
MCPs — but a GitHub connector, which is why the fleet can now write to its repos without a PAT in
the sandbox.

## Change history vs. the 2026-10-28 original

1. **Three probe layers**, not one. The original probed env vars and HTTP endpoints only. It now
   also probes the **agent.minimax.io connector catalog** (for newly registered financial MCPs)
   and the **MCP-over-HTTP bridge** (for newly published packs).
2. **Three-state catalog reporting** — see above.
3. **Appends to a running ledger** (`mcp-health/ledger.md`), because a weekly file only shows
   Sunday's state — the *diff* is the answer to "has it landed yet?"
4. **Names the GitHub connector**, which arrived 2026-10-31 and makes the repo push independent of
   `GITHUB_TOKEN`.
