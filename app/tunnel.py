from __future__ import annotations

import shutil
import subprocess
import time

import httpx

from app.monitoring.events import EventLogger

_tunnellog = EventLogger("app.tunnel", "tunnel")

NGROK_LOCAL_API = "http://127.0.0.1:4040/api/tunnels"


class TunnelError(RuntimeError):
    pass


def ensure_ngrok_available() -> str:
    path = shutil.which("ngrok")
    if path is None:
        raise TunnelError(
            "ngrok executable not found. Install from https://ngrok.com/download"
        )
    return path


def ensure_ngrok_configured() -> None:
    try:
        result = subprocess.run(
            ["ngrok", "config", "check"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise TunnelError(f"Failed to verify ngrok configuration: {exc}") from exc

    combined = f"{result.stdout}\n{result.stderr}"
    if "Valid configuration" not in combined:
        raise TunnelError(
            "ngrok AuthToken is not configured. Get a token from https://dashboard.ngrok.com "
            "and run `ngrok config add-authtoken <token>`."
        )


def fetch_public_url() -> str | None:
    try:
        response = httpx.get(NGROK_LOCAL_API, timeout=2.0)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    for tunnel in data.get("tunnels", []):
        public_url = tunnel.get("public_url", "")
        if public_url.startswith("https"):
            return public_url
    return None


class NgrokTunnel:
    def __init__(self, port: int = 8000) -> None:
        self._port = port
        self._process: subprocess.Popen | None = None
        self.public_url: str | None = None

    def start(self, *, startup_timeout: float = 15.0) -> str:
        ensure_ngrok_available()
        ensure_ngrok_configured()
        self._process = subprocess.Popen(
            ["ngrok", "http", str(self._port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        url = self._wait_for_public_url(startup_timeout)
        if url is None:
            self.stop()
            raise TunnelError(
                "Failed to get ngrok public URL. Check whether another ngrok session is already running."
            )
        self.public_url = url
        _tunnellog.info("ngrok tunnel started url=%s port=%d", url, self._port)
        return url

    def _wait_for_public_url(self, timeout: float) -> str | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            url = fetch_public_url()
            if url:
                return url
            time.sleep(0.5)
        return None

    def stop(self) -> None:
        if self._process is None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
        self._process = None
        _tunnellog.info("ngrok tunnel stopped")
