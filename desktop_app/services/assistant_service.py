"""Desktop assistant-service facade for Ivyago Phase 3.

This module is the ONLY desktop-facing assistant behaviour facade. It connects
the existing offline pipeline (``keyword_detector`` routing/ranking and the
``query_layer`` prompt/output-safety policy) to the Phase 2 local provider
boundary, without importing Ollama, ``query_layer.answer()``, an HTTP client, a
provider runtime, Qt, or any widget.

Two things it deliberately does NOT do:

  * It never calls ``query_layer.answer()`` -- that function owns an
    Ollama-specific model call. Generation belongs to the provider.
  * It never touches a widget or the Qt thread. The controller runs
    ``prepare_request`` / ``finalize_response`` on a worker thread.

The pure prompt/cleanup/fallback rules are reused (not copied) via
``query_layer.prompt_policy``, a stdlib-only extraction shared with the legacy
CLI so the safety-critical behaviour has a single source of truth.

Import discipline: this module imports only the standard library plus
``desktop_app.models`` at load time. The legacy modules
(``query_layer.prompt_policy`` and ``keyword_detector.keywords``) are imported
lazily inside the default callables, so importing the contracts below never
pulls the detector, the databases, or the prompt policy into a process that
only needs the types.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields
from typing import Protocol, runtime_checkable

from ..models import (
    SOURCE_EMERGENCY_NUMBER_REFERENCE_USED,
    SOURCE_IDENTIFIERS,
    SOURCE_LOCAL_REFERENCE_UNAVAILABLE,
    SOURCE_LOCAL_REFERENCE_USED,
    SOURCE_OFFLINE_ASSISTANT,
    SOURCE_LABELS,
)

# Re-exported so callers can import the identifiers from the service contract.
__all__ = [
    "AssistantRequest",
    "PreparedAssistantRequest",
    "AssistantResponse",
    "AssistantService",
    "DefaultAssistantService",
    "DetectorFn",
    "SystemPromptFn",
    "UserPromptFn",
    "ResponsePolicyFn",
    "SOURCE_OFFLINE_ASSISTANT",
    "SOURCE_LOCAL_REFERENCE_USED",
    "SOURCE_EMERGENCY_NUMBER_REFERENCE_USED",
    "SOURCE_LOCAL_REFERENCE_UNAVAILABLE",
    "SOURCE_IDENTIFIERS",
    "SOURCE_LABELS",
]

# Detector routes that can carry relevant local reference rows. A general
# question never receives reference context.
_REFERENCE_ROUTES = frozenset({"body_symptoms", "medicines", "emergency_numbers"})


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AssistantRequest:
    """One user submission: identity plus the visible prompt text only."""

    request_id: str
    user_text: str


@dataclass(frozen=True)
class PreparedAssistantRequest:
    """Detector output, prompts, and internal reference rows for one request.

    The provider receives only ``system_prompt`` and ``user_prompt``. Reference
    rows stay inside the service object and are never handed to the UI as raw
    database rows.
    """

    request: AssistantRequest
    system_prompt: str
    user_prompt: str
    route: str
    severity: str
    matched_keywords: tuple[str, ...]
    db_results: tuple[Mapping[str, object], ...]
    critical_override: bool
    reference_available: bool


@dataclass(frozen=True)
class AssistantResponse:
    """The finalized, cleaned answer plus quiet source metadata."""

    text: str
    route: str
    severity: str
    source: str
    matched_keywords: tuple[str, ...]
    db_results_used: int
    critical_override: bool
    reference_available: bool


@runtime_checkable
class AssistantService(Protocol):
    """The desktop-facing assistant behaviour contract."""

    def prepare_request(
        self,
        request: AssistantRequest,
    ) -> PreparedAssistantRequest: ...

    def finalize_response(
        self,
        prepared: PreparedAssistantRequest,
        generated_text: str,
    ) -> AssistantResponse: ...


# Injectable collaborators. Defaults reuse the existing pipeline lazily.
DetectorFn = Callable[[str], Mapping[str, object]]
SystemPromptFn = Callable[[str], str]
UserPromptFn = Callable[[str, Sequence[Mapping[str, object]], str], str]
ResponsePolicyFn = Callable[[PreparedAssistantRequest, str], AssistantResponse]


# ---------------------------------------------------------------------------
# Default collaborators (lazy imports of the shared offline policy)
# ---------------------------------------------------------------------------


def _default_detector(user_text: str) -> Mapping[str, object]:
    """Route one message through the existing keyword detector, exactly once."""
    from keyword_detector.keywords import run  # lazy: stdlib + sqlite only

    return run(user_text)


def _default_system_prompt(severity: str) -> str:
    from query_layer.prompt_policy import build_system_prompt  # lazy, stdlib

    return build_system_prompt(severity)


def _default_user_prompt(
    user_text: str,
    db_results: Sequence[Mapping[str, object]],
    route: str,
) -> str:
    from query_layer.prompt_policy import build_user_prompt  # lazy, stdlib

    return build_user_prompt(user_text, list(db_results), route)


_NUMBER_FIELDS = ("police", "ambulance", "fire")
_SERVICE_ALIASES = {
    "police": ("police",),
    "ambulance": ("ambulance", "medical emergency", "medical emergencies"),
    "fire": ("fire", "fire brigade", "fire department"),
}
_MISSING_NUMBER_VALUES = frozenset(
    {"", "n/a", "na", "none", "-", "--", "not available"}
)


def _verified_number(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in _MISSING_NUMBER_VALUES else text


def _value_in_text(value: str, text: str) -> bool:
    """Match a verified value without accepting it as part of another number."""
    if not value:
        return False
    if value.isdigit():
        return re.search(r"(?<!\d)" + re.escape(value) + r"(?!\d)", text) is not None
    return value.lower() in text.lower()


def _service_mentions(text: str) -> set[str]:
    lowered = (text or "").lower()
    return {
        service
        for service, aliases in _SERVICE_ALIASES.items()
        if any(alias in lowered for alias in aliases)
    }


def _service_value_is_associated(service: str, value: str, segment: str) -> bool:
    """Require a nearby service/value pair without another service in between."""
    if not value:
        return False

    lowered = segment.lower()
    aliases = _SERVICE_ALIASES[service]
    other_aliases = tuple(
        alias
        for other_service, service_aliases in _SERVICE_ALIASES.items()
        if other_service != service
        for alias in service_aliases
    )
    service_pattern = "(?:" + "|".join(re.escape(alias) for alias in aliases) + ")"
    service_matches = list(re.finditer(service_pattern, lowered))
    if value.isdigit():
        value_matches = list(
            re.finditer(r"(?<!\d)" + re.escape(value) + r"(?!\d)", lowered)
        )
    else:
        value_matches = list(re.finditer(re.escape(value.lower()), lowered))

    for service_match in service_matches:
        for value_match in value_matches:
            if abs(service_match.start() - value_match.start()) > 32:
                continue
            between_start = min(service_match.end(), value_match.end())
            between_end = max(service_match.start(), value_match.start())
            between = lowered[between_start:between_end]
            if any(alias in between for alias in other_aliases):
                continue
            return True
    return False


def _cites_verified_number(
    text: str,
    db_results: Sequence[Mapping[str, object]],
    user_text: str = "",
) -> bool:
    """True when emergency numbers are grounded and service labels agree.

    A bare verified number is accepted only when the user asked for a specific
    service and that service's value appears. If the answer names services, each
    named service must be paired with its own verified value in the same line or
    sentence. This prevents output such as ``police 112`` when 112 is actually
    the ambulance value in the selected row.
    """
    answer = (text or "").strip()
    if not answer or not db_results:
        return False

    row = db_results[0]
    verified = {
        field: _verified_number(row.get(field, "")) for field in _NUMBER_FIELDS
    }
    available = {field for field, value in verified.items() if value}
    if not available:
        return False

    answer_services = _service_mentions(answer)
    user_services = _service_mentions(user_text)
    requested_services = user_services & available

    # Explicitly named services in the generated answer must each carry their
    # own verified number. Split on lines and sentence boundaries so separate
    # entries such as ``Police: 15`` / ``Ambulance: 112`` remain valid.
    if answer_services:
        segments = [
            segment.strip()
            for segment in re.split(r"[\n.!?;]+", answer)
            if segment.strip()
        ]
        for service in answer_services:
            aliases = _SERVICE_ALIASES[service]
            service_segments = [
                segment
                for segment in segments
                if any(alias in segment.lower() for alias in aliases)
            ]
            if not service_segments:
                return False
            if not any(
                _service_value_is_associated(service, verified[service], segment)
                for segment in service_segments
            ):
                return False
        return True

    # If the answer uses only a bare number, honor the user's requested service
    # rather than accepting a different service's number by coincidence.
    if requested_services:
        return any(_value_in_text(verified[service], answer)
                   for service in requested_services)

    # Generic country-wide answers may cite any verified service number.
    return any(_value_in_text(value, answer) for value in verified.values())


def _source_for_reference(route: str) -> str:
    if route == "emergency_numbers":
        return SOURCE_EMERGENCY_NUMBER_REFERENCE_USED
    return SOURCE_LOCAL_REFERENCE_USED


# ---------------------------------------------------------------------------
# Concrete implementation
# ---------------------------------------------------------------------------


class DefaultAssistantService:
    """The packaged assistant service: existing detector + prompt policy.

    Synchronous and UI-independent. The controller is responsible for running
    both methods off the Qt thread.
    """

    def __init__(
        self,
        detector: DetectorFn | None = None,
        system_prompt_builder: SystemPromptFn | None = None,
        user_prompt_builder: UserPromptFn | None = None,
        response_policy: ResponsePolicyFn | None = None,
    ) -> None:
        self._detector: DetectorFn = (
            detector if detector is not None else _default_detector
        )
        self._system_prompt_builder: SystemPromptFn = (
            system_prompt_builder
            if system_prompt_builder is not None
            else _default_system_prompt
        )
        self._user_prompt_builder: UserPromptFn = (
            user_prompt_builder
            if user_prompt_builder is not None
            else _default_user_prompt
        )
        # ``None`` selects the built-in validation/fallback policy below.
        self._response_policy = response_policy

    # -- preparation -----------------------------------------------------

    def prepare_request(self, request: AssistantRequest) -> PreparedAssistantRequest:
        detection = self._safe_detect(request.user_text)

        route = str(detection.get("route") or "general")
        severity = str(detection.get("severity_hint") or "UNKNOWN")
        critical_override = bool(detection.get("critical_override", False))
        raw_matched = detection.get("matched_keywords")
        matched = (
            tuple(str(k) for k in raw_matched)
            if isinstance(raw_matched, Sequence)
            and not isinstance(raw_matched, (str, bytes))
            else ()
        )

        raw_rows = detection.get("db_results")
        rows = (
            tuple(r for r in raw_rows if isinstance(r, Mapping))
            if isinstance(raw_rows, Sequence)
            and not isinstance(raw_rows, (str, bytes))
            else ()
        )

        # Reference context is injected only for the routes the detector ranks
        # rows for. A general (or unknown) question never receives reference
        # context, whatever a detector returned: unrelated rows must never be
        # injected as an answer.
        if route not in _REFERENCE_ROUTES:
            rows = ()

        system_prompt = self._system_prompt_builder(severity)
        user_prompt = self._user_prompt_builder(request.user_text, rows, route)
        reference_available = bool(rows)

        return PreparedAssistantRequest(
            request=request,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            route=route,
            severity=severity,
            matched_keywords=matched,
            db_results=rows,
            critical_override=critical_override,
            reference_available=reference_available,
        )

    # -- finalization ----------------------------------------------------

    def finalize_response(
        self,
        prepared: PreparedAssistantRequest,
        generated_text: str,
    ) -> AssistantResponse:
        policy = self._response_policy
        if policy is not None:
            return policy(prepared, generated_text)
        return self._default_finalize(prepared, generated_text)

    # -- internals -------------------------------------------------------

    def _safe_detect(self, user_text: str) -> Mapping[str, object]:
        """Call the detector once; a failure degrades to a safe general route."""
        try:
            result = self._detector(user_text)
        except Exception as exc:  # pragma: no cover - defensive detector failure
            # Recorded outside the user-visible response, as the spec requires.
            print("[WARN] detector failed; continuing as general: %s" % exc)
            return {}
        if not isinstance(result, Mapping):
            return {}
        return result

    def _default_finalize(
        self,
        prepared: PreparedAssistantRequest,
        generated_text: str,
    ) -> AssistantResponse:
        from query_layer.prompt_policy import (
            _ECHO_SAFE_REPLY,
            _EMPTY_REPLY,
            _echoes_prompt,
            _inverts_safety_verdict,
            _looks_degenerate,
            build_db_fallback,
            clean_response,
        )

        user_text = prepared.request.user_text
        route = prepared.route
        db_results = list(prepared.db_results)
        ref_avail = prepared.reference_available

        # Preserve the existing validation order.
        cleaned = clean_response(generated_text or "")
        echoed = _echoes_prompt(cleaned)
        empty = cleaned == _EMPTY_REPLY
        degenerate = _looks_degenerate(cleaned)
        inverted = _inverts_safety_verdict(user_text, db_results, route, cleaned)

        # Emergency-number grounding: the answer must actually cite a verified
        # number from the selected country row, or it is replaced by the
        # verified fallback below.
        grounded = True
        if route == "emergency_numbers" and db_results:
            grounded = _cites_verified_number(cleaned, db_results, user_text)

        unusable = echoed or empty or degenerate or inverted or not grounded

        if unusable:
            db_fallback = build_db_fallback(db_results, route) if db_results else ""
            if db_fallback:
                text = db_fallback
                source = _source_for_reference(route)
                used = len(db_results)
            else:
                text = _ECHO_SAFE_REPLY
                used = 0
                # The route wanted a reference but none was available.
                source = (
                    SOURCE_LOCAL_REFERENCE_UNAVAILABLE
                    if route in _REFERENCE_ROUTES and not db_results
                    else SOURCE_OFFLINE_ASSISTANT
                )
        else:
            text = cleaned
            if ref_avail and route in _REFERENCE_ROUTES:
                source = _source_for_reference(route)
                used = len(db_results)
            else:
                source = SOURCE_OFFLINE_ASSISTANT
                used = 0

        return AssistantResponse(
            text=text,
            route=route,
            severity=prepared.severity,
            source=source,
            matched_keywords=prepared.matched_keywords,
            db_results_used=used,
            critical_override=prepared.critical_override,
            reference_available=ref_avail,
        )


def contract_field_names() -> frozenset[str]:
    """Return the declared field names of each frozen contract.

    Used by contract tests to guarantee the contracts carry only prompt/metadata
    values and never a database connection, widget, or provider handle.
    """
    names: set[str] = set()
    for cls in (AssistantRequest, PreparedAssistantRequest, AssistantResponse):
        names.update(f.name for f in fields(cls))
    return frozenset(names)
