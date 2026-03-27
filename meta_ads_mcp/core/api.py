"""
Core API layer for Meta Graph API access.

Provides both facebook-business SDK access and raw HTTP fallback
for endpoints the SDK doesn't cover. Handles rate limit monitoring,
error classification, and appsecret_proof generation.

Graph API version: v24.0
"""
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Optional

import httpx
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.exceptions import FacebookRequestError

logger = logging.getLogger("meta-ads-mcp.api")

GRAPH_API_VERSION = "v24.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Rate limit thresholds
RATE_LIMIT_WARN_PCT = 80
RATE_LIMIT_BLOCK_PCT = 95


class MetaAPIError(Exception):
    """Structured error from Meta Graph API."""

    def __init__(self, message: str, error_code: int = 0, error_subcode: int = 0,
                 error_type: str = "", fbtrace_id: str = "", is_transient: bool = False):
        super().__init__(message)
        self.error_code = error_code
        self.error_subcode = error_subcode
        self.error_type = error_type
        self.fbtrace_id = fbtrace_id
        self.is_transient = is_transient


class RateLimitStatus:
    """Tracks rate limit usage from response headers."""

    def __init__(self):
        self.app_usage: dict = {}
        self.business_usage: dict = {}
        self.ad_account_usage: dict = {}
        self.last_updated: float = 0

    def update_from_headers(self, headers: dict):
        """Extract rate limit info from Meta API response headers."""
        self.last_updated = time.time()

        for header_name, attr_name in [
            ("x-app-usage", "app_usage"),
            ("x-business-use-case-usage", "business_usage"),
            ("x-ad-account-usage", "ad_account_usage"),
        ]:
            raw = headers.get(header_name)
            if raw:
                try:
                    setattr(self, attr_name, json.loads(raw))
                except json.JSONDecodeError:
                    pass

    @property
    def max_usage_pct(self) -> float:
        """Return the highest usage percentage across all rate limit categories."""
        max_pct = 0.0
        for usage in [self.app_usage, self.ad_account_usage]:
            if isinstance(usage, dict):
                for key in ("call_count", "total_cputime", "total_time"):
                    val = usage.get(key, 0)
                    if isinstance(val, (int, float)) and val > max_pct:
                        max_pct = val
        return max_pct

    @property
    def is_warning(self) -> bool:
        return self.max_usage_pct >= RATE_LIMIT_WARN_PCT

    @property
    def is_critical(self) -> bool:
        return self.max_usage_pct >= RATE_LIMIT_BLOCK_PCT


class MetaAPIClient:
    """
    Unified client for Meta Graph API access.

    Provides:
    - facebook-business SDK initialization and access
    - Raw HTTP client for endpoints the SDK doesn't cover
    - Rate limit monitoring
    - appsecret_proof generation
    - Error classification
    """

    def __init__(self):
        self._sdk_initialized = False
        self._http_client: Optional[httpx.Client] = None
        self._access_token: Optional[str] = None
        self._app_secret: Optional[str] = None
        self._app_id: Optional[str] = None
        self.rate_limits = RateLimitStatus()

    def initialize(self):
        """Initialize API client from environment variables."""
        self._access_token = os.environ.get("META_ACCESS_TOKEN")
        self._app_secret = os.environ.get("META_APP_SECRET")
        self._app_id = os.environ.get("META_APP_ID")

        if not self._access_token:
            raise MetaAPIError("META_ACCESS_TOKEN environment variable is not set", error_code=-1)

        # Initialize facebook-business SDK
        FacebookAdsApi.init(
            app_id=self._app_id or "",
            app_secret=self._app_secret or "",
            access_token=self._access_token,
            api_version=GRAPH_API_VERSION,
        )
        self._sdk_initialized = True

        # Initialize HTTP client for raw API calls
        self._http_client = httpx.Client(
            base_url=GRAPH_API_BASE,
            timeout=60.0,
            headers={"Accept": "application/json"},
        )

        logger.info("Meta API client initialized (SDK + HTTP), API version %s", GRAPH_API_VERSION)

    @property
    def is_initialized(self) -> bool:
        return self._sdk_initialized

    def _ensure_initialized(self):
        if not self._sdk_initialized:
            self.initialize()

    def _generate_appsecret_proof(self) -> Optional[str]:
        """Generate appsecret_proof via HMAC-SHA256 for added security."""
        if self._app_secret and self._access_token:
            return hmac.new(
                self._app_secret.encode("utf-8"),
                self._access_token.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
        return None

    def _build_params(self, params: Optional[dict] = None) -> dict:
        """Build request parameters with token and optional appsecret_proof."""
        result = {"access_token": self._access_token}
        proof = self._generate_appsecret_proof()
        if proof:
            result["appsecret_proof"] = proof
        if params:
            result.update(params)
        return result

    def get_ad_account(self, account_id: str) -> AdAccount:
        """Get an AdAccount SDK object for the given account ID."""
        self._ensure_initialized()
        if not account_id.startswith("act_"):
            account_id = f"act_{account_id}"
        return AdAccount(account_id)

    def graph_get(self, endpoint: str, params: Optional[dict] = None, fields: Optional[list] = None) -> dict:
        """
        Make a GET request to the Graph API via raw HTTP.

        Use this for endpoints not covered by the facebook-business SDK.
        """
        self._ensure_initialized()
        request_params = self._build_params(params)
        if fields:
            request_params["fields"] = ",".join(fields)

        response = self._http_client.get(endpoint, params=request_params)
        self.rate_limits.update_from_headers(dict(response.headers))

        if self.rate_limits.is_warning:
            logger.warning("Rate limit usage at %.1f%% - approaching limit", self.rate_limits.max_usage_pct)

        if response.status_code != 200:
            self._handle_http_error(response)

        return response.json()

    def graph_post(self, endpoint: str, data: Optional[dict] = None,
                   params: Optional[dict] = None, json_body: Optional[dict] = None) -> dict:
        """
        Make a POST request to the Graph API via raw HTTP.

        For write operations. Always uses JSON body for safe Greek text transport.
        """
        self._ensure_initialized()
        request_params = self._build_params(params)

        if json_body:
            # Safe path for Greek text - use JSON body
            response = self._http_client.post(
                endpoint,
                params=request_params,
                json=json_body,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
        elif data:
            response = self._http_client.post(endpoint, params=request_params, data=data)
        else:
            response = self._http_client.post(endpoint, params=request_params)

        self.rate_limits.update_from_headers(dict(response.headers))

        if response.status_code != 200:
            self._handle_http_error(response)

        return response.json()

    def _handle_http_error(self, response: httpx.Response):
        """Parse and raise structured API error."""
        try:
            body = response.json()
            error = body.get("error", {})
            raise MetaAPIError(
                message=error.get("message", f"HTTP {response.status_code}"),
                error_code=error.get("code", response.status_code),
                error_subcode=error.get("error_subcode", 0),
                error_type=error.get("type", ""),
                fbtrace_id=error.get("fbtrace_id", ""),
                is_transient=error.get("is_transient", False),
            )
        except (json.JSONDecodeError, KeyError):
            raise MetaAPIError(
                message=f"HTTP {response.status_code}: {response.text[:500]}",
                error_code=response.status_code,
            )

    def handle_sdk_error(self, error: FacebookRequestError) -> MetaAPIError:
        """Convert SDK error to our structured error type."""
        return MetaAPIError(
            message=error.api_error_message() or str(error),
            error_code=error.api_error_code() or 0,
            error_subcode=error.api_error_subcode() or 0,
            error_type=error.api_error_type() or "",
            fbtrace_id=error.api_transient_error() or "",
            is_transient=bool(error.api_transient_error()),
        )

    def check_token_health(self) -> dict:
        """Verify token validity and permissions."""
        self._ensure_initialized()
        try:
            result = self.graph_get("/me", fields=["id", "name"])
            return {
                "status": "valid",
                "user_id": result.get("id"),
                "user_name": result.get("name"),
                "rate_limit_usage_pct": self.rate_limits.max_usage_pct,
            }
        except MetaAPIError as e:
            if e.error_code in (190, 102):
                return {"status": "expired", "error": str(e)}
            return {"status": "error", "error": str(e)}


# Module-level singleton
api_client = MetaAPIClient()
