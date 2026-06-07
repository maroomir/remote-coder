import httpx
import pytest
import respx
from httpx import Response

import app.tunnel as tunnel


@respx.mock
def test_fetch_public_url_returns_first_https():
    respx.get(tunnel.NGROK_LOCAL_API).mock(
        return_value=Response(
            200,
            json={
                "tunnels": [
                    {"public_url": "http://abcd.ngrok-free.app"},
                    {"public_url": "https://abcd.ngrok-free.app"},
                ]
            },
        )
    )

    assert tunnel.fetch_public_url() == "https://abcd.ngrok-free.app"


@respx.mock
def test_fetch_public_url_none_without_https():
    respx.get(tunnel.NGROK_LOCAL_API).mock(
        return_value=Response(200, json={"tunnels": [{"public_url": "http://abcd"}]})
    )

    assert tunnel.fetch_public_url() is None


@respx.mock
def test_fetch_public_url_none_on_connection_error():
    respx.get(tunnel.NGROK_LOCAL_API).mock(side_effect=httpx.ConnectError("refused"))

    assert tunnel.fetch_public_url() is None


def test_ensure_ngrok_available_raises_when_missing(monkeypatch):
    monkeypatch.setattr("app.tunnel.shutil.which", lambda name: None)

    with pytest.raises(tunnel.TunnelError):
        tunnel.ensure_ngrok_available()


def test_ensure_ngrok_available_returns_path(monkeypatch):
    monkeypatch.setattr("app.tunnel.shutil.which", lambda name: "/usr/local/bin/ngrok")

    assert tunnel.ensure_ngrok_available() == "/usr/local/bin/ngrok"


def test_ensure_ngrok_configured_raises_without_valid_config(monkeypatch):
    class _Result:
        stdout = ""
        stderr = "authtoken not found"

    monkeypatch.setattr("app.tunnel.subprocess.run", lambda *a, **k: _Result())

    with pytest.raises(tunnel.TunnelError):
        tunnel.ensure_ngrok_configured()


def test_ensure_ngrok_configured_accepts_valid_config(monkeypatch):
    class _Result:
        stdout = "Valid configuration file at /home/user/.config/ngrok/ngrok.yml"
        stderr = ""

    monkeypatch.setattr("app.tunnel.subprocess.run", lambda *a, **k: _Result())

    tunnel.ensure_ngrok_configured()
