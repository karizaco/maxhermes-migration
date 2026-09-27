# Skills (Cloud-deployed copies)

These are the local Mavis skills, copied here for Cloud Mavis cron prompts to reference via raw.githubusercontent.com URLs.

## Origin

Source of truth: `skills-original/` (also in this repo, captures from `C:\Users\admin\.minimax\agents\mavis\skills\` and `C:\Users\admin\.minimax\projects\coding-shared\mavis-runtime-staging\mavis-runtime\skills\`).

## How Cloud cron prompts read them

Each prompt is built with this pattern:

```
# Cloud cron reads SKILL.md via:
SKILL_URL="https://raw.githubusercontent.com/karizaco/maxhermes-migration/main/cloud-prompts/skills/<name>/SKILL.md"
# (or whatever subdir)
# Then prompts the model to either:
#   (a) read it via web_fetch / requests.get()
#   (b) have the prompt include "If you need the spec, fetch it from $SKILL_URL and follow verbatim"
```

## Maintenance

When local Mavis skills change, re-mirror them here. Two ways:

1. **Manual:** copy new SKILL.md into the corresponding directory, commit, push.
2. **Automated:** cron #11 (mavis-runtime-export, Bucket 3) can be configured to mirror on every backup run.

Until cron #11 is migrated to Cloud, manual is the only path.

## Why this directory is `cloud-prompts/skills/` and not just `skills/`

Repo layout intent:
- `/skills-original/` — captured from local Mavis, READ-ONLY baseline
- `/cloud-prompts/skills/` — working copy that Cloud refs; can drift if edited
- `/scripts/`, `/memory/` — repo metadata (not skill content)

If the local Mavis is decommissioned eventually, `/skills-original/` is the audit trail.
