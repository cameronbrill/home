"""Authentication for Roborock's current v4 password-login API."""

import base64
from dataclasses import dataclass
import hashlib
import json
import re
import secrets
from typing import Any, cast
from urllib.parse import urlparse

from aiohttp import ClientError, ClientSession, ClientTimeout
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from roborock.data.containers import UserData

BASE_URLS = (
    "https://usiot.roborock.com",
    "https://euiot.roborock.com",
    "https://cniot.roborock.com",
    "https://ruiot.roborock.com",
)
DEFAULT_AGREEMENT = {"majorVersion": 14, "minorVersion": 0}
REQUEST_TIMEOUT = ClientTimeout(total=30)


class RoborockAuthenticationError(RuntimeError):
    """A Roborock login failed without exposing account credentials."""


@dataclass(frozen=True)
class RoborockLoginResult:
    """A successful login and the regional API endpoint it belongs to."""

    user_data: UserData
    base_url: str | None


def _validate_api_url(raw_url: str) -> str:
    candidate = raw_url if "://" in raw_url else f"https://{raw_url}"
    parsed = urlparse(candidate)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (hostname == "roborock.com" or hostname.endswith(".roborock.com")):
        raise RoborockAuthenticationError("Roborock returned an untrusted API endpoint")
    return candidate.rstrip("/")


def login_from_session(raw_session: str) -> RoborockLoginResult:
    """Restore a previously authenticated Roborock session without logging it."""
    try:
        payload = json.loads(raw_session)
    except ValueError:
        raise RoborockAuthenticationError("Stored Roborock session is not valid JSON") from None

    if not isinstance(payload, dict):
        raise RoborockAuthenticationError("Stored Roborock session is invalid")
    try:
        user_data = UserData.from_dict(cast("dict[str, Any]", payload))
    except ValueError:
        raise RoborockAuthenticationError("Stored Roborock session has invalid fields") from None
    except TypeError:
        raise RoborockAuthenticationError("Stored Roborock session has invalid fields") from None
    if not user_data.token or not user_data.rriot:
        raise RoborockAuthenticationError("Stored Roborock session has no token or rriot data")
    session_base_url = user_data.rriot.r.a
    if not session_base_url:
        raise RoborockAuthenticationError("Stored Roborock session has no API endpoint")
    _validate_api_url(session_base_url)
    return RoborockLoginResult(user_data=user_data, base_url=None)


def country_from_host(base_url: str) -> str:
    hostname = (urlparse(base_url).hostname or "").lower()
    if hostname.startswith("euiot."):
        return "DE"
    if hostname.startswith("cniot."):
        return "CN"
    if hostname.startswith("ruiot."):
        return "RU"
    if hostname == "api.roborock.com":
        return "SG"
    if hostname.startswith("api-us."):
        return "US"
    if hostname.startswith("api-eu."):
        return "DE"
    if hostname.startswith("api-cn."):
        return "CN"
    if hostname.startswith("api-ru."):
        return "RU"
    return "US"


def _safe_server_message(message: object) -> str:
    text = message if isinstance(message, str) else "login refused"
    text = re.sub(r"[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[redacted]", text)
    return text[:200]


def encrypt_password(password: str, signing_key: str) -> str:
    """Encrypt a password exactly as Roborock's app does for v4 login."""
    if len(signing_key) < 8:
        raise RoborockAuthenticationError("Roborock returned an invalid signing key")

    derived_key = signing_key[4:] + signing_key[:4]
    if len(derived_key) != AES.block_size:
        raise RoborockAuthenticationError("Roborock returned an invalid signing key")

    cipher = AES.new(derived_key.encode(), AES.MODE_ECB)
    encrypted = cipher.encrypt(pad(password.encode(), AES.block_size))
    return base64.b64encode(encrypted).decode()


def _login_headers(username: str, device_identifier: str) -> dict[str, str]:
    client_hash = hashlib.md5(usedforsecurity=False)
    client_hash.update(username.encode())
    client_hash.update(device_identifier.encode())
    return {
        "header_clientid": base64.b64encode(client_hash.digest()).decode(),
        "header_clientlang": "en",
        "header_appversion": "4.54.02",
        "header_phonemodel": "iPhone16,1",
        "header_phonesystem": "iOS",
    }


def _login_nonce() -> str:
    raw = base64.b64encode(secrets.token_bytes(12)).decode()[:16]
    return raw.replace("+", "X").replace("/", "Y")


async def _request_json(
    session: ClientSession,
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        async with session.request(
            method,
            url,
            headers=headers,
            params=params,
            data=data,
            timeout=REQUEST_TIMEOUT,
        ) as response:
            body = await response.read()
            status = response.status
            content_type = response.content_type
    except (ClientError, TimeoutError, OSError) as error:
        raise RoborockAuthenticationError("Could not reach Roborock") from error

    try:
        payload = json.loads(body)
    except ValueError:
        raise RoborockAuthenticationError(
            f"Roborock returned a non-JSON response (HTTP {status}, {content_type})"
        ) from None

    if not isinstance(payload, dict):
        raise RoborockAuthenticationError("Roborock returned an unexpected login response")
    return payload


async def _discover_base_url(
    session: ClientSession,
    username: str,
    headers: dict[str, str],
) -> tuple[str, str]:
    for base_url in BASE_URLS:
        try:
            payload = await _request_json(
                session,
                "POST",
                f"{base_url}/api/v1/getUrlByEmail",
                headers=headers,
                params={"email": username, "needtwostepauth": "false"},
            )
        except RoborockAuthenticationError:
            continue
        if payload.get("code") != 200:
            continue

        data = payload.get("data")
        if not isinstance(data, dict):
            continue
        url_value = data.get("url")
        if not isinstance(url_value, str):
            continue
        resolved_url = _validate_api_url(url_value)
        country_value = data.get("country")
        country = country_value if isinstance(country_value, str) and country_value else country_from_host(resolved_url)
        return resolved_url, country

    raise RoborockAuthenticationError("Roborock could not resolve the account's regional API")


async def _agreement_version(
    session: ClientSession,
    base_url: str,
    country: str,
    headers: dict[str, str],
) -> dict[str, int]:
    try:
        payload = await _request_json(
            session,
            "GET",
            f"{base_url}/api/v3/app/agreement/latest",
            headers=headers,
            params={"country": country},
        )
    except RoborockAuthenticationError:
        return DEFAULT_AGREEMENT

    data = payload.get("data")
    if payload.get("code") != 200 or not isinstance(data, dict):
        return DEFAULT_AGREEMENT
    major = data.get("majorVersion")
    minor = data.get("minorVersion")
    if isinstance(major, int) and isinstance(minor, int):
        return {"majorVersion": major, "minorVersion": minor}
    return DEFAULT_AGREEMENT


async def discover_api_base_url(
    session: ClientSession,
    username: str,
) -> str:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    base_url, _ = await _discover_base_url(session, username, headers)
    return base_url


async def login_with_password(
    *,
    session: ClientSession | None,
    username: str,
    password: str,
    base_url: str | None = None,
) -> RoborockLoginResult:
    """Log in through the signed v4 endpoint used by the current Roborock app."""
    owns_session = session is None
    active_session = session or ClientSession()
    device_identifier = secrets.token_urlsafe(16)
    headers = _login_headers(username, device_identifier)

    try:
        if base_url is None:
            resolved_base_url, country = await _discover_base_url(active_session, username, headers)
        else:
            resolved_base_url = base_url.rstrip("/")
            country = country_from_host(resolved_base_url)

        nonce = _login_nonce()
        signing_payload = await _request_json(
            active_session,
            "POST",
            f"{resolved_base_url}/api/v3/key/sign",
            headers=headers,
            params={"s": nonce},
        )
        signing_data = signing_payload.get("data")
        if signing_payload.get("code") != 200 or not isinstance(signing_data, dict):
            raise RoborockAuthenticationError("Roborock rejected the login signature request")
        signing_key = signing_data.get("k")
        if not isinstance(signing_key, str):
            raise RoborockAuthenticationError("Roborock returned an invalid signing key")

        agreement = await _agreement_version(active_session, resolved_base_url, country, headers)
        login_payload = await _request_json(
            active_session,
            "POST",
            f"{resolved_base_url}/api/v4/auth/email/login/pwd",
            headers={
                **headers,
                "x-mercy-k": signing_key,
                "x-mercy-ks": nonce,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "email": username,
                "password": encrypt_password(password, signing_key),
                "majorVersion": str(agreement["majorVersion"]),
                "minorVersion": str(agreement["minorVersion"]),
            },
        )
        response_code = login_payload.get("code")
        if response_code != 200:
            raise RoborockAuthenticationError(
                f"Roborock login failed ({response_code}): {_safe_server_message(login_payload.get('msg'))}"
            )

        user_data_payload = login_payload.get("data")
        if not isinstance(user_data_payload, dict):
            raise RoborockAuthenticationError("Roborock returned an invalid user session")
        try:
            user_data = UserData.from_dict(cast("dict[str, Any]", user_data_payload))
        except ValueError:
            raise RoborockAuthenticationError("Roborock returned an invalid user session") from None
        except TypeError:
            raise RoborockAuthenticationError("Roborock returned an invalid user session") from None
        return RoborockLoginResult(user_data=user_data, base_url=resolved_base_url)
    finally:
        if owns_session:
            await active_session.close()
