"""Guardas de subida para el importador Binance multifuente.

Binance entrega sus exportaciones como ZIP. Este módulo extrae únicamente CSV
con límites explícitos, sin confiar en rutas internas del ZIP y sin persistir
los ZIP originales más allá de la petición.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import zipfile
from pathlib import PurePosixPath
from typing import Iterable, List, Tuple


class BinanceUploadError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.category = "user_error"


def _safe_member_name(name: str) -> str:
    if not name or "\x00" in name:
        raise BinanceUploadError("unsafe_zip", "El ZIP de Binance contiene una ruta no válida.")
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
        raise BinanceUploadError(
            "unsafe_zip",
            "El ZIP de Binance contiene carpetas o rutas no permitidas. "
            "Descárgalo de nuevo directamente desde Binance.",
        )
    if not normalized.lower().endswith(".csv"):
        raise BinanceUploadError(
            "zip_non_csv",
            "El ZIP de Binance contiene archivos que no son CSV.",
        )
    return path.name


def save_binance_uploads(
    uploads: Iterable,
    *,
    prefix: str = "fifo_",
    max_uploads: int = 20,
    max_csv_files: int = 40,
    max_member_bytes: int = 10 * 1024 * 1024,
    max_total_bytes: int = 50 * 1024 * 1024,
    max_ratio: int = 200,
) -> Tuple[List[str], List[str]]:
    """Guarda CSV o extrae ZIP Binance en temporales seguros.

    Devuelve (rutas_temporales_csv, nombres_lógicos). Los nombres lógicos
    preservan el nombre de exportación solo dentro de la petición para detectar
    el offset UTC; no se incorporan a los cálculos fiscales.
    """
    uploads = list(uploads or [])
    if not uploads:
        raise BinanceUploadError("no_files", "No se recibió ningún archivo de Binance.")
    if len(uploads) > max_uploads:
        raise BinanceUploadError(
            "too_many_uploads",
            f"Demasiados archivos. Máximo {max_uploads} CSV/ZIP por análisis.",
        )

    tmp_csvs: List[str] = []
    logical_names: List[str] = []
    tmp_zips: List[str] = []
    seen_hashes: set[str] = set()
    total_bytes = 0
    csv_count = 0

    def store_bytes(data: bytes, logical_name: str) -> None:
        nonlocal total_bytes, csv_count
        if len(data) > max_member_bytes:
            raise BinanceUploadError(
                "csv_too_large",
                "Uno de los CSV de Binance supera el máximo permitido de 10 MB.",
            )
        total_bytes += len(data)
        if total_bytes > max_total_bytes:
            raise BinanceUploadError(
                "bundle_too_large",
                "Los archivos de Binance descomprimidos superan el máximo permitido.",
            )
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen_hashes:
            raise BinanceUploadError(
                "duplicate_file",
                "Has añadido dos veces el mismo CSV de Binance. Elimina el duplicado y vuelve a intentarlo.",
            )
        seen_hashes.add(digest)
        csv_count += 1
        if csv_count > max_csv_files:
            raise BinanceUploadError(
                "too_many_csv",
                f"Los ZIP contienen demasiados CSV. Máximo {max_csv_files}.",
            )
        with tempfile.NamedTemporaryFile(prefix=prefix, suffix=".csv", delete=False) as out:
            out.write(data)
            tmp_csvs.append(out.name)
            logical_names.append(logical_name)

    try:
        for upload in uploads:
            original = (getattr(upload, "filename", "") or "").strip()
            lower = original.lower()
            if lower.endswith(".csv"):
                # FileStorage.read() puede estar disponible; save() es más universal.
                with tempfile.NamedTemporaryFile(prefix=prefix, suffix=".csv", delete=False) as tmp:
                    upload.save(tmp.name)
                    direct_path = tmp.name
                try:
                    with open(direct_path, "rb") as fh:
                        data = fh.read(max_member_bytes + 1)
                finally:
                    try:
                        os.unlink(direct_path)
                    except OSError:
                        pass
                store_bytes(data, original or "binance.csv")
                continue

            if not lower.endswith(".zip"):
                raise BinanceUploadError(
                    "unsupported_extension",
                    "Binance admite archivos .csv y los .zip descargados directamente desde Binance.",
                )

            with tempfile.NamedTemporaryFile(prefix=prefix, suffix=".zip", delete=False) as tmp:
                upload.save(tmp.name)
                zip_path = tmp.name
                tmp_zips.append(zip_path)

            try:
                with zipfile.ZipFile(zip_path) as zf:
                    infos = [i for i in zf.infolist() if not i.is_dir()]
                    if not infos:
                        raise BinanceUploadError("empty_zip", "El ZIP de Binance está vacío.")
                    for info in infos:
                        member = _safe_member_name(info.filename)
                        if info.file_size > max_member_bytes:
                            raise BinanceUploadError(
                                "zip_member_too_large",
                                "Un CSV del ZIP de Binance supera el máximo permitido de 10 MB.",
                            )
                        if (info.file_size > 1024 * 1024
                                and info.file_size / max(info.compress_size, 1) > max_ratio):
                            raise BinanceUploadError(
                                "zip_ratio",
                                "El ZIP de Binance tiene una relación de compresión no segura.",
                            )
                        with zf.open(info, "r") as fh:
                            data = fh.read(max_member_bytes + 1)
                        if len(data) != info.file_size:
                            raise BinanceUploadError(
                                "zip_size_mismatch",
                                "No se pudo verificar el tamaño de un CSV del ZIP de Binance.",
                            )
                        store_bytes(data, f"{original}::{member}")
            except zipfile.BadZipFile as exc:
                raise BinanceUploadError(
                    "invalid_zip",
                    "El archivo ZIP no es válido. Descárgalo de nuevo desde Binance.",
                ) from exc

        return tmp_csvs, logical_names
    except Exception:
        for path in tmp_csvs:
            try:
                os.unlink(path)
            except OSError:
                pass
        raise
    finally:
        for path in tmp_zips:
            try:
                os.unlink(path)
            except OSError:
                pass
