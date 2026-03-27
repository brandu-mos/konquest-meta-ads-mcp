"""
Greek Unicode Integrity Validator (Category F).

Validates Greek text before and after Meta API writes.
Detects mojibake, replacement characters, broken encoding,
and escaped Unicode sequences. Normalizes text to NFC.

This is a hard safety requirement - no Greek text reaches the
Meta API without passing through this validator.
"""
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("meta-ads-mcp.validators.greek_text")


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class TextIssue:
    """A single issue found during text validation."""
    severity: Severity
    message: str
    field_name: str = ""
    context: str = ""
    position: Optional[int] = None


@dataclass
class TextValidationResult:
    """Result of validating a text string."""
    original_text: str
    normalized_text: str
    field_name: str
    context: str
    is_safe: bool
    issues: list[TextIssue] = field(default_factory=list)

    @property
    def has_critical(self) -> bool:
        return any(i.severity == Severity.CRITICAL for i in self.issues)

    @property
    def has_high(self) -> bool:
        return any(i.severity == Severity.HIGH for i in self.issues)


@dataclass
class VerificationResult:
    """Result of post-write text verification."""
    status: str  # verified | text_integrity_failure
    mismatches: list[dict] = field(default_factory=list)
    action: str = ""  # block_and_report | none


# Greek Unicode ranges
GREEK_RANGE = re.compile(r'[\u0370-\u03ff\u1f00-\u1fff]')

# Mojibake detection patterns - common corruption signatures
MOJIBAKE_PATTERNS = [
    # Latin-1 misinterpreted as UTF-8 (very common on Windows)
    (re.compile(r'Î[±-ÿ]'), "Latin-1 decoded as UTF-8"),
    (re.compile(r'Î[\x91-\xbf]'), "Latin-1 decoded as UTF-8 (uppercase Greek)"),
    # Double-encoded UTF-8
    (re.compile(r'Ã[\x80-\xbf]'), "Double-encoded UTF-8"),
    (re.compile(r'Ã¢'), "Double-encoded UTF-8 (common)"),
    # Windows-1252 smart quotes via UTF-8
    (re.compile(r'â€[™\u201c\u201d\u0153\u201e]'), "Windows-1252 smart quotes"),
    # Escaped raw bytes in string
    (re.compile(r'\\xc[3-4][\x80-\xbf]'), "Raw escaped UTF-8 bytes"),
    # HTML entities that should have been decoded
    (re.compile(r'&(?:alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lambda|mu|nu|xi|omicron|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega);', re.IGNORECASE),
     "HTML entities for Greek characters"),
]

# Escaped Unicode sequences that should be real characters
ESCAPED_UNICODE_PATTERN = re.compile(r'\\u03[0-9a-fA-F]{2}')

# Replacement character
REPLACEMENT_CHAR = '\ufffd'

# Control characters (except common whitespace)
CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def contains_greek(text: str) -> bool:
    """Check if text contains any Greek characters."""
    return bool(GREEK_RANGE.search(text))


def validate_greek_text(
    text: str,
    field_name: str = "",
    context: str = "",
) -> TextValidationResult:
    """
    Validate Greek text integrity before any write operation.

    Checks:
    1. UTF-8 validity
    2. Mojibake detection (common corruption patterns)
    3. Replacement character detection (U+FFFD)
    4. Control character detection
    5. Escaped Unicode detection
    6. NFC normalization

    Args:
        text: The text to validate.
        field_name: Name of the field (e.g., 'primary_text', 'headline').
        context: Additional context (e.g., 'campaign creation for ExampleBrand').

    Returns:
        TextValidationResult with normalized text and any issues found.
    """
    issues: list[TextIssue] = []
    normalized = text

    # 1. UTF-8 validity check
    try:
        text.encode('utf-8').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError) as e:
        issues.append(TextIssue(
            severity=Severity.CRITICAL,
            message=f"Invalid UTF-8 encoding: {e}",
            field_name=field_name,
            context=context,
        ))
        return TextValidationResult(
            original_text=text,
            normalized_text=text,
            field_name=field_name,
            context=context,
            is_safe=False,
            issues=issues,
        )

    # 2. Mojibake detection
    for pattern, description in MOJIBAKE_PATTERNS:
        match = pattern.search(text)
        if match:
            issues.append(TextIssue(
                severity=Severity.CRITICAL,
                message=f"Mojibake detected ({description}): '{match.group()}' at position {match.start()}",
                field_name=field_name,
                context=context,
                position=match.start(),
            ))

    # 3. Replacement character detection
    if REPLACEMENT_CHAR in text:
        positions = [i for i, c in enumerate(text) if c == REPLACEMENT_CHAR]
        issues.append(TextIssue(
            severity=Severity.CRITICAL,
            message=f"Replacement character (U+FFFD) found at positions: {positions}",
            field_name=field_name,
            context=context,
            position=positions[0] if positions else None,
        ))

    # 4. Control character detection (only flag if mixed with Greek)
    if contains_greek(text):
        ctrl_match = CONTROL_CHARS.search(text)
        if ctrl_match:
            issues.append(TextIssue(
                severity=Severity.HIGH,
                message=f"Control character (0x{ord(ctrl_match.group()):02x}) mixed with Greek text at position {ctrl_match.start()}",
                field_name=field_name,
                context=context,
                position=ctrl_match.start(),
            ))

    # 5. Escaped Unicode detection (should be real characters, not \\u03xx)
    escaped_match = ESCAPED_UNICODE_PATTERN.search(text)
    if escaped_match:
        issues.append(TextIssue(
            severity=Severity.HIGH,
            message=f"Escaped Unicode sequence instead of real Greek character: '{escaped_match.group()}'",
            field_name=field_name,
            context=context,
            position=escaped_match.start(),
        ))

    # 6. NFC normalization
    normalized = unicodedata.normalize('NFC', text)
    if normalized != text:
        diff_positions = [i for i, (a, b) in enumerate(zip(text, normalized)) if a != b]
        issues.append(TextIssue(
            severity=Severity.INFO,
            message=f"Text normalized (NFC): {len(text)} -> {len(normalized)} chars, diffs at positions {diff_positions[:5]}",
            field_name=field_name,
            context=context,
        ))

    is_safe = not any(i.severity in (Severity.CRITICAL,) for i in issues)

    return TextValidationResult(
        original_text=text,
        normalized_text=normalized,
        field_name=field_name,
        context=context,
        is_safe=is_safe,
        issues=issues,
    )


def validate_payload_greek_text(
    payload: dict,
    context: str = "",
) -> list[TextValidationResult]:
    """
    Validate all text fields in a Meta API payload for Greek integrity.

    Scans all string values in the payload dict (including nested)
    and validates any that contain Greek characters.

    Returns a list of TextValidationResult for each Greek-containing field.
    """
    results = []

    def _scan(obj: any, prefix: str = ""):
        if isinstance(obj, str):
            if contains_greek(obj):
                result = validate_greek_text(obj, field_name=prefix, context=context)
                results.append(result)
        elif isinstance(obj, dict):
            for key, value in obj.items():
                _scan(value, prefix=f"{prefix}.{key}" if prefix else key)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _scan(item, prefix=f"{prefix}[{i}]")

    _scan(payload)
    return results


def verify_post_write_greek(
    intended_fields: dict[str, str],
    returned_fields: dict[str, str],
) -> VerificationResult:
    """
    Verify Greek text integrity after a Meta API write.

    Compares the intended text with what the API returned
    to detect corruption during transport.

    Args:
        intended_fields: Dict of field_name -> intended text value.
        returned_fields: Dict of field_name -> text value read back from API.

    Returns:
        VerificationResult with any mismatches found.
    """
    mismatches = []

    for field_name, intended_value in intended_fields.items():
        if not contains_greek(intended_value):
            continue

        returned_value = returned_fields.get(field_name, "")

        # Normalize both for comparison
        intended_norm = unicodedata.normalize('NFC', intended_value)
        returned_norm = unicodedata.normalize('NFC', returned_value)

        if intended_norm != returned_norm:
            # Classify the type of difference
            diff_type = _classify_text_diff(intended_norm, returned_norm)
            mismatches.append({
                "field": field_name,
                "intended": intended_value,
                "returned": returned_value,
                "diff_type": diff_type,
                "intended_length": len(intended_value),
                "returned_length": len(returned_value),
            })

    if mismatches:
        return VerificationResult(
            status="text_integrity_failure",
            mismatches=mismatches,
            action="block_and_report",
        )

    return VerificationResult(status="verified")


def _classify_text_diff(intended: str, returned: str) -> str:
    """Classify the type of text difference for diagnostics."""
    if not returned:
        return "field_empty_or_missing"

    if len(returned) > len(intended) * 1.5:
        return "possible_double_encoding"

    if len(returned) < len(intended) * 0.5:
        return "possible_truncation"

    # Check if it's a mojibake issue
    for pattern, description in MOJIBAKE_PATTERNS:
        if pattern.search(returned):
            return f"mojibake_{description.replace(' ', '_').lower()}"

    if REPLACEMENT_CHAR in returned:
        return "replacement_characters_inserted"

    # Check for accent/diacritic differences
    intended_base = ''.join(c for c in unicodedata.normalize('NFD', intended) if unicodedata.category(c) != 'Mn')
    returned_base = ''.join(c for c in unicodedata.normalize('NFD', returned) if unicodedata.category(c) != 'Mn')
    if intended_base == returned_base:
        return "diacritic_difference"

    return "unknown_corruption"


def sanitize_for_log(text: str, max_length: int = 200) -> str:
    """
    Sanitize text for logging, preserving Greek characters safely.

    Truncates if needed and ensures the output is safe for log files.
    """
    # Normalize first
    text = unicodedata.normalize('NFC', text)
    # Remove control characters
    text = CONTROL_CHARS.sub('', text)
    # Truncate
    if len(text) > max_length:
        text = text[:max_length] + "..."
    return text
