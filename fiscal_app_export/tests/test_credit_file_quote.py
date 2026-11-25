from io import BytesIO
import zipfile

import pytest
from werkzeug.datastructures import FileStorage

from credit_file_quote import inspect_credit_uploads


def _upload(content, name):
    return FileStorage(stream=BytesIO(content), filename=name)


def test_fingerprint_ignores_filenames_and_csv_order():
    one = b"Date,Symbol,Amount\n2025-01-01,BTC,1\n"
    two = b"Date,Symbol,Amount\n2025-02-01,ETH,2\n"
    first = inspect_credit_uploads([_upload(one, "first.csv"), _upload(two, "second.csv")])
    second = inspect_credit_uploads([_upload(two, "renamed-b.csv"), _upload(one, "renamed-a.csv")])
    assert first["fingerprint"] == second["fingerprint"]
    assert first["rows"] == second["rows"] == 2


def test_same_csv_set_in_zip_has_same_content_fingerprint():
    one = b"Date,Symbol,Amount\n2025-01-01,BTC,1\n"
    two = b"Date,Symbol,Amount\n2025-02-01,ETH,2\n"
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("one.csv", one)
        zf.writestr("two.csv", two)
    from_csvs = inspect_credit_uploads([_upload(one, "one.csv"), _upload(two, "two.csv")])
    from_zip = inspect_credit_uploads([_upload(archive.getvalue(), "history.zip")])
    assert from_csvs["fingerprint"] == from_zip["fingerprint"]
    assert from_csvs["files"] == from_zip["files"] == 2


@pytest.mark.parametrize("content,name", [
    (b"", "empty.csv"),
    (b"not a zip", "broken.zip"),
    (b"synthetic workbook", "history.xlsx"),
])
def test_invalid_credit_preflight_fails_closed(content, name):
    with pytest.raises(ValueError):
        inspect_credit_uploads([_upload(content, name)])
