# authorisation.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Indigo Enphase Token Authorisation (pyenphase-based)

This module provides a small, sync-friendly wrapper around pyenphase EnvoyTokenAuth
(the same token auth strategy Home Assistant uses).

You get:
  - get_token(): returns a valid token; refreshes when near expiry or missing
  - refresh_token(): force refresh from cloud and validate token against local Envoy

Notes:
  - Requires `pyenphase` and `aiohttp` in your Indigo plugin environment.
  - Cloud token retrieval may fail if Enlighten MFA is enabled.
"""

from __future__ import annotations
from datetime import datetime
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

import jwt  # PyJWT


import aiohttp
from pyenphase.auth import EnvoyTokenAuth
from pyenphase.ssl import NO_VERIFY_SSL_CONTEXT


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

    async def _async_refresh_and_validate(self) -> str:
        """
        Use pyenphase EnvoyTokenAuth to:
          1) refresh token from cloud
          2) setup() to validate against local Envoy
        """
        assert aiohttp is not None
        assert NO_VERIFY_SSL_CONTEXT is not None

        connector = aiohttp.TCPConnector(ssl=NO_VERIFY_SSL_CONTEXT)
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as client:
            # Force cloud refresh first
            self.logger.debug("Calling pyenphase EnvoyTokenAuth.refresh()")
            await self._auth.refresh()

            # Validate/setup against local Envoy (and ensure headers/cookies correct)
            self.logger.debug("Calling pyenphase EnvoyTokenAuth.setup() for local validation")
            await self._auth.setup(client)

        # Pull token from pyenphase object
        new_token = getattr(self._auth, "token", None)
        if not new_token:
            raise ValueError("pyenphase EnvoyTokenAuth did not provide a token after refresh/setup.")

        exp_ts = self._jwt_exp_ts(new_token)
        self._state = TokenState(token=new_token, exp_ts=exp_ts, fetched_ts=int(time.time()))

        self.logger.info("Successfully obtained new token . Expires: %s — will auto-refresh before expiry.",
                          datetime.fromtimestamp(exp_ts).isoformat() if exp_ts else "<unknown>")
        return new_token
