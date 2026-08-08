"""Response package: excerpt assembly, confidence thresholds, validation.

Every field in a ResponsePackage must trace back verbatim (or near-verbatim
excerpt) to a source chunk. No synthesis.
"""

from app.response.package_builder import build_response_package, ResponsePackage
from app.response.confidence_thresholds import ConfidenceLevel, route_by_confidence
from app.response.validation import validate_package

__all__ = [
    "build_response_package",
    "ResponsePackage",
    "ConfidenceLevel",
    "route_by_confidence",
    "validate_package",
]
