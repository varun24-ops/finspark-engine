from __future__ import annotations


class FinSparkError(Exception):
    """Base error for user-facing pipeline failures."""


class DocumentProcessingError(FinSparkError):
    """Raised when an uploaded document cannot be read safely."""


class BRDParsingError(FinSparkError):
    """Raised when a BRD cannot be parsed into service requirements."""


class RegistryValidationError(FinSparkError):
    """Raised when the adapter registry cannot satisfy a request."""


class ConfigGenerationError(FinSparkError):
    """Raised when config generation fails."""


class PolicyValidationError(FinSparkError):
    """Raised when config policy validation cannot be completed."""


class SimulationEngineError(FinSparkError):
    """Raised when simulation input is invalid or execution cannot continue."""


class HealingError(FinSparkError):
    """Raised when the self-healing loop cannot run."""
