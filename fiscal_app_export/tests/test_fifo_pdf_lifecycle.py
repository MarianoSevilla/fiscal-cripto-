"""SEC5-PDF: synthetic tests for private temporary reports and safe cleanup."""
import io
import os
import stat
import time

import pytest

from fifo_pdf_lifecycle import (
    PDF_PREFIX,
    PDF_TTL_SECONDS,
    prepare_one_use_download,
    purge_expired_pdfs,
    write_private_pdf,
)


def _new_pdf(tmp_path, name="fifo_report_synthetic.pdf", content=b"%PDF-synthetic"):
    path = tmp_path / name
    path.write_bytes(content)
    return path


def test_writer_uses_private_permissions_and_never_overwrites(tmp_path):
    path = tmp_path / (PDF_PREFIX + "private.pdf")
    write_private_pdf(str(path), b"%PDF-private")
    assert path.read_bytes() == b"%PDF-private"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        write_private_pdf(str(path), b"%PDF-overwrite")
    assert path.read_bytes() == b"%PDF-private"


def test_cleaner_removes_expired_own_files_but_not_other_files(tmp_path):
    expired = _new_pdf(tmp_path)
    stale_claim = _new_pdf(tmp_path, "fifo_report_crash.pdf.claimed")
    fresh = _new_pdf(tmp_path, "fifo_report_fresh.pdf")
    other_pdf = _new_pdf(tmp_path, "other_application.pdf")
    neighboring_csv = tmp_path / "fifo_report_input.csv"
    neighboring_csv.write_text("synthetic", encoding="utf-8")
    now = time.time()
    for path in (expired, stale_claim, other_pdf, neighboring_csv):
        os.utime(path, (now - PDF_TTL_SECONDS - 10,) * 2)
    assert purge_expired_pdfs(directory=str(tmp_path), now=now) == 2
    assert not expired.exists()
    assert not stale_claim.exists()
    assert fresh.exists()
    assert other_pdf.exists()
    assert neighboring_csv.exists()


def test_cleaner_skips_symlink_even_if_matching_name(tmp_path):
    target = _new_pdf(tmp_path, "unrelated_document.pdf")
    link = tmp_path / "fifo_report_link.pdf"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are not supported on this environment")
    now = time.time()
    os.utime(target, (now - PDF_TTL_SECONDS - 10,) * 2)
    assert purge_expired_pdfs(directory=str(tmp_path), now=now) == 0
    assert link.is_symlink()
    assert target.exists()


def test_one_use_download_is_independent_of_file_during_slow_delivery(tmp_path):
    path = _new_pdf(tmp_path)
    # Build the response before removing the file. The returned buffer can be
    # delivered much later, even though the source and claim no longer exist.
    payload = prepare_one_use_download(str(path), lambda data: io.BytesIO(data))
    assert not path.exists()
    assert not (tmp_path / (path.name + ".claimed")).exists()
    assert payload.read() == b"%PDF-synthetic"
    with pytest.raises(FileNotFoundError):
        prepare_one_use_download(str(path), lambda data: data)


def test_failure_while_building_response_preserves_original_for_retry(tmp_path):
    path = _new_pdf(tmp_path)
    def fail(_data):
        raise OSError("synthetic response preparation error")
    with pytest.raises(OSError):
        prepare_one_use_download(str(path), fail)
    assert path.read_bytes() == b"%PDF-synthetic"
    assert not (tmp_path / (path.name + ".claimed")).exists()
    assert prepare_one_use_download(str(path), lambda data: data) == b"%PDF-synthetic"


def test_only_original_token_can_claim_file_once(tmp_path):
    path = _new_pdf(tmp_path)
    def concurrent_attempt(data):
        with pytest.raises(FileNotFoundError):
            prepare_one_use_download(str(path), lambda _: b"unexpected")
        return data
    assert prepare_one_use_download(str(path), concurrent_attempt) == b"%PDF-synthetic"


def test_invalid_name_never_created(tmp_path):
    for unsafe in ("other.pdf", "fifo_report_no_pdf.txt", "fifo_report_fake.pdf.claimed"):
        path = tmp_path / unsafe
        with pytest.raises(ValueError):
            write_private_pdf(str(path), b"payload")
        assert not path.exists()
