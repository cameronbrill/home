import base64
import json
import socket
from urllib.parse import parse_qs

from aiohttp import web
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
import pytest

from core.roborock_auth import (
    RoborockAuthenticationError,
    country_from_host,
    encrypt_password,
    login_from_session,
    login_with_password,
)

USERNAME = "fixture@example.invalid"
PASSWORD = "fixture-password-not-real"  # noqa: S105
SIGNING_KEY = "abcdefghijklmnop"


def decrypt_password(value: str, signing_key: str) -> str:
    derived_key = signing_key[4:] + signing_key[:4]
    cipher = AES.new(derived_key.encode(), AES.MODE_ECB)
    encrypted = base64.b64decode(value)
    return unpad(cipher.decrypt(encrypted), AES.block_size).decode()


def available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_encrypt_password_uses_rotated_signing_key() -> None:
    encrypted = encrypt_password(PASSWORD, SIGNING_KEY)

    assert encrypted != PASSWORD
    assert decrypt_password(encrypted, SIGNING_KEY) == PASSWORD


@pytest.mark.asyncio()
async def test_password_login_uses_sign_then_v4_password_endpoint() -> None:
    seen: dict[str, str] = {}

    async def sign(request: web.Request) -> web.Response:
        seen["nonce"] = request.query["s"]
        return web.json_response({"code": 200, "data": {"k": SIGNING_KEY}})

    async def agreement(request: web.Request) -> web.Response:
        assert request.query["country"] == "US"
        return web.json_response({"code": 200, "data": {"majorVersion": 16, "minorVersion": 0}})

    async def login(request: web.Request) -> web.Response:
        body = await request.text()
        seen["body"] = body
        assert PASSWORD not in body
        form = parse_qs(body)
        assert form["email"] == [USERNAME]
        assert form["majorVersion"] == ["16"]
        assert decrypt_password(form["password"][0], SIGNING_KEY) == PASSWORD
        assert request.headers["x-mercy-k"] == SIGNING_KEY
        assert request.headers["x-mercy-ks"] == seen["nonce"]
        return web.json_response(
            {
                "code": 200,
                "msg": "success",
                "data": {
                    "uid": 1,
                    "token": "test-token",
                    "rruid": "test-rruid",
                    "country": "US",
                    "countrycode": "1",
                    "rriot": {
                        "u": "user",
                        "s": "secret",
                        "h": "hash",
                        "k": "key",
                        "r": {
                            "r": "US",
                            "a": "https://example.invalid",
                            "m": "mqtts://example.invalid:8883",
                            "l": "local-key",
                        },
                    },
                },
            }
        )

    app = web.Application()
    app.router.add_post("/api/v3/key/sign", sign)
    app.router.add_get("/api/v3/app/agreement/latest", agreement)
    app.router.add_post("/api/v4/auth/email/login/pwd", login)
    runner = web.AppRunner(app)
    await runner.setup()
    port = available_port()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    try:
        login_result = await login_with_password(
            session=None,
            username=USERNAME,
            password=PASSWORD,
            base_url=f"http://127.0.0.1:{port}",
        )
    finally:
        await runner.cleanup()

    assert len(seen["nonce"]) == 16
    assert login_result.user_data.token is not None
    assert login_result.user_data.rriot.k == "key"
    assert login_result.base_url == f"http://127.0.0.1:{port}"


@pytest.mark.asyncio()
async def test_login_error_does_not_disclose_password() -> None:
    async def sign(request: web.Request) -> web.Response:
        return web.json_response({"code": 200, "data": {"k": SIGNING_KEY}})

    async def agreement(request: web.Request) -> web.Response:
        return web.json_response({"code": 200, "data": {"majorVersion": 16, "minorVersion": 0}})

    async def login(request: web.Request) -> web.Response:
        return web.json_response(
            {"code": 2012, "msg": "invalid credentials for fixture@example.invalid"},
            status=401,
        )

    app = web.Application()
    app.router.add_post("/api/v3/key/sign", sign)
    app.router.add_get("/api/v3/app/agreement/latest", agreement)
    app.router.add_post("/api/v4/auth/email/login/pwd", login)
    runner = web.AppRunner(app)
    await runner.setup()
    port = available_port()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    try:
        with pytest.raises(RoborockAuthenticationError) as exc_info:
            await login_with_password(
                session=None,
                username=USERNAME,
                password=PASSWORD,
                base_url=f"http://127.0.0.1:{port}",
            )
    finally:
        await runner.cleanup()

    assert "2012" in str(exc_info.value)
    assert PASSWORD not in str(exc_info.value)
    assert USERNAME not in str(exc_info.value)


def test_stored_session_restores_token_and_region() -> None:
    stored_session = json.dumps(
        {
            "uid": 1,
            "token": "test-token",
            "rruid": "test-rruid",
            "country": "US",
            "countrycode": "1",
            "rriot": {
                "u": "user",
                "s": "secret",
                "h": "hash",
                "k": "key",
                "r": {
                    "r": "US",
                    "a": "https://usiot.roborock.com",
                    "m": "mqtts://example.invalid:8883",
                    "l": "local-key",
                },
            },
        }
    )

    result = login_from_session(stored_session)

    assert result.user_data.token is not None
    assert result.user_data.rriot.k == "key"
    assert result.base_url is None


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://usiot.roborock.com", "US"),
        ("https://api-us.roborock.com", "US"),
        ("https://api.roborock.com", "SG"),
        ("https://api-eu.roborock.com", "DE"),
        ("https://api-cn.roborock.com", "CN"),
        ("https://api-ru.roborock.com", "RU"),
    ],
)
def test_regional_country_fallback(base_url: str, expected: str) -> None:
    assert country_from_host(base_url) == expected


def test_stored_session_rejects_untrusted_endpoint() -> None:
    stored_session = json.dumps(
        {
            "token": "test-token",
            "rriot": {
                "u": "user",
                "s": "secret",
                "h": "hash",
                "k": "key",
                "r": {"r": "US", "a": "https://attacker.example"},
            },
        }
    )

    with pytest.raises(RoborockAuthenticationError) as exc_info:
        login_from_session(stored_session)

    assert "untrusted API endpoint" in str(exc_info.value)


def test_invalid_stored_session_does_not_echo_session_contents() -> None:
    invalid_session = '{"token": "must-not-appear"'

    with pytest.raises(RoborockAuthenticationError) as exc_info:
        login_from_session(invalid_session)

    assert "must-not-appear" not in str(exc_info.value)


@pytest.mark.asyncio()
async def test_discovery_rejects_untrusted_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    async def discovery(request: web.Request) -> web.Response:
        return web.json_response({"code": 200, "data": {"url": "https://attacker.example", "country": "US"}})

    app = web.Application()
    app.router.add_post("/api/v1/getUrlByEmail", discovery)
    runner = web.AppRunner(app)
    await runner.setup()
    port = available_port()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    monkeypatch.setattr("core.roborock_auth.BASE_URLS", (f"http://127.0.0.1:{port}",))
    try:
        with pytest.raises(RoborockAuthenticationError) as exc_info:
            await login_with_password(
                session=None,
                username=USERNAME,
                password=PASSWORD,
            )
    finally:
        await runner.cleanup()

    assert "untrusted API endpoint" in str(exc_info.value)
    assert USERNAME not in str(exc_info.value)
