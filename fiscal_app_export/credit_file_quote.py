"""Read-only upload preflight used to bind a credit quote to the exact files."""
import hashlib
import io
import zipfile


MAX_UNPACKED_BYTES = 100 * 1024 * 1024
MAX_CSV_MEMBERS = 100


def inspect_credit_uploads(files):
    """Return physical CSV rows, parsed CSV count and content fingerprint.

    ZIP members are read in memory and never extracted. XLS/XLSX and unknown
    formats fail closed in the first credits pilot. Existing free tools keep
    their independent format behavior.
    """
    files = [f for f in (files or []) if getattr(f, "filename", "")]
    if not files:
        raise ValueError("Selecciona al menos un archivo CSV o ZIP.")
    file_hashes = []
    rows = members = unpacked_total = 0
    for upload in files:
        name = upload.filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        raw = upload.stream.read()
        upload.stream.seek(0)
        if not raw:
            raise ValueError("Hay un archivo vacío. Corrígelo antes de cotizar.")
        suffix = name.lower().rsplit(".", 1)[-1] if "." in name else ""
        if suffix == "csv":
            file_hashes.append(hashlib.sha256(raw).digest())
            rows += _count_physical_rows(raw)
            members += 1
        elif suffix == "zip":
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    candidates = [x for x in archive.infolist()
                                  if not x.is_dir() and x.filename.lower().endswith(".csv")]
                    if not candidates:
                        raise ValueError("El ZIP no contiene CSV compatibles.")
                    if len(candidates) + members > MAX_CSV_MEMBERS:
                        raise ValueError("El ZIP incluye demasiados CSV para el piloto.")
                    for info in candidates:
                        unpacked_total += info.file_size
                        if unpacked_total > MAX_UNPACKED_BYTES:
                            raise ValueError("El ZIP supera el tamaño descomprimido admitido.")
                        with archive.open(info) as stream:
                            content = stream.read(MAX_UNPACKED_BYTES + 1)
                        if len(content) != info.file_size:
                            raise ValueError("No se ha podido validar un CSV del ZIP.")
                        file_hashes.append(hashlib.sha256(content).digest())
                        rows += _count_physical_rows(content)
                        members += 1
            except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
                raise ValueError("El ZIP está dañado o no se puede leer.") from exc
        else:
            raise ValueError("El piloto de créditos admite CSV y ZIP con CSV; este formato no está disponible aún.")
    if members > MAX_CSV_MEMBERS:
        raise ValueError("Se han seleccionado demasiados CSV para cotizar.")
    digest = hashlib.sha256(b"fifo-credit-csv-content-v1\0")
    digest.update(len(file_hashes).to_bytes(4, "big"))
    for file_hash in sorted(file_hashes):
        digest.update(file_hash)
    return {"rows": rows, "files": members, "fingerprint": digest.hexdigest()}


def _count_physical_rows(raw: bytes) -> int:
    # Mirrors the existing FIFO physical-line counter. It is a quotation
    # measure only, not a statement about recognized fiscal operations.
    text = raw.decode("utf-8-sig", "replace")
    return max(0, sum(1 for _ in io.StringIO(text)) - 1)
