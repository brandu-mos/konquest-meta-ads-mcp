"""
Tests for Greek Unicode integrity validator.

Phase: v1.0 - these tests should pass immediately.
"""
import pytest
from meta_ads_mcp.validators.greek_text import (
    validate_greek_text,
    validate_payload_greek_text,
    verify_post_write_greek,
    contains_greek,
)


class TestContainsGreek:
    def test_greek_text(self):
        assert contains_greek("Ελληνικά") is True

    def test_english_text(self):
        assert contains_greek("English only") is False

    def test_mixed_text(self):
        assert contains_greek("Hello Κόσμε") is True

    def test_empty_text(self):
        assert contains_greek("") is False

    def test_greek_with_numbers(self):
        assert contains_greek("Τιμή: €15.00") is True


class TestValidateGreekText:
    def test_valid_greek(self):
        result = validate_greek_text("Αυθεντικό Φλερτ", field_name="headline")
        assert result.is_safe is True
        assert len([i for i in result.issues if i.severity.value == "critical"]) == 0

    def test_nfc_normalization(self):
        # Composed vs decomposed alpha with accent
        import unicodedata
        decomposed = unicodedata.normalize("NFD", "ά")  # alpha + combining accent
        result = validate_greek_text(decomposed, field_name="test")
        assert result.normalized_text == unicodedata.normalize("NFC", decomposed)

    def test_replacement_character(self):
        result = validate_greek_text("Ελληνικ\ufffdα", field_name="test")
        assert result.is_safe is False
        assert any("FFFD" in i.message for i in result.issues)

    def test_empty_string(self):
        result = validate_greek_text("", field_name="test")
        assert result.is_safe is True

    def test_escaped_unicode(self):
        result = validate_greek_text("text with \\u03b1 escaped", field_name="test")
        assert any("Escaped Unicode" in i.message for i in result.issues)

    def test_pure_english(self):
        result = validate_greek_text("No Greek here", field_name="test")
        assert result.is_safe is True


class TestValidatePayload:
    def test_nested_greek(self):
        payload = {
            "name": "Test Campaign",
            "adcreatives": {
                "body": "Μάθε περισσότερα",
                "title": "Αυθεντικό Φλερτ",
            }
        }
        results = validate_payload_greek_text(payload)
        assert len(results) == 2  # Two Greek fields found

    def test_no_greek_payload(self):
        payload = {"name": "English Campaign", "budget": "1500"}
        results = validate_payload_greek_text(payload)
        assert len(results) == 0

    def test_list_in_payload(self):
        payload = {
            "headlines": ["Πρώτο", "Δεύτερο", "Third"],
        }
        results = validate_payload_greek_text(payload)
        assert len(results) == 2  # Two Greek strings in list


class TestPostWriteVerification:
    def test_matching_text(self):
        result = verify_post_write_greek(
            intended_fields={"body": "Ελληνικά"},
            returned_fields={"body": "Ελληνικά"},
        )
        assert result.status == "verified"

    def test_mismatched_text(self):
        result = verify_post_write_greek(
            intended_fields={"body": "Ελληνικά"},
            returned_fields={"body": "Î•Î»Î»Î·Î½Î¹ÎºÎ¬"},
        )
        assert result.status == "text_integrity_failure"
        assert len(result.mismatches) == 1

    def test_empty_returned(self):
        result = verify_post_write_greek(
            intended_fields={"body": "Ελληνικά"},
            returned_fields={"body": ""},
        )
        assert result.status == "text_integrity_failure"

    def test_english_fields_skipped(self):
        result = verify_post_write_greek(
            intended_fields={"name": "English Name", "body": "Ελληνικά"},
            returned_fields={"name": "Different Name", "body": "Ελληνικά"},
        )
        assert result.status == "verified"  # Only Greek fields checked
