"""
Zoho CRM API client.

Auth model: Zoho uses short-lived access tokens (1 hr) minted from a
long-lived refresh token. You generate the refresh token ONCE via Zoho's
self-client flow (see README) and this module handles renewing access
tokens automatically from then on — no manual token pasting per run.

Env vars required (see .env.example):
    ZOHO_CLIENT_ID
    ZOHO_CLIENT_SECRET
    ZOHO_REFRESH_TOKEN
    ZOHO_ACCOUNTS_DOMAIN   e.g. https://accounts.zoho.in  (region-specific!)
    ZOHO_API_DOMAIN        e.g. https://www.zohoapis.in    (region-specific!)
"""
from __future__ import annotations
import logging
import os
import time
from dataclasses import dataclass

import requests

from .config import ZOHO_MODULE, ZOHO_DUPLICATE_CHECK_FIELD

logger = logging.getLogger("formatter.zoho")

BULK_UPSERT_BATCH_SIZE = 100  # Zoho's hard cap per /upsert call
MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 2


@dataclass
class ZohoConfig:
    client_id: str
    client_secret: str
    refresh_token: str
    accounts_domain: str
    api_domain: str

    @classmethod
    def from_env(cls) -> "ZohoConfig":
        missing = [
            var for var in (
                "ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN",
                "ZOHO_ACCOUNTS_DOMAIN", "ZOHO_API_DOMAIN",
            )
            if not os.environ.get(var)
        ]
        if missing:
            raise EnvironmentError(
                f"Missing required Zoho env vars: {', '.join(missing)}. "
                "See .env.example / README for how to obtain them."
            )
        return cls(
            client_id=os.environ["ZOHO_CLIENT_ID"],
            client_secret=os.environ["ZOHO_CLIENT_SECRET"],
            refresh_token=os.environ["ZOHO_REFRESH_TOKEN"],
            accounts_domain=os.environ["ZOHO_ACCOUNTS_DOMAIN"].rstrip("/"),
            api_domain=os.environ["ZOHO_API_DOMAIN"].rstrip("/"),
        )


class ZohoClient:
    def __init__(self, cfg: ZohoConfig | None = None):
        self.cfg = cfg or ZohoConfig.from_env()
        self._access_token: str | None = None
        self._token_expiry: float = 0.0

    # ---------------------------------------------------------------- auth
    def _refresh_access_token(self) -> None:
        url = f"{self.cfg.accounts_domain}/oauth/v2/token"
        params = {
            "refresh_token": self.cfg.refresh_token,
            "client_id": self.cfg.client_id,
            "client_secret": self.cfg.client_secret,
            "grant_type": "refresh_token",
        }
        resp = requests.post(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if "access_token" not in data:
            raise RuntimeError(f"Zoho token refresh failed: {data}")
        self._access_token = data["access_token"]
        # expires_in is usually 3600s; renew 5 min early to be safe
        self._token_expiry = time.time() + int(data.get("expires_in", 3600)) - 300
        logger.info("Zoho access token refreshed (valid ~1hr).")

    def _get_access_token(self) -> str:
        if not self._access_token or time.time() >= self._token_expiry:
            self._refresh_access_token()
        return self._access_token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Zoho-oauthtoken {self._get_access_token()}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------ requests
    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        backoff = INITIAL_BACKOFF_SECONDS
        for attempt in range(1, MAX_RETRIES + 1):
            resp = requests.request(method, url, headers=self._headers(), timeout=60, **kwargs)

            if resp.status_code == 401 and attempt == 1:
                # token might have just expired between check and call
                self._refresh_access_token()
                continue

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", backoff))
                logger.warning("Zoho rate limit hit, sleeping %ss (attempt %d/%d)",
                               retry_after, attempt, MAX_RETRIES)
                time.sleep(retry_after)
                backoff *= 2
                continue

            if resp.status_code >= 500:
                logger.warning("Zoho server error %s, retrying in %ss (attempt %d/%d)",
                               resp.status_code, backoff, attempt, MAX_RETRIES)
                time.sleep(backoff)
                backoff *= 2
                continue

            return resp  # 2xx, 4xx (non-429) -> return, caller handles

        return resp  # exhausted retries, return last response

    # ------------------------------------------------------------- upsert
    def upsert_records(self, zoho_records: list[dict], module: str = ZOHO_MODULE,
                        duplicate_check_field: str = ZOHO_DUPLICATE_CHECK_FIELD) -> dict:
        """
        Upserts records into Zoho CRM in batches of 100 (API limit).
        Returns a summary dict: {"success": n, "failed": n, "errors": [...]}.
        """
        url = f"{self.cfg.api_domain}/crm/v3/{module}/upsert"
        summary = {"success": 0, "failed": 0, "errors": []}

        for i in range(0, len(zoho_records), BULK_UPSERT_BATCH_SIZE):
            batch = zoho_records[i:i + BULK_UPSERT_BATCH_SIZE]
            body = {"data": batch, "duplicate_check_fields": [duplicate_check_field]}
            resp = self._request_with_retry("POST", url, json=body)

            if resp.status_code not in (200, 201):
                logger.error("Zoho upsert batch failed [%s]: %s", resp.status_code, resp.text)
                summary["failed"] += len(batch)
                summary["errors"].append({"batch_start": i, "status": resp.status_code, "body": resp.text})
                continue

            result = resp.json()
            for entry in result.get("data", []):
                if entry.get("status") == "success":
                    summary["success"] += 1
                else:
                    summary["failed"] += 1
                    summary["errors"].append(entry)

        logger.info("Zoho upsert complete: %d success, %d failed",
                    summary["success"], summary["failed"])
        return summary
