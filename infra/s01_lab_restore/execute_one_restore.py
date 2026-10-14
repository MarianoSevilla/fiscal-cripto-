"""STG-B10S: real-capable restore entrypoint, NOT DEPLOYED to Railway.

Two-step deployment security:
1. Source SHA must be reviewed + pinned in Railway to this exact build.
2. This script rejects execution unless the *separately set* manual approval
   variable equals the exact nonsecret operation identifier.
B10S preparation does not set that variable or redeploy this image.

Any authorized invocation targets ONLY pinned Postgres-Im3h and its S3 archive
via the independently reviewed restore_candidate.restore_once().
"""
from __future__ import annotations

import os
import sys

import restore_candidate

# Nonsecret exact intent string; NOT a credential. A human-approved deployment
# must provide this explicitly by a future Railway variable action.
APPROVAL_KEY = "S01_RECOVERY_WRITE_APPROVAL"
APPROVAL_INTENT = (
    "ONE-RESTORE:POSTGRES-IM3H:7696517018472497211:"
    "1af6ba229c781a7cc0b357610119d546c4a47bcce5a2b19442a11501ea3afdab"
)


class ReleaseDenied(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def validate_release(env):
    # Check authorization BEFORE touching PostgreSQL or S3. No alternative
    # keys, generic 'true', or inferred consent.
    if env.get(APPROVAL_KEY) != APPROVAL_INTENT:
        raise ReleaseDenied("EXPLICIT_ONE_RESTORE_APPROVAL_MISSING")
    try:
        restore_candidate.validate_configuration(env)
    except restore_candidate.RestoreDenied as exc:
        raise ReleaseDenied("INVALID_PINNED_LAB_" + exc.code) from None
    # Once set the preconditions are still checked fresh by restore_once.
    return True


def execute_approved(env, *, restore_fn=restore_candidate.restore_once):
    validate_release(env)
    return restore_fn(env)


def main():
    try:
        result = execute_approved(dict(os.environ))
        if result != "RESTORE_VERIFIED_INDEPENDENT_RECOVERY_CLUSTER":
            raise ReleaseDenied("UNEXPECTED_POSTRESTORE_RESULT")
    except ReleaseDenied as exc:
        print("S01 STG-B10S: NO-GO (" + exc.code + ")",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    except restore_candidate.RestoreDenied as exc:
        # Codes have no URLs, passwords, original DDL, or row data.
        print("S01 STG-B10S: NO-GO (" + exc.code + ")",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    except Exception:
        # Never reveal S3/PSQL tracebacks in deployment logs.
        print("S01 STG-B10S: NO-GO (REDACTED_ERROR)",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    print("S01 STG-B10S: PASS (ONE authorized restore of verified archive;"
          " target PG18 cluster 7696517018472497211;"
          " postflight pristine; source untouched by executor)", flush=True)


if __name__ == "__main__":
    main()
