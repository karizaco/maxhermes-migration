# Fixture — the 2026-11-05 NTRT brief, rendered with the v3 contract

This is **not a published brief**. It is the 2026-11-05 artifact as delivered in
`karizaco/minimax-cloud-outputs` (`ntrt/2026-11-05.md` + `.csv`), plus the two things the v3
contract added:

1. the `### Gap vs catalyst` subsection (skill §8), and
2. the catalyst lookups for the 20 **wider-screen** names, which the v3 contract requires — the
   CSV's `catalyst` column now carries a lookup for every published name, not only the
   actionable set.

`catalysts.json` holds those 19 wider-screen catalyst lines (TXO has none) with their sources.

## Why it is here

It is the only **real 481-row** dataset that satisfies the v3 contract, so it is the proof that
the checker is calibrated to production data rather than to a synthetic fixture:

```bash
python3 tools/check_ntrt_artifact.py \
    --md tools/fixtures/ntrt/2026-11-05/2026-11-05.md \
    --csv tools/fixtures/ntrt/2026-11-05/2026-11-05.csv
# CONTRACT OK — contract: 14/14 (ntrt-artifact-v3)
```

Run it against the DELIVERED artifact (without the §8 table) and the two new checks fail —
which is the point: the delivered brief predates the requirement.

## Do not publish this

The delivered 2026-11-05 brief in the outputs repo is the artifact of record. This fixture must
never be pushed to `ntrt/` — re-pushing a modified copy of a delivered brief would rewrite
history for no gain.
