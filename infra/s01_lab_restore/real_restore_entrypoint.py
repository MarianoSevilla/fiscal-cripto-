"""S01 B10R — exact restore entrypoint, RELEASE HARD-DISABLED in this PR.

IMPORTANT: this module is packaged in the B10R *candidate* image for
synthetic acceptance only. A future distinct SHA, reviewed CI and owner's
specific consent must precede any release that writes Postgres-Im3h.
"""
from __future__ import annotations

import os
import sys

import restore_candidate

# NOT an environment-controlled switch. This exact source SHA cannot run DDL.
LIVE_RESTORE_AUTHORIZED_IN_SOURCE = False


class EntryDenied(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def entrypoint(*, env=None, worker=restore_candidate.restore_once) -> str:
    """Production-shape entrypoint with deliberate unconditional NO-GO.

    The work function is injected for synthetic contract tests. It is not
    called until an independently authorized *source change* is reviewed.
    """
    if LIVE_RESTORE_AUTHORIZED_IN_SOURCE is not False:
        raise EntryDenied("SOURCE_GATE_TAMPERED")
    raise EntryDenied("AWAITING_SEPARATE_RESTORE_AUTHORIZATION")


def main() -> None:
    try:
        status = entrypoint(env=dict(os.environ))
    except EntryDenied as exc:
        print("S01 STG-B10R: NO-GO (" + exc.code + ")",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    except Exception:
        # A future release may call a DB/S3 client. Never leak DSN, SQL
        # or credentials through the host log.
        print("S01 STG-B10R: NO-GO (REDACTED_ERROR)",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    # Defensive deny even if an injected worker ever returns success.
    print("S01 STG-B10R: NO-GO (INCONSISTENT_RELEASE)",
          file=sys.stderr, flush=True)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
