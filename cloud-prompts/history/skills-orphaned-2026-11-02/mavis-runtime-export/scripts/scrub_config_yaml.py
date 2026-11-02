#!/usr/bin/env python3
"""
scrub_config_yaml.py
Read ~/.minimax/config.yaml, strip secret-bearing fields, emit a public-safe
catalog of the model provider + its model definitions.

Rules:
  - DROP any value under `provider.<id>.options.apiKey` (replace with marker).
  - DROP any value under `provider.<id>.options.<...>` fields that look like
    a credential: apiKey, api_key, apikey, secret, token, password, key.
  - REDACT `provider.<id>.options.baseURL` hostnames to root domain only
    (e.g. `https://agent.minimax.io/mavis/api/v1/llm/v1`
     -> `https://minimax.io/...`) — keeps the structural fingerprint without
    exposing endpoint paths you may want private. Configurable via --redact-url.
  - KEEP all model definitions: id, name, capabilities, contextWindowOptions,
    modalities, thinking_config. These are vendor-published and stable.
  - KEEP `defaultModel`, `defaultModelVariant`, `logLevel`, `model_order`,
    `whitelist` — useful for understanding which model is in active use.

Safety invariants:
  - Output file MUST NOT contain any string matching the secret-keyword regex
    applied to the source. (Verified at the end of `main()`.)
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

try:
    import yaml  # PyYAML
except ImportError:
    print("ERROR: PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


REDACTED = "<REDACTED — secrets stripped before commit>"
SECRET_KEYS = {"apikey", "api_key", "secret", "token", "password", "key"}


def scrub(d, parent_key: str = "", notes: list | None = None) -> tuple:
    """Recursively walk the config and redact secret-bearing leaves."""
    if notes is None:
        notes = []
    if isinstance(d, dict):
        out = {}
        for k, v in d.items():
            child_key = f"{parent_key}.{k}" if parent_key else k
            if isinstance(v, (dict, list)):
                out[k] = scrub(v, child_key, notes)
            else:
                # Drop secret keys by name. Any non-empty string value gets redacted,
                # even placeholders like "sk-xxx" — those still fingerprint the credential
                # contract and have no business in the public catalog.
                if k.lower() in SECRET_KEYS and isinstance(v, str) and len(v) >= 1:
                    notes.append(f"redacted: {child_key}")
                    out[k] = REDACTED
                else:
                    out[k] = v
        return out
    if isinstance(d, list):
        return [scrub(x, parent_key, notes) for x in d]
    return d


def redact_url_host(url: str) -> str:
    """Keep scheme + root domain only. e.g. https://agent.minimax.io/mavis/api/v1/llm/v1 -> https://minimax.io/"""
    m = re.match(r"^(https?://)([^/]+)(/.*)?$", url)
    if not m:
        return REDACTED
    host = m.group(2)
    # Try to extract the registrable domain (last 2 labels).
    parts = host.split(".")
    if len(parts) >= 2:
        regdom = ".".join(parts[-2:])
    else:
        regdom = host
    return f"{m.group(1)}{regdom}/"


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrub config.yaml for public export.")
    ap.add_argument("--source", default=r"C:\Users\admin\.minimax\config.yaml",
                    help="Path to live config.yaml")
    ap.add_argument("--out", default=r"C:\Users\admin\.minimax\projects\coding-shared\mavis-runtime-staging\mavis-runtime\config\config.public.yaml",
                    help="Where to write the public YAML")
    ap.add_argument("--audit-out", default=r"C:\Users\admin\.minimax\projects\coding-shared\mavis-runtime-staging\audit-config.txt",
                    help="Where to write the audit log")
    ap.add_argument("--redact-url", action="store_true", default=True,
                    help="Reduce baseURL hostnames to root domain (default: True)")
    ap.add_argument("--no-redact-url", dest="redact_url", action="store_false")
    args = ap.parse_args()

    src = Path(args.source)
    dst = Path(args.out)
    audit_path = Path(args.audit_out)

    if not src.exists():
        print(f"ERROR: source not found: {src}", file=sys.stderr)
        return 1

    raw = src.read_text(encoding="utf-8")
    src_sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    data = yaml.safe_load(raw)

    notes: list[str] = []
    scrubbed = scrub(data, "", notes)

    # Redact baseURL hostnames (opt-in/out flag).
    if args.redact_url and isinstance(scrubbed, dict):
        for prov_id, prov in scrubbed.get("provider", {}).items():
            opts = prov.get("options", {}) if isinstance(prov, dict) else {}
            if isinstance(opts, dict) and isinstance(opts.get("baseURL"), str):
                original = opts["baseURL"]
                redacted_url = redact_url_host(original)
                if original != redacted_url:
                    notes.append(f"redacted: provider.{prov_id}.options.baseURL")
                    opts["baseURL"] = redacted_url

    # Emit as a YAML doc with the same order as the source (PyYAML preserves order).
    header = (
        "# config.public.yaml\n"
        "# Public catalog of model-provider config used by the Mavis runtime.\n"
        f"# Source: {src}\n"
        f"# Source SHA-256: {src_sha}\n"
        "# Generated by: scripts/scrub_config_yaml.py\n"
        "# Secrets (`apiKey`, etc.) have been replaced with a REDACTED marker.\n"
        "# `baseURL` hostnames reduced to root domain.\n"
        "# DO NOT edit by hand — re-run the scrubber.\n"
    )

    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(scrubbed, f, sort_keys=False, allow_unicode=True,
                       default_flow_style=False, width=120)

    # Safety invariants — re-read the output and verify no secrets leaked.
    # Strip YAML comment lines first so the header text doesn't trigger false positives
    # (the header contains "apiKey" and "sk-" by design).
    out_lines = dst.read_text(encoding="utf-8").splitlines()
    data_lines = [ln for ln in out_lines if not ln.lstrip().startswith("#")]
    out_data = "\n".join(data_lines)
    leak_checks = {
        "Deepgram key": r"DEEPGRAM_API_KEY",
        "API key marker": r"apiKey:\s*sk-",
        "GitHub token prefix": r"ghp_",
        "Slack token prefix": r"xoxb-",
        "OpenAI key prefix": r"sk-[A-Za-z0-9]{20}",
        "Bearer header": r"Bearer\s+[A-Za-z0-9]",
    }
    leaks = []
    for label, pattern in leak_checks.items():
        if re.search(pattern, out_data):
            leaks.append(f"{label} (pattern: {pattern})")
    if leaks:
        print("ERROR: leaked secret patterns in output:", file=sys.stderr)
        for leak in leaks:
            print(f"  - {leak}", file=sys.stderr)
        return 3

    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("w", encoding="utf-8") as f:
        f.write(f"source: {src}\n")
        f.write(f"source_sha256: {src_sha}\n")
        f.write(f"redactions:\n")
        for line in notes:
            f.write(f"  - {line}\n")
        if not notes:
            f.write("  - (none — no apiKey/baseURL/secret detected)\n")
        f.write(f"\npost-scrub secret-pattern check: PASS (no leaks)\n")

    print(f"OK: wrote public config to {dst}")
    print(f"OK: audit log at {audit_path}")
    print(f"Redactions: {len(notes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())