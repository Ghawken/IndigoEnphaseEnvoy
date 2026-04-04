# authorisation.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Indigo Enphase Token Authorisation

Supports two token-acquisition strategies:

  1. **PKCE OAuth flow** (preferred — from vincentwolsink HA installer integration)
     Mimics the Envoy web-UI login via ``entrez.enphaseenergy.com/login`` →
     local Envoy ``/auth/get_jwt``.  The *Envoy itself* mints the JWT so the
     ``enphaseUser`` claim correctly reflects the account type (installer vs owner).

  2. **pyenphase cloud flow** (fallback)
     ``enlighten.enphaseenergy.com/login/login.json`` →
     ``entrez.enphaseenergy.com/tokens``.  Kept as a fallback because some
     account configurations may not support the PKCE redirect.

Public API:
  - get_token(): returns a valid token; refreshes when near expiry or missing
  - refresh_token(): force refresh and validate token against local Envoy

Notes:
  - Requires ``pyenphase`` and ``aiohttp`` in the plugin environment.
  - Cloud token retrieval may fail if Enlighten MFA is enabled.
"""

from __future__ import annotations
from datetime import datetime
import asyncio
import base64
import hashlib
import logging
import secrets
import string
import time
from dataclasses import dataclass
from typing import Optional
from urllib import parse

import jwt  # PyJWT

import aiohttp
from pyenphase.auth import EnvoyTokenAuth
from pyenphase.ssl import NO_VERIFY_SSL_CONTEXT

# ── PKCE helpers (ported from vincentwolsink HA installer integration) ──

ENLIGHTEN_LOGIN_URL = "https://entrez.enphaseenergy.com/login"
ENDPOINT_URL_GET_JWT = "https://{}/auth/get_jwt"
ENDPOINT_URL_CHECK_JWT = "https://{}/auth/check_jwt"


def _random_content(length: int) -> str:
    """Return a random alphanumeric string of *length* characters."""
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def _generate_challenge(code: str) -> str:
    """Derive a PKCE code-challenge (S256) from *code*."""
    sha = hashlib.sha256(code.encode("utf-8")).digest()
    return (
        base64.b64encode(sha)
        .decode("utf-8")
        .replace("+", "-")
        .replace("/", "_")
        .replace("=", "")
    )


@dataclass
class TokenState:
    token: str
    exp_ts: int  # epoch seconds (0 if unknown)
    fetched_ts: int  # epoch seconds


class EnphaseTokenManager:
    """
    Sync wrapper for pyenphase EnvoyTokenAuth for Indigo.

    Typical usage from plugin.py:
        tm = EnphaseTokenManager(
            host=envoy_ip,
            cloud_username=user,
            cloud_password=pw,
            envoy_serial=serial,
            token=saved_token,
            logger=self.logger,
        )
        token = tm.get_token()
        if tm.did_refresh:
            # persist tm.token somewhere (pluginPrefs / deviceProps)
    """

    def __init__(
        self,
        host: str,
        cloud_username: Optional[str] = None,
        cloud_password: Optional[str] = None,
        envoy_serial: Optional[str] = None,
        token: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        refresh_margin_seconds: int = 7 * 24 * 3600,  # refresh if within 7 days of expiry
        timeout_seconds: int = 60,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.host = host
        self.cloud_username = cloud_username
        self.cloud_password = cloud_password
        self.envoy_serial = envoy_serial
        self.refresh_margin_seconds = int(refresh_margin_seconds)
        self.timeout_seconds = int(timeout_seconds)

        self.did_refresh: bool = False
        self.last_error: Optional[str] = None

        if EnvoyTokenAuth is None or aiohttp is None:
            raise RuntimeError(
                f"pyenphase/aiohttp not available: {_IMPORT_ERROR!r}. "
                "Install pyenphase + aiohttp into the Indigo plugin environment."
            )

        # pyenphase token auth object (async internally)
        self._auth = EnvoyTokenAuth(
            host=self.host,
            cloud_username=self.cloud_username,
            cloud_password=self.cloud_password,
            envoy_serial=self.envoy_serial,
            token=token,
        )

        # Local cached state (what plugin should persist)
        self._state: Optional[TokenState] = None
        if token:
            self._state = TokenState(token=token, exp_ts=self._jwt_exp_ts(token), fetched_ts=int(time.time()))

    # -------------------------
    # Public API
    # -------------------------

    @property
    def token(self) -> Optional[str]:
        return self._state.token if self._state else None

    @property
    def token_exp_ts(self) -> int:
        return self._state.exp_ts if self._state else 0

    def get_token(self, force_refresh: bool = False) -> str:
        """
        Return a valid token. Refreshes if:
          - force_refresh=True
          - no token present
          - token is expired or near expiry (within refresh_margin_seconds)
        """
        self.did_refresh = False
        self.last_error = None

        if force_refresh:
            self.logger.debug("get_token(force_refresh=True) -> refresh_token()")
            return self.refresh_token()

        # If we have a token and it is not near expiry, return it.
        if self._state and self._state.token:
            if self._token_is_valid_enough(self._state.exp_ts):
                self.logger.debug(
                    "Using cached token (exp_ts=%s, now=%s)",
                    self._state.exp_ts,
                    int(time.time()),
                )
                return self._state.token
            self.logger.info("Token is expired/near expiry -> attempting refresh")

        # Otherwise, attempt refresh
        return self.refresh_token()

    def refresh_token(self) -> str:
        """
        Force refresh the token from cloud and validate it against local Envoy.
        Raises on failure.
        """
        self.did_refresh = False
        self.last_error = None

        if not self.cloud_username or not self.cloud_password or not self.envoy_serial:
            raise ValueError(
                "Cannot refresh token without cloud_username, cloud_password, and envoy_serial. "
                "Provide those or supply a manual token."
            )

        try:
            token = self._run_async(self._async_refresh_and_validate())
            self.did_refresh = True
            return token
        except Exception as e:
            msg = str(e)
            self.last_error = msg
            # A common real-world cause: MFA enabled → cloud login fails
            self.logger.error(
                "Token refresh failed. If your Enlighten account has MFA enabled, disable it or use a manually generated token. Error: %s",
                msg,
            )
            raise

    # -------------------------
    # Internals
    # -------------------------

    def _token_is_valid_enough(self, exp_ts: int) -> bool:
        """True if token exists and not expiring within the refresh margin."""
        if not exp_ts:
            # If we can't parse exp, treat as unknown and force refresh soon
            return False
        now = int(time.time())
        if exp_ts <= now:
            return False
        # Refresh when within margin
        return exp_ts > (now + self.refresh_margin_seconds)

    @staticmethod
    def _jwt_exp_ts(token: str) -> int:
        """
        Decode JWT 'exp' without verifying signature.
        Returns 0 if missing/unparseable.
        """
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            exp = payload.get("exp")
            return int(exp) if exp is not None else 0
        except Exception:
            return 0

    def _run_async(self, coro):
        """
        Run an async coroutine from sync Indigo code.
        Uses asyncio.run when possible; falls back to a private loop if already running.
        """
        try:
            return asyncio.run(coro)
        except RuntimeError as e:
            # Happens if called from within an existing running loop (rare in Indigo, but safe)
            if "asyncio.run()" in str(e) or "running event loop" in str(e):
                loop = asyncio.new_event_loop()
                try:
                    return loop.run_until_complete(coro)
                finally:
                    loop.close()
            raise

    # ── PKCE OAuth flow (vincentwolsink) ───────────────────────────────

    async def _async_pkce_fetch_token(self) -> str:
        """Obtain token via the PKCE OAuth flow used by the Envoy web UI.

        Steps (reverse-engineered from vincentwolsink HA installer integration):
          1. Generate a PKCE code_verifier + code_challenge.
          2. POST credentials to ``entrez.enphaseenergy.com/login`` with the
             challenge.  Expect a 302 redirect whose Location carries an
             authorization ``code``.
          3. POST the code + verifier to the **local Envoy**
             ``/auth/get_jwt`` which returns the JWT.

        The Envoy mints the token so the ``enphaseUser`` claim correctly
        reflects the Enlighten account type (owner / installer).
        """
        code_verifier = _random_content(40)

        login_data = {
            "username": self.cloud_username,
            "password": self.cloud_password,
            "codeChallenge": _generate_challenge(code_verifier),
            "redirectUri": f"https://{self.host}/auth/callback",
            "client": "envoy-ui",
            "clientId": "envoy-ui-client",
            "authFlow": "oauth",
            "serialNum": self.envoy_serial,
            "granttype": "authorize",
            "state": "",
            "invalidSerialNum": "",
        }

        self.logger.debug("PKCE: posting to entrez login with challenge %s", login_data["codeChallenge"])

        # SSL context that verifies certs for Enlighten cloud
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)

        # Do NOT follow redirects — we need the 302 Location header
        async with aiohttp.ClientSession(
            timeout=timeout,
        ) as client:
            # Step 2 – login at entrez (expect 302)
            async with client.post(
                ENLIGHTEN_LOGIN_URL,
                data=login_data,
                allow_redirects=False,
            ) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise ValueError(
                        f"PKCE: Enlighten login failed — HTTP {resp.status}: {body[:200]}"
                    )
                if resp.status != 302:
                    raise ValueError(
                        f"PKCE: Expected 302 redirect from Enlighten login, got {resp.status}"
                    )

                redirect_location = resp.headers.get("location", "")

            url_parts = parse.urlparse(redirect_location)
            query_parts = parse.parse_qs(url_parts.query)

            if "code" not in query_parts:
                raise ValueError(
                    f"PKCE: No authorization code in redirect URL: {redirect_location}"
                )

            # Step 3 – exchange code for JWT on local Envoy (self-signed cert)
            json_data = {
                "client_id": "envoy-ui-1",
                "code": query_parts["code"][0],
                "code_verifier": code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": login_data["redirectUri"],
            }

            self.logger.debug("PKCE: exchanging code for JWT on local Envoy")

            envoy_connector = aiohttp.TCPConnector(ssl=NO_VERIFY_SSL_CONTEXT)
            async with aiohttp.ClientSession(
                connector=envoy_connector,
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
            ) as envoy_client:
                async with envoy_client.post(
                    ENDPOINT_URL_GET_JWT.format(self.host),
                    json=json_data,
                ) as jwt_resp:
                    if jwt_resp.status != 200:
                        body = await jwt_resp.text()
                        raise ValueError(
                            f"PKCE: Could not fetch JWT from Envoy /auth/get_jwt — "
                            f"HTTP {jwt_resp.status}: {body[:200]}"
                        )
                    jwt_json = await jwt_resp.json()
                    return jwt_json["access_token"]

    # ── Orchestration: try PKCE first, fall back to pyenphase ────────

    async def _async_refresh_and_validate(self) -> str:
        """Obtain a fresh token: try PKCE OAuth first, then pyenphase cloud."""

        new_token: str | None = None

        # ── Attempt 1: PKCE OAuth (vincentwolsink) ──
        try:
            self.logger.info("Token refresh: trying PKCE OAuth flow (Envoy web-UI style)…")
            new_token = await self._async_pkce_fetch_token()
            self.logger.info("PKCE OAuth flow succeeded.")
            self._log_token_details(new_token, "PKCE")
        except Exception as exc:
            self.logger.warning("PKCE OAuth flow failed (%r). Falling back to pyenphase cloud flow.", exc)

        # ── Attempt 2: pyenphase cloud (original) ──
        if not new_token:
            try:
                self.logger.info("Token refresh: trying pyenphase cloud flow…")
                assert aiohttp is not None
                assert NO_VERIFY_SSL_CONTEXT is not None

                connector = aiohttp.TCPConnector(ssl=NO_VERIFY_SSL_CONTEXT)
                timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)

                async with aiohttp.ClientSession(connector=connector, timeout=timeout) as client:
                    self.logger.debug("Calling pyenphase EnvoyTokenAuth.refresh()")
                    await self._auth.refresh()
                    self.logger.debug("Calling pyenphase EnvoyTokenAuth.setup() for local validation")
                    await self._auth.setup(client)

                new_token = getattr(self._auth, "token", None)
                if new_token:
                    self.logger.info("pyenphase cloud flow succeeded.")
                    self._log_token_details(new_token, "pyenphase cloud")
            except Exception as exc:
                self.logger.error("pyenphase cloud flow also failed: %s", exc)

        if not new_token:
            raise ValueError("Both PKCE and pyenphase token flows failed. Check credentials and network.")

        # ── Validate with local Envoy (/auth/check_jwt) ──
        try:
            envoy_connector = aiohttp.TCPConnector(ssl=NO_VERIFY_SSL_CONTEXT)
            async with aiohttp.ClientSession(
                connector=envoy_connector,
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
            ) as client:
                async with client.get(
                    ENDPOINT_URL_CHECK_JWT.format(self.host),
                    headers={"Authorization": f"Bearer {new_token}"},
                ) as check_resp:
                    if check_resp.status == 200:
                        self.logger.debug("Token validated against local Envoy (/auth/check_jwt).")

                    else:
                        self.logger.warning(
                            "Token check_jwt returned HTTP %s — token may not be accepted by Envoy.",
                            check_resp.status,
                        )
        except Exception as exc:
            self.logger.warning("Could not validate token with local Envoy: %s", exc)

        exp_ts = self._jwt_exp_ts(new_token)
        self._state = TokenState(token=new_token, exp_ts=exp_ts, fetched_ts=int(time.time()))

        self.logger.info(
            "Successfully obtained new token. Expires: %s — will auto-refresh before expiry.",
            datetime.fromtimestamp(exp_ts).isoformat() if exp_ts else "<unknown>",
        )
        return new_token

    def _log_token_details(self, token: str, flow_name: str) -> None:
        """Log the full token and decoded JWT claims to help identify token type."""
        self.logger.info("Token obtained via %s flow:", flow_name)
        self.logger.info("  Token: %s", token)
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            user_type = payload.get("enphaseUser", "<missing>")
            issuer = payload.get("iss", "<missing>")
            exp = payload.get("exp")
            iat = payload.get("iat")
            username = payload.get("username", "<missing>")
            exp_str = datetime.fromtimestamp(int(exp)).isoformat() if exp else "<missing>"
            iat_str = datetime.fromtimestamp(int(iat)).isoformat() if iat else "<missing>"
            self.logger.info("  JWT enphaseUser : %s", user_type)
            self.logger.info("  JWT issuer (iss): %s", issuer)
            self.logger.info("  JWT username    : %s", username)
            self.logger.info("  JWT issued (iat): %s", iat_str)
            self.logger.info("  JWT expiry (exp): %s", exp_str)
            if user_type == "installer":
                self.logger.info("  ** This is an INSTALLER token — full Envoy API access. **")
            elif user_type == "owner":
                self.logger.info("  ** This is an OWNER token — read-only access; power control endpoints unavailable. **")
            else:
                self.logger.warning("  ** Could not determine token type (enphaseUser=%r). **", user_type)
        except Exception as exc:
            self.logger.warning("  Could not decode JWT payload: %s", exc)