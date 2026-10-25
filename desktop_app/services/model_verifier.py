"""Local model-file resolution and integrity verification.

A GGUF artifact is never trusted just because a file exists: the desktop app
checks the expected byte size and SHA-256 recorded by the compatibility gate
before the runtime is allowed to open it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .. import paths
from .model_provider import ModelCorruptError, ModelMissingError
from .runtime_config import RuntimeConfig

HASH_CHUNK_SIZE = 4 * 1024 * 1024


@dataclass(frozen=True)
class ModelMetadata:
    """Verified identity of a local model artifact."""

    path: Path
    byte_size: int
    sha256: str


def resolve_model_path(config: RuntimeConfig) -> Path:
    """Return the absolute model path for ``config``.

    Relative paths resolve against the application root rather than the current
    working directory so launching from a shortcut behaves like launching from
    the repository.
    """

    path = Path(config.model_path)
    if not path.is_absolute():
        path = paths.project_root() / path
    return path


def sha256_file(path: Path, chunk_size: int = HASH_CHUNK_SIZE) -> str:
    """Hash a file in chunks so a 1.12 GB artifact is never held in memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model_file(
    path: Path,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> ModelMetadata:
    """Validate a model file and return its verified metadata.

    Raises ``ModelMissingError`` when the path does not exist and
    ``ModelCorruptError`` for a directory, an unreadable file, an empty file, a
    size mismatch, or a checksum mismatch.
    """

    candidate = Path(path)
    if not candidate.exists():
        raise ModelMissingError(f"Model file not found: {candidate}")
    if not candidate.is_file():
        raise ModelCorruptError(f"Model path is not a file: {candidate}")

    try:
        byte_size = candidate.stat().st_size
    except OSError as exc:
        raise ModelCorruptError(
            f"Model file could not be inspected: {candidate}"
        ) from exc

    if byte_size == 0:
        raise ModelCorruptError(f"Model file is empty: {candidate}")

    if expected_size is not None and byte_size != expected_size:
        raise ModelCorruptError(
            f"Model size mismatch: expected {expected_size} bytes, found {byte_size}"
        )

    try:
        digest = sha256_file(candidate)
    except PermissionError as exc:
        raise ModelCorruptError(
            f"Model file is not readable: {candidate}"
        ) from exc
    except OSError as exc:
        raise ModelCorruptError(f"Model file could not be read: {candidate}") from exc

    if expected_sha256 is not None and digest != expected_sha256.lower():
        raise ModelCorruptError("Model checksum does not match the validated artifact")

    return ModelMetadata(path=candidate, byte_size=byte_size, sha256=digest)


def verify_configured_model(config: RuntimeConfig) -> ModelMetadata:
    """Convenience wrapper: resolve and verify the configured model artifact."""

    return verify_model_file(
        resolve_model_path(config),
        expected_size=config.expected_byte_size,
        expected_sha256=config.expected_sha256,
    )
