"""Runtime and model configuration for the Ivyago desktop assistant.

The default configuration describes the validated embedded runtime only. Ollama
exists as an explicit developer/reference choice and is never selected by
default, never configured with a remote host, and never used as a fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

from .. import paths

# Model artifact validated by the Phase 2 compatibility gate.
VALIDATED_MODEL_NAME = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
VALIDATED_MODEL_BYTE_SIZE = 1_117_320_736
VALIDATED_MODEL_SHA256 = (
    "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e"
)
MODEL_DISPLAY_NAME = "Qwen2.5 1.5B Instruct (Q4_K_M)"

# Desktop context window. The compatibility gate validated the runtime at 1024;
# the model supports 32768. 3072 balances prompt room against CPU time on the
# target machine and stays inside the approved 2048-4096 band.
DEFAULT_CONTEXT_SIZE = 3072
MIN_CONTEXT_SIZE = 2048
MAX_CONTEXT_SIZE = 4096

DEFAULT_MAX_TOKENS = 384
MAX_ALLOWED_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.2
DEFAULT_TOP_P = 0.95
DEFAULT_REPEAT_PENALTY = 1.05

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


class ProviderKind(str, Enum):
    """Which local provider implementation the composition should build."""

    EMBEDDED = "embedded"
    OLLAMA_REFERENCE = "ollama_reference"


@dataclass(frozen=True)
class GenerationSettings:
    """Bounded, deterministic sampling values used for every local request."""

    context_size: int = DEFAULT_CONTEXT_SIZE
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = DEFAULT_TEMPERATURE
    top_p: float = DEFAULT_TOP_P
    repeat_penalty: float = DEFAULT_REPEAT_PENALTY
    n_threads: int | None = None

    def __post_init__(self) -> None:
        if not MIN_CONTEXT_SIZE <= self.context_size <= MAX_CONTEXT_SIZE:
            raise ValueError(
                "context_size must be between "
                f"{MIN_CONTEXT_SIZE} and {MAX_CONTEXT_SIZE}: {self.context_size}"
            )
        if not 1 <= self.max_tokens <= MAX_ALLOWED_MAX_TOKENS:
            raise ValueError(
                f"max_tokens must be between 1 and {MAX_ALLOWED_MAX_TOKENS}: "
                f"{self.max_tokens}"
            )
        if not 0.0 <= self.temperature <= 1.5:
            raise ValueError(f"temperature out of range: {self.temperature}")
        if not 0.0 < self.top_p <= 1.0:
            raise ValueError(f"top_p out of range: {self.top_p}")
        if not 0.5 <= self.repeat_penalty <= 2.0:
            raise ValueError(f"repeat_penalty out of range: {self.repeat_penalty}")
        if self.n_threads is not None and self.n_threads < 1:
            raise ValueError(f"n_threads must be positive: {self.n_threads}")


@dataclass(frozen=True)
class RuntimeConfig:
    """Complete, immutable description of the local assistant runtime."""

    provider: ProviderKind = ProviderKind.EMBEDDED
    model_path: Path = field(
        default_factory=lambda: paths.model_file(VALIDATED_MODEL_NAME)
    )
    expected_byte_size: int | None = VALIDATED_MODEL_BYTE_SIZE
    expected_sha256: str | None = VALIDATED_MODEL_SHA256
    model_name: str = MODEL_DISPLAY_NAME
    generation: GenerationSettings = field(default_factory=GenerationSettings)
    ollama_base_url: str | None = None
    ollama_model: str | None = None

    def __post_init__(self) -> None:
        if self.expected_sha256 is not None:
            digest = self.expected_sha256.lower()
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("expected_sha256 must be a 64-character hex digest")
            object.__setattr__(self, "expected_sha256", digest)

        if self.expected_byte_size is not None and self.expected_byte_size < 0:
            raise ValueError("expected_byte_size must not be negative")

        if self.provider is ProviderKind.EMBEDDED:
            if self.ollama_base_url is not None or self.ollama_model is not None:
                raise ValueError(
                    "The embedded provider has no network endpoint; "
                    "Ollama settings require ProviderKind.OLLAMA_REFERENCE"
                )
            return

        # Explicit reference mode: localhost only, and a model must be named.
        if not self.ollama_base_url:
            raise ValueError(
                "The Ollama reference provider requires an explicit localhost URL"
            )
        host = urlparse(self.ollama_base_url).hostname
        if host not in LOCAL_HOSTS:
            raise ValueError(
                f"The Ollama reference provider is localhost-only: {self.ollama_base_url!r}"
            )
        if not self.ollama_model:
            raise ValueError(
                "The Ollama reference provider requires an explicit model name"
            )


def default_runtime_config() -> RuntimeConfig:
    """Return the packaged default: the validated embedded runtime."""

    return RuntimeConfig()


def ollama_reference_config(
    model: str,
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
) -> RuntimeConfig:
    """Return an explicit developer/reference configuration (localhost only)."""

    return RuntimeConfig(
        provider=ProviderKind.OLLAMA_REFERENCE,
        ollama_base_url=base_url,
        ollama_model=model,
    )
