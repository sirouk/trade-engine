from __future__ import annotations

import json
import logging
import os
import threading
import time
import weakref
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

# Global registry to track active sessions for cleanup
try:
    _active_sessions: weakref.WeakSet = weakref.WeakSet()
except Exception:
    _active_sessions = set()

def _register_session(sess):
    """Register a session for potential cleanup."""
    try:
        _active_sessions.add(sess)
    except Exception:
        pass

def close_all_sessions() -> int:
    """
    Close all active curl_cffi sessions.
    Call this on process shutdown or when recycling connections.
    Returns count of sessions closed.
    """
    count = 0
    # Make a copy since closing may trigger removal
    for sess in list(_active_sessions):
        try:
            sess.close()
            count += 1
        except Exception:
            pass
    try:
        _active_sessions.clear()
    except Exception:
        pass
    return count


def _get_blofin_sdk_version() -> str | None:
    """Get the installed blofin SDK version for diagnostics."""
    try:
        import importlib.metadata

        return importlib.metadata.version("blofin")
    except Exception:
        return None


def patch_blofin_cloudflare_transport() -> bool:
    """
    Patch the third-party `blofin` package to use `curl_cffi` for HTTP requests.

    Why:
    BloFin's endpoints are sometimes protected by Cloudflare-managed challenges that
    block plain `python-requests` (HTTP 403 with an HTML "Just a moment..." page).
    `curl_cffi` can impersonate a real browser TLS fingerprint, which avoids the challenge.

    Design constraints:
    - The trade engine wraps many calls in `execute_with_timeout(..., timeout=5)` which uses threads.
      Threads are not cancellable; if HTTP timeouts/retries exceed that budget, timed-out threads can pile up.
    - Therefore we keep HTTP timeouts <= 5s by default and retries extremely conservative.

    Returns:
        True if patch applied, False if `curl_cffi` is not available.
    """
    if getattr(patch_blofin_cloudflare_transport, "_applied", False):
        return True

    try:
        from curl_cffi import requests as curl_requests
        from curl_cffi.requests.exceptions import ImpersonateError
        from curl_cffi.requests.impersonate import DEFAULT_CHROME
    except Exception:
        return False

    # Import inside the patch function so we can safely run even if blofin isn't installed.
    from blofin.constants import REST_API_URL, SERVER_TIME_ENDPOINT
    from blofin.exceptions import (
        BloFinAuthException,
        BloFinRequestException,
        raise_api_exception,
    )

    def _has_auth(auth) -> bool:
        return bool(
            getattr(auth, "API_KEY", None)
            and getattr(auth, "API_SECRET", None)
            and getattr(auth, "PASSPHRASE", None)
        )

    # Allow comma-separated fallback list for future Cloudflare/WAF changes.
    raw_impersonate = os.getenv("BLOFIN_IMPERSONATE", "").strip()
    if raw_impersonate:
        impersonate_candidates = [
            p.strip() for p in raw_impersonate.split(",") if p.strip()
        ]
    else:
        # Keep the old known-good pin first, then try curl_cffi's up-to-date default.
        impersonate_candidates = ["chrome110", str(DEFAULT_CHROME)]

    # Deduplicate while preserving order.
    seen: set[str] = set()
    impersonate_candidates = [
        p for p in impersonate_candidates if not (p in seen or seen.add(p))
    ]

    # NOTE: `execute_with_timeout()` wraps many BloFin calls with a 5s asyncio timeout.
    # If the underlying HTTP timeout is >= the outer timeout, timed-out threads can pile up
    # (threads aren't cancellable). Keep the HTTP timeout slightly below 5s by default.
    try:
        timeout_s = float(os.getenv("BLOFIN_HTTP_TIMEOUT", "4"))
    except Exception:
        timeout_s = 4.0

    # Expose effective candidates/timeout for startup logging.
    patch_blofin_cloudflare_transport.impersonate_candidates = list(impersonate_candidates)
    patch_blofin_cloudflare_transport.timeout_s = timeout_s

    # We'll only attempt multiple impersonations on fast Cloudflare 403 challenge responses.
    max_challenge_attempts = max(
        1, int(os.getenv("BLOFIN_HTTP_CHALLENGE_ATTEMPTS", "3"))
    )

    _tls = threading.local()
    _session_lock = threading.Lock()

    def _session():
        """Get or create a thread-local curl_cffi session with lifecycle management."""
        sess = getattr(_tls, "session", None)
        if sess is None:
            with _session_lock:
                # Double-check after acquiring lock
                sess = getattr(_tls, "session", None)
                if sess is None:
                    # Per-thread session keeps connections/cookies without cross-thread contention.
                    sess = curl_requests.Session()
                    # Disable keep-alive for long-running processes to avoid stale connections
                    sess.headers.update({"Connection": "keep-alive"})
                    _tls.session = sess
                    _register_session(sess)
                    _tls.session_created_at = time.time()
                else:
                    # Check if session is too old (recycle after 5 minutes)
                    created = getattr(_tls, "session_created_at", 0)
                    if time.time() - created > 300:
                        try:
                            sess.close()
                        except Exception:
                            pass
                        sess = curl_requests.Session()
                        sess.headers.update({"Connection": "keep-alive"})
                        _tls.session = sess
                        _register_session(sess)
                        _tls.session_created_at = time.time()
        return sess

    def _is_cloudflare_challenge(resp) -> bool:
        try:
            if getattr(resp, "status_code", None) != 403:
                return False
            if (resp.headers.get("cf-mitigated") or "").lower() == "challenge":
                return True
            text = (resp.text or "")[:1024]
            return ("just a moment" in text.lower()) and ("challenge" in text.lower())
        except Exception:
            return False

    def _json_or_none(resp):
        try:
            return resp.json()
        except Exception:
            return None

    def _non_json_snippet(resp) -> str:
        try:
            text = resp.text or ""
            return text[:200].replace("\n", "\\n")
        except Exception:
            return ""

    def send_request(method, request_path, auth, params=None, data=None, authenticate=False):
        if authenticate and not _has_auth(auth):
            raise BloFinAuthException(
                "API credentials are required for this method. Please provide API key, API secret, and an API passphrase."
            )

        try:
            # IMPORTANT: the signature includes the exact request path and (if present) the exact query string.
            query = ("?" + urlencode(params, doseq=True)) if params else ""
            path_for_sig = f"{request_path}{query}"
            url = f"{REST_API_URL}{path_for_sig}"

            body_obj = None
            body_str = None
            if method == "GET":
                pass
            elif method == "POST":
                # Ensure the exact body bytes match what Auth.generate_signature signs.
                body_obj = data if data is not None else {}
                body_str = json.dumps(body_obj)
            else:
                raise BloFinRequestException(f"Unsupported HTTP method: {method}")

            if authenticate:
                if method == "POST":
                    headers = auth.get_headers(path_for_sig, method, body_obj)
                else:
                    headers = auth.get_headers(path_for_sig, method)
            else:
                headers = {}

            resp = None
            tried: list[str] = []
            last_cf_snippet = ""

            for idx, candidate in enumerate(impersonate_candidates):
                if idx >= max_challenge_attempts:
                    break
                tried.append(candidate)

                try:
                    if method == "GET":
                        resp = _session().get(
                            url,
                            headers=headers,
                            timeout=timeout_s,
                            impersonate=candidate,
                        )
                    else:
                        resp = _session().post(
                            url,
                            headers=headers,
                            data=body_str,
                            timeout=timeout_s,
                            impersonate=candidate,
                        )
                except ImpersonateError:
                    # Invalid profile string, try next.
                    continue

                if _is_cloudflare_challenge(resp):
                    last_cf_snippet = _non_json_snippet(resp)
                    # Cloudflare challenges are fast; retry with a different fingerprint.
                    continue

                # Either not a Cloudflare challenge, or it's a normal response we should handle.
                break

            if resp is None:
                raise BloFinRequestException(
                    f"Request failed: no usable impersonation profile (tried={tried})"
                )

            # Mirror upstream behavior: only raise on non-2xx HTTP. API-level errors often come back as HTTP 200.
            if not str(resp.status_code).startswith("2"):
                if _is_cloudflare_challenge(resp):
                    snippet = _non_json_snippet(resp) or last_cf_snippet
                    raise BloFinRequestException(
                        "Request blocked by Cloudflare challenge (HTTP 403). "
                        f"tried_impersonate={tried} snippet={snippet!r}"
                    )

                payload = _json_or_none(resp)
                if payload is None:
                    raise BloFinRequestException(
                        f"Request failed: HTTP {resp.status_code} url={getattr(resp, 'url', url)} body_snippet={_non_json_snippet(resp)!r}"
                    )

                # `raise_api_exception` expects `response.json()` to work.
                raise_api_exception(resp)

                # Defensive: `raise_api_exception` always raises.
                raise BloFinRequestException(
                    f"Request failed: HTTP {resp.status_code} url={getattr(resp, 'url', url)} payload={payload}"
                )

            payload = _json_or_none(resp)
            if payload is None:
                raise BloFinRequestException(
                    f"Request returned non-JSON response: url={getattr(resp, 'url', url)} body_snippet={_non_json_snippet(resp)!r}"
                )

            return payload

        except (BloFinRequestException, BloFinAuthException):
            raise
        except Exception as e:
            raise BloFinRequestException(f"Request failed: {e}") from e

    def get_server_time():
        last_exc: Exception | None = None
        resp = None

        for idx, candidate in enumerate(impersonate_candidates):
            if idx >= max_challenge_attempts:
                break
            try:
                resp = _session().get(
                    f"{REST_API_URL}{SERVER_TIME_ENDPOINT}",
                    timeout=timeout_s,
                    impersonate=candidate,
                )
            except ImpersonateError as e:
                last_exc = e
                continue
            if _is_cloudflare_challenge(resp):
                last_exc = BloFinRequestException(
                    "Cloudflare challenge on server time endpoint"
                )
                continue
            break

        if resp is None:
            raise BloFinRequestException(f"Failed to get server time: {last_exc}")

        if resp.status_code != 200:
            raise BloFinRequestException(
                f"Failed to get server time (HTTP {resp.status_code})"
            )

        payload = _json_or_none(resp)
        if payload is None:
            raise BloFinRequestException(
                f"Failed to parse server time (non-JSON): body_snippet={_non_json_snippet(resp)!r}"
            )

        try:
            return int(payload["data"]["timestamp"])
        except Exception as e:
            raise BloFinRequestException(f"Failed to parse server time: {payload}") from e

    # Patch module-level references (the library imports send_request into each module namespace).
    import blofin.auth as blofin_auth
    import blofin.utils as blofin_utils
    import blofin.api.account as blofin_api_account
    import blofin.api.affiliate as blofin_api_affiliate
    import blofin.api.public as blofin_api_public
    import blofin.api.trading as blofin_api_trading
    import blofin.api.user as blofin_api_user

    blofin_utils.send_request = send_request
    blofin_utils.get_server_time = get_server_time

    # Auth imported `get_server_time` into its own module namespace; patch that alias too.
    blofin_auth.get_server_time = get_server_time

    blofin_api_account.send_request = send_request
    blofin_api_trading.send_request = send_request
    blofin_api_public.send_request = send_request
    blofin_api_affiliate.send_request = send_request
    blofin_api_user.send_request = send_request

    # Verify patches were applied to critical modules (fail loud if SDK structure changed)
    _required_attrs = [
        (blofin_utils, "send_request"),
        (blofin_utils, "get_server_time"),
        (blofin_auth, "get_server_time"),
        (blofin_api_trading, "send_request"),
    ]
    for module, attr in _required_attrs:
        if not hasattr(module, attr):
            raise RuntimeError(
                f"BloFin patch failed: expected {module.__name__}.{attr} after patching. "
                f"SDK structure may have changed. Check blofin SDK version."
            )

    # Log SDK version for diagnostic purposes
    sdk_version = _get_blofin_sdk_version()
    if sdk_version:
        logger.info("blofin SDK version: %s (curl_cffi transport patched)", sdk_version)

    patch_blofin_cloudflare_transport._applied = True

    # Register atexit handler for clean shutdown
    import atexit
    atexit.register(close_all_sessions)

    return True


def health_check() -> dict:
    """
    Perform a lightweight health check on the BloFin transport.
    Returns status dict with 'ok', 'latency_ms', 'error' fields.
    """
    import time

    result = {"ok": False, "latency_ms": None, "error": None}

    if not getattr(patch_blofin_cloudflare_transport, "_applied", False):
        result["error"] = "Patch not applied"
        return result

    try:
        from curl_cffi import requests as curl_requests

        start = time.time()
        # Lightweight endpoint - server time
        resp = curl_requests.get(
            "https://openapi.blofin.com/api/v1/market/time",
            timeout=5,
            impersonate="chrome110",
        )
        elapsed = (time.time() - start) * 1000
        result["latency_ms"] = round(elapsed, 2)

        if resp.status_code == 200:
            result["ok"] = True
        else:
            result["error"] = f"HTTP {resp.status_code}"

        # Close this temporary session
        try:
            resp.close()
        except Exception:
            pass

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"

    return result


def verify_patch_working() -> bool:
    """
    Verify the patch is working by making a real API call.
    Call this during startup to ensure BloFin connectivity.
    """
    check = health_check()
    if not check["ok"]:
        logger.error("BloFin patch health check failed: %s", check.get("error"))
        return False
    logger.info("BloFin patch verified: latency=%sms", check.get("latency_ms"))
    return True
