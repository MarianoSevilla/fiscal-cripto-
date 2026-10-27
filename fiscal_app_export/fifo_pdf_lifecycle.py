"""Short-lived FIFO PDF files; no provider, database or user-data dependencies.

Only files whose names carry our dedicated prefix are eligible for scavenging.
A periodic best-effort sweep while a web worker is alive complements per-request
sweeps. Storage remains ephemeral: no promise of a hard deletion SLA after
worker shutdown or filesystem failure.
"""
import logging
import os
import re
import stat
import tempfile
import threading
import time

PDF_PREFIX = "fifo_report_"
PDF_TTL_SECONDS = 300
_SWEEP_INTERVAL_SECONDS = 60
_OWNED_PDF_RE = re.compile(r"^fifo_report_[a-zA-Z0-9_-]+\.pdf(?:\.claimed)?$")
_started = False
_start_lock = threading.Lock()
_logger = logging.getLogger(__name__)


def purge_expired_pdfs(*, directory=None, now=None):
    """Remove only this application's expired PDF files (including crash claims).

    Symlinks and unrelated temporary files are never removed. Missing files and
    races with concurrent download/cleanup workers are harmless.
    """
    root = directory if directory is not None else tempfile.gettempdir()
    now = time.time() if now is None else now
    removed = 0
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                if not _OWNED_PDF_RE.fullmatch(entry.name):
                    continue
                try:
                    mode_and_time = entry.stat(follow_symlinks=False)
                    if not stat.S_ISREG(mode_and_time.st_mode):
                        continue
                    if now - mode_and_time.st_mtime < PDF_TTL_SECONDS:
                        continue
                    os.unlink(entry.path)
                    removed += 1
                except FileNotFoundError:
                    pass
                except OSError:
                    _logger.warning("fifo_pdf_cleanup_entry_failed")
    except OSError:
        _logger.warning("fifo_pdf_cleanup_scan_failed")
    return removed


def start_pdf_reaper():
    """Start at most one daemon scavenger per process, without extra services."""
    global _started
    with _start_lock:
        if _started:
            return
        worker = threading.Thread(
            name="fifo-pdf-expiry",
            target=_reap_loop,
            daemon=True,
        )
        worker.start()
        _started = True


def _reap_loop():
    while True:
        time.sleep(_SWEEP_INTERVAL_SECONDS)
        purge_expired_pdfs()


def write_private_pdf(path, pdf_bytes):
    """Create a 0600 PDF; never overwrite an existing report or leave partial data."""
    if not _OWNED_PDF_RE.fullmatch(os.path.basename(path)) or path.endswith(".claimed"):
        raise ValueError("Temporary FIFO report filename invalid")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(pdf_bytes)
    except BaseException:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    # Scavenging begins only after the completed PDF is available.
    purge_expired_pdfs()
    start_pdf_reaper()


def prepare_one_use_download(path, build_response):
    """Atomically claim a file, construct an in-memory response, then unlink it.

    The response receives bytes owned by its BytesIO, so the file cannot vanish
    mid-transfer. An error while reading/building restores the file for retry.
    Client disconnect after response commitment cannot be distinguished here.
    """
    claimed = path + ".claimed"
    os.rename(path, claimed)  # only one concurrent caller can claim this token
    try:
        with open(claimed, "rb") as stream:
            content = stream.read()
        response = build_response(content)
    except BaseException:
        try:
            os.replace(claimed, path)
        except OSError:
            _logger.warning("fifo_pdf_restore_failed")
        raise
    try:
        os.unlink(claimed)
    except OSError:
        _logger.warning("fifo_pdf_claim_cleanup_failed")
    return response
