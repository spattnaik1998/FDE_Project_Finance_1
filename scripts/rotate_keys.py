"""Paste rotated API keys into .env safely, then prove each one works.

    python scripts/rotate_keys.py             # prompt for each key
    python scripts/rotate_keys.py --check     # validate what is already there
    python scripts/rotate_keys.py --only OPENAI_API_KEY ANTHROPIC_API_KEY

Rotation itself cannot be automated from here: every provider needs either a
login or a key delivered by email. What this does is the part around it --
get the new values into the file without breaking anything, and confirm they
actually work before you find out in front of a client.

Three things it is careful about:

**It never echoes a key.** Input is read with ``getpass`` so the value does not
appear on screen, in the shell history, or in this process's command line. A
command line is not a secret on Windows -- any process able to enumerate
processes can read another's -- which is why ``--only`` takes key *names* and
never values.

**It writes in place.** Truncating and rewriting the existing file preserves its
ACL. The usual "write a temp file and rename over it" pattern does not: the new
file inherits the folder's permissions, which on this machine means
``BUILTIN\\Users FullControl`` comes straight back and the hardening is silently
undone. Several editors save that way, so the ACL is re-checked afterwards
either way.

**It validates against the live provider.** A key that parses is not a key that
works. Each rotated credential is probed with one minimal call, and a failure is
reported per key rather than as a single "something is wrong".
"""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
from pathlib import Path

sys.path.insert(0, "src")

logging.basicConfig(level=logging.WARNING,
                    format="%(levelname)-7s %(name)s | %(message)s")

import config

ENV_PATH = Path(".env")

ROTATABLE = {
    "BEA_API_KEY":       "apps.bea.gov/API/signup           (key by email)",
    "CENSUS_API_KEY":    "api.census.gov/data/key_signup.html (key by email)",
    "FRED_API_KEY":      "fredaccount.stlouisfed.org/apikeys  (login)",
    "BLS_API_KEY":       "data.bls.gov/registrationEngine     (key by email)",
    "OPENAI_API_KEY":    "platform.openai.com/api-keys        (login)",
    "ANTHROPIC_API_KEY": "console.anthropic.com/settings/keys (login)",
}


# ---------------------------------------------------------------------------
# Reading and writing .env without disturbing anything else in it
# ---------------------------------------------------------------------------

def read_lines() -> list[str]:
    return ENV_PATH.read_text(encoding="utf-8").splitlines(keepends=True)


def replace_value(lines: list[str], name: str, value: str) -> tuple[list[str], bool]:
    """Swap one key's value, leaving every other line byte-identical.

    Rewrites only the matched line. The file also holds the four
    ``USR_FDE_*_PASSWORD`` entries that ``enable_sql_auth.ps1`` appends, and
    reformatting or reordering those would be a silent way to break the
    database connection later.
    """
    out, replaced = [], False
    for line in lines:
        stripped = line.lstrip()
        if not replaced and (stripped.startswith(name + " ")
                             or stripped.startswith(name + "=")
                             or stripped.startswith(name + ":")):
            newline = "\n" if line.endswith("\n") else ""
            out.append(f"{name} = '{value}'{newline}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and not out[-1].endswith("\n"):
            out[-1] = out[-1] + "\n"
        out.append(f"{name} = '{value}'\n")
    return out, replaced


def write_in_place(lines: list[str]) -> None:
    """Truncate and rewrite the same file, so its ACL survives.

    Deliberately not a temp-file-and-rename: that produces a *new* file which
    inherits the folder ACL, undoing scripts/harden_secrets.ps1 without saying
    so. Verified: the rename pattern took the file from 1 explicit ACE back to
    4 inherited ones.
    """
    with open(ENV_PATH, "w", encoding="utf-8", newline="") as handle:
        handle.writelines(lines)


def broad_access() -> list[str]:
    """Identities with broad Allow access to .env, if any came back."""
    import subprocess
    result = subprocess.run(["icacls", str(ENV_PATH)],
                            capture_output=True, text=True)
    hits = []
    for line in result.stdout.splitlines():
        if any(token in line for token in
               ("BUILTIN\\Users", "Everyone", "Authenticated Users")):
            hits.append(line.strip())
    return hits


# ---------------------------------------------------------------------------
# Live validation, one key at a time
# ---------------------------------------------------------------------------

def probe(name: str, key: str) -> tuple[bool, str]:
    """One minimal live call per credential."""
    try:
        if name == "BEA_API_KEY":
            from sources import bea
            frame = bea.gdp_by_industry(key, table_id=6, frequency="A",
                                        year="2022")
            return (not frame.empty), f"{len(frame)} rows"
        if name == "CENSUS_API_KEY":
            from sources import census
            frame = census.fetch("2018/abstcb",
                                 ["NAICS2017", "TECHUSE", "FIRMPDEMP"],
                                 key, geo="us:*", INDLEVEL="2")
            return (not frame.empty), f"{len(frame)} rows"
        if name == "FRED_API_KEY":
            from sources import fred
            frame = fred.fetch_observations(["PAYEMS"], key,
                                            start="2024-01-01")
            return (not frame.empty), f"{len(frame)} observations"
        if name == "BLS_API_KEY":
            from sources import bls
            if bls.key_is_valid(key):
                return True, "v2 accepted"
            return False, ("v2 rejected; the adapter still works via keyless "
                           "v1 with a narrower window")
        if name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            import os
            from providers import registry
            from providers.base import CallContext
            os.environ[name] = key          # this process only
            registry.reset()
            stage = (registry.Stage.TASK_CLASSIFIER
                     if name == "OPENAI_API_KEY" else registry.Stage.REVIEW_GATE)
            provider = registry.for_stage(stage)
            response = provider.complete(
                "Reply with the single word: ok",
                context=CallContext(stage="rotate_check", run_id="rotate"))
            text = (response.text or "").strip()
            return bool(text), f"{provider.model} -> {text[:12]!r}"
    except Exception as exc:                        # noqa: BLE001 - reported
        return False, f"{type(exc).__name__}: {str(exc)[:70]}"
    return False, "no probe defined"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="Validate the keys already in .env; change nothing")
    parser.add_argument("--only", nargs="*", metavar="KEY_NAME",
                        choices=sorted(ROTATABLE), default=None,
                        help="Key NAMES to rotate (never values)")
    args = parser.parse_args()

    if not ENV_PATH.exists():
        print(f"No {ENV_PATH} in {Path.cwd()}")
        return 1

    targets = args.only or sorted(ROTATABLE)

    print(f"\n{'=' * 74}")
    print("KEY ROTATION" if not args.check else "KEY VALIDATION")
    print(f"{'=' * 74}")

    if not args.check:
        acl = broad_access()
        if acl:
            print("  WARNING: .env is broadly readable:")
            for line in acl:
                print(f"    {line}")
            print("  Run scripts/harden_secrets.ps1 first.\n")

        print("  Paste each new key. Input is hidden. Blank = keep the current one.\n")
        lines = read_lines()
        changed: list[str] = []
        for name in targets:
            where = ROTATABLE[name]
            value = getpass.getpass(f"  {name:20} [{where}]\n    new value: ")
            if not value.strip():
                print("    kept existing\n")
                continue
            lines, existed = replace_value(lines, name, value.strip())
            changed.append(name)
            print(f"    staged ({'replaced' if existed else 'added'})\n")

        if changed:
            write_in_place(lines)
            print(f"  wrote {len(changed)} value(s) to {ENV_PATH} (in place)")
            still = broad_access()
            if still:
                print("  WARNING: .env is broadly readable again after the write.")
                print("  Re-run scripts/harden_secrets.ps1.")
            else:
                print("  ACL still restricted after the write.")
        else:
            print("  nothing changed")

    # --- validate ---------------------------------------------------------
    print(f"\n{'-' * 74}")
    print("  live check")
    print(f"{'-' * 74}")
    keys = config.load_keys(include_models=True)
    sources = config.key_sources(include_models=True)
    failures = warnings = 0
    for name in targets:
        key = keys.get(name)
        if not key:
            print(f"  FAIL  {name:20} missing from .env")
            failures += 1
            continue
        ok, detail = probe(name, key)
        if ok:
            status = "OK  "
        elif name == "BLS_API_KEY":
            # Documented condition with a working keyless-v1 fallback, so not a
            # blocker -- but counted separately. Folding it into the OK total
            # printed "6/6 usable" directly beneath a visible WARN, which
            # teaches the reader to stop believing the total.
            status, warnings = "WARN", warnings + 1
        else:
            status, failures = "FAIL", failures + 1
        print(f"  {status}  {name:20} {detail}   [{sources.get(name, '?')}]")

    healthy = len(targets) - failures - warnings
    summary = f"\n  {healthy}/{len(targets)} fully working"
    if warnings:
        summary += f", {warnings} degraded but usable"
    if failures:
        summary += f", {failures} need attention"
    print(summary)
    print("\n  Nothing here is printed with a key in it. If you pasted a wrong")
    print("  value, re-run for that one key with --only <NAME>.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
