"""Shared constants for external recipient validation."""

from __future__ import annotations

EXTERNAL_VALIDATION_DISABLED = "none"
NEVERBOUNCE_SERVICE = "neverbounce"
NEVERBOUNCE_API_KEY = "NEVERBOUNCE_API_KEY"

VALIDATION_STAGE_RESEARCH = "research"
VALIDATION_STAGE_SEND = "send"
EXTERNAL_VALIDATION_STAGES = (VALIDATION_STAGE_RESEARCH, VALIDATION_STAGE_SEND)
EXTERNAL_VALIDATION_SERVICES = (NEVERBOUNCE_SERVICE, EXTERNAL_VALIDATION_DISABLED)


def normalize_validation_stage(value: str) -> str:
    """Normalize the configured external-validation timing value."""
    return value.strip().lower()


def normalize_validation_service(value: str) -> str:
    """Normalize the configured external-validation service value."""
    return value.strip().lower()
