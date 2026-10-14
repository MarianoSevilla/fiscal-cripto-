"""STG-B10P release switch: permanently DENIED in this preparatory PR.

This file may be packaged in an offline candidate image, but NO live Railway
deployment is authorized. The compiled constant is a literal False. There is
no environment flag, argument, magic token, or imported entrypoint that can
enable a real S01 database restore from this file.
"""
from __future__ import annotations

import sys

# Future approval requires an independently reviewed *source-code change*,
# a new immutable SHA, a green full CI, checked Railway inventory and the
# owner's separate authorization to write only Postgres-Im3h. This PR does
# not request, imply, or perform that change.
LIVE_RESTORE_RELEASED = False


class ReleaseDenied(RuntimeError):
    pass


def restore_release(env=None):
    if LIVE_RESTORE_RELEASED is not False:
        # Defensive against a malformed/nonbool constant in future changes.
        raise ReleaseDenied("INVALID_RELEASE_GATE")
    raise ReleaseDenied("REAL_RESTORE_NOT_AUTHORIZED")


def main() -> None:
    try:
        restore_release()
    except ReleaseDenied as exc:
        print("S01 STG-B10P: NO-GO (" + str(exc) + ")",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    print("S01 STG-B10P: NO-GO (FAIL_CLOSED)",
          file=sys.stderr, flush=True)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
