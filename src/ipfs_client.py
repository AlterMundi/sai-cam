"""
IPFS Client for SAI-Cam

Uploads images to IPFS via the Kubo HTTP API or a Cluster proxy.
Designed to run against a remote node over a Zerotier VPN.
"""

import io
import random
import time

import requests


_MAX_RETRIES = 3
_BASE_RETRY_DELAY = 1.0  # seconds, before jitter


class IPFSClient:
    """HTTP client for the Kubo (or Cluster-proxied) IPFS API."""

    def __init__(self, config: dict, logger):
        """
        Initialize the IPFS client.

        Args:
            config: ipfs sub-dict from the main config.
                    Expected keys:
                      api_url   - base URL, e.g. 'https://ipfs.altermundi.net/api/v0'
                      api_token - optional Bearer token for reverse-proxy auth
                      backend   - 'kubo' (default) or 'cluster'
                      timeout   - request timeout in seconds (default 60)
            logger: standard logging.Logger (or RateLimitedLogger)
        """
        self.logger = logger
        self.api_url = config.get("api_url", "http://127.0.0.1:5001/api/v0").rstrip("/")
        self.timeout = int(config.get("timeout", 60))
        try:
            cid_version = int(config.get("cid_version", 1))
        except (TypeError, ValueError):
            cid_version = 1
        self.cid_version = 1 if cid_version not in (0, 1) else cid_version
        self.pin = bool(config.get("pin", True))
        # 'cluster' backend proxies the Kubo API on port 9095 — same /api/v0/add path.
        # We just note the backend for logging; the caller is responsible for setting
        # api_url to the correct endpoint+port.
        self.backend = config.get("backend", "kubo")
        # Optional Bearer token for reverse-proxy auth (e.g. ipfs.altermundi.net)
        token = config.get("api_token", "").strip()
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.logger.info(
            f"IPFSClient initialised: backend={self.backend} api_url={self.api_url} timeout={self.timeout}s "
            f"cid_version={self.cid_version} pin={self.pin} auth={'yes' if token else 'no'}"
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def add_image(self, image_bytes: bytes, filename: str):
        """Upload image bytes to IPFS.

        Args:
            image_bytes: Raw image data.
            filename: Filename to embed in the multipart payload.

        Returns:
            CID string on success, None on failure.
        """
        url = f"{self.api_url}/add"
        params = {
            "cid-version": str(self.cid_version),
            "pin": "true" if self.pin else "false",
            "quieter": "true",
            "progress": "false",
        }

        last_error = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                files = {"file": (filename, io.BytesIO(image_bytes), "image/jpeg")}
                response = requests.post(url, params=params, files=files, headers=self._headers, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()
                cid = data.get("Hash")
                if not cid:
                    self.logger.error(
                        f"IPFS add_image: unexpected response (no Hash field): {data}"
                    )
                    return None
                self.logger.debug(
                    f"IPFS add_image: uploaded {filename} ({len(image_bytes)} bytes) -> {cid}"
                )
                return cid

            except requests.exceptions.Timeout as e:
                last_error = e
                self.logger.warning(
                    f"IPFS add_image: timeout on attempt {attempt}/{_MAX_RETRIES} for {filename}: {e}"
                )
            except requests.exceptions.ConnectionError as e:
                last_error = e
                self.logger.warning(
                    f"IPFS add_image: connection error on attempt {attempt}/{_MAX_RETRIES} for {filename}: {e}"
                )
            except requests.exceptions.HTTPError as e:
                last_error = e
                # 4xx errors are not transient — don't retry
                self.logger.error(
                    f"IPFS add_image: HTTP error for {filename}: {e}"
                )
                return None
            except Exception as e:
                last_error = e
                self.logger.error(
                    f"IPFS add_image: unexpected error on attempt {attempt}/{_MAX_RETRIES} for {filename}: {e}",
                    exc_info=True,
                )

            if attempt < _MAX_RETRIES:
                delay = _BASE_RETRY_DELAY * attempt + random.uniform(0, 1.0)
                self.logger.debug(f"IPFS add_image: retrying in {delay:.1f}s")
                time.sleep(delay)

        self.logger.error(
            f"IPFS add_image: all {_MAX_RETRIES} attempts failed for {filename}: {last_error}"
        )
        return None

    def check_health(self) -> bool:
        """Check connectivity to the IPFS node.

        Returns:
            True if the node is reachable and responds to /version, False otherwise.
        """
        url = f"{self.api_url}/version"
        try:
            response = requests.post(url, headers=self._headers, timeout=5)
            response.raise_for_status()
            data = response.json()
            version = data.get("Version", "unknown")
            self.logger.debug(f"IPFS check_health: node reachable, version={version}")
            return True
        except Exception as e:
            self.logger.warning(f"IPFS check_health: node unreachable: {e}")
            return False
