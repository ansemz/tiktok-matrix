"""Minimal client for the TikMatrix local automation API.

Wraps the two things every custom script has to get right — taking a device
lease and keeping it alive — so a script can be about the automation instead
of the protocol.

Two ways to get a device:

    # Managed script: the app already leased a device and passed it in.
    with TikMatrix.from_env() as d:
        d.click(text="Login")

    # Standalone script: pick a device and lease it yourself.
    client = TikMatrix()
    with client.device("192.168.1.5:5555") as d:
        d.click(text="Login")

Both give back the same object. Leaving the `with` block releases the device.

Requires: requests
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:50809"

# The server clamps a lease to 600s. Renewing at a third of the requested TTL
# leaves room for two failed renewals before the device is reclaimed.
DEFAULT_TTL_SECS = 120


class TikMatrixError(RuntimeError):
    """An API call was rejected or a device operation failed."""


class DeviceBusyError(TikMatrixError):
    """The device is already leased, or the plan has no free device slot."""


class TikMatrix:
    """Connection to the local TikMatrix server."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("TIKMATRIX_API_BASE") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()

    # -- plumbing ---------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        session_id: Optional[str] = None,
        raw: bool = False,
        **kwargs: Any,
    ) -> Any:
        headers: Dict[str, str] = {}
        if session_id:
            headers["x-session-id"] = session_id

        response = self._session.request(
            method,
            f"{self.base_url}{path}",
            headers=headers,
            timeout=self.timeout,
            **kwargs,
        )

        if response.status_code == 409:
            raise DeviceBusyError(_error_message(response))
        if not response.ok:
            raise TikMatrixError(f"{method} {path} -> {response.status_code}: {_error_message(response)}")

        if raw:
            return response.content

        payload = response.json()
        if isinstance(payload, dict) and payload.get("code") not in (None, 0):
            raise TikMatrixError(payload.get("message", "request failed"))
        return payload.get("data") if isinstance(payload, dict) else payload

    # -- discovery --------------------------------------------------------

    def devices(self) -> List[Dict[str, Any]]:
        """Every online device, with whether it is currently busy."""
        return self._request("GET", "/api/v1/rpc/devices") or []

    def sessions(self) -> List[Dict[str, Any]]:
        """Leases currently held, including ones this process does not own."""
        return self._request("GET", "/api/v1/rpc/session") or []

    # -- leasing ----------------------------------------------------------

    def device(
        self,
        serial: str,
        label: str = "python script",
        ttl_secs: int = DEFAULT_TTL_SECS,
    ) -> "Device":
        """Lease `serial` and return a handle for driving it."""
        data = self._request(
            "POST",
            "/api/v1/rpc/session",
            json={"serial": serial, "label": label, "ttl_secs": ttl_secs},
        )
        return Device(self, serial, data["session_id"], ttl_secs, owns_session=True)

    @classmethod
    def from_env(cls, timeout: float = 30.0) -> "Device":
        """Adopt the device a managed custom script was started with.

        The app leases the device before spawning the script and passes the
        credentials in the environment, so there is nothing to acquire here —
        and nothing to release either: the runner does that when the task ends.
        """
        serial = os.environ.get("TIKMATRIX_SERIAL")
        session_id = os.environ.get("TIKMATRIX_SESSION_ID")
        if not serial or not session_id:
            raise TikMatrixError(
                "TIKMATRIX_SERIAL / TIKMATRIX_SESSION_ID are not set. "
                "from_env() is for scripts started by TikMatrix as a custom script task; "
                "use TikMatrix(...).device(serial) to lease a device yourself."
            )
        client = cls(timeout=timeout)
        return Device(client, serial, session_id, DEFAULT_TTL_SECS, owns_session=False)


class Device:
    """A leased device.

    Use it as a context manager so the lease is released even when the script
    raises. While the block is open a background thread renews the lease.
    """

    def __init__(
        self,
        client: TikMatrix,
        serial: str,
        session_id: str,
        ttl_secs: int,
        owns_session: bool,
    ) -> None:
        self.client = client
        self.serial = serial
        self.session_id = session_id
        self.ttl_secs = ttl_secs
        self._owns_session = owns_session
        self._stop_heartbeat = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._start_heartbeat()

    # -- lifecycle --------------------------------------------------------

    def _start_heartbeat(self) -> None:
        def beat() -> None:
            interval = max(self.ttl_secs / 3.0, 5.0)
            while not self._stop_heartbeat.wait(interval):
                try:
                    self.client._request(
                        "POST",
                        f"/api/v1/rpc/session/{self.session_id}/heartbeat",
                        json={"ttl_secs": self.ttl_secs},
                    )
                except TikMatrixError:
                    # The lease is gone (released elsewhere, or the app
                    # restarted). Stop rather than retry forever; the next
                    # device call will surface the real error.
                    return

        self._heartbeat_thread = threading.Thread(target=beat, daemon=True)
        self._heartbeat_thread.start()

    def release(self) -> None:
        """Give the device back. Safe to call more than once."""
        self._stop_heartbeat.set()
        if self._owns_session:
            try:
                self.client._request("DELETE", f"/api/v1/rpc/session/{self.session_id}")
            except TikMatrixError:
                pass
            self._owns_session = False

    def __enter__(self) -> "Device":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.release()

    # -- raw channels -----------------------------------------------------

    def jsonrpc(self, method: str, params: Optional[List[Any]] = None, timeout: int = 10) -> Any:
        """Call a UIAutomator2 method directly."""
        return self.client._request(
            "POST",
            "/api/v1/rpc/jsonrpc",
            session_id=self.session_id,
            json={
                "serial": self.serial,
                "method": method,
                "params": params or [],
                "timeout": timeout,
            },
        )

    def adb(self, *args: str, timeout_ms: Optional[int] = None) -> str:
        """Run an ADB command, e.g. `d.adb("shell", "pm", "list", "packages")`."""
        body: Dict[str, Any] = {"serial": self.serial, "args": list(args)}
        if timeout_ms is not None:
            body["timeout_ms"] = timeout_ms
        return self.client._request(
            "POST", "/api/v1/rpc/adb", session_id=self.session_id, json=body
        )

    def hierarchy(self) -> str:
        """The current UI tree as XML."""
        return self.client._request(
            "GET",
            "/api/v1/rpc/hierarchy",
            session_id=self.session_id,
            params={"serial": self.serial},
            raw=True,
        ).decode("utf-8")

    def screenshot(self, path: Optional[str] = None) -> bytes:
        """PNG bytes of the screen, optionally written to `path`."""
        data = self.client._request(
            "GET",
            "/api/v1/rpc/screenshot",
            session_id=self.session_id,
            params={"serial": self.serial},
            raw=True,
        )
        if path:
            with open(path, "wb") as handle:
                handle.write(data)
        return data

    # -- conveniences -----------------------------------------------------

    def info(self) -> Dict[str, Any]:
        return self.jsonrpc("deviceInfo")

    def window_size(self) -> tuple:
        info = self.info()
        return info.get("displayWidth"), info.get("displayHeight")

    def click_xy(self, x: int, y: int) -> Any:
        return self.jsonrpc("click", [int(x), int(y)])

    def swipe(self, sx: int, sy: int, ex: int, ey: int, steps: int = 20) -> Any:
        return self.jsonrpc("swipe", [int(sx), int(sy), int(ex), int(ey), int(steps)])

    def press(self, key: str) -> Any:
        """Press a hardware key: back, home, recent, enter, ..."""
        return self.jsonrpc("pressKey", [key])

    def find(
        self,
        text: Optional[str] = None,
        resource_id: Optional[str] = None,
        description: Optional[str] = None,
        class_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Matching nodes, each with `text`, `resource-id`, `bounds`, `center`.

        Matching is done here against the dumped hierarchy rather than through
        a UIAutomator selector so that a miss can be debugged by printing
        `hierarchy()` — the same tree this searched.
        """
        root = ElementTree.fromstring(self.hierarchy())
        results: List[Dict[str, Any]] = []

        for node in root.iter("node"):
            if text is not None and node.get("text") != text:
                continue
            if resource_id is not None and node.get("resource-id") != resource_id:
                continue
            if description is not None and node.get("content-desc") != description:
                continue
            if class_name is not None and node.get("class") != class_name:
                continue

            bounds = _parse_bounds(node.get("bounds", ""))
            if bounds is None:
                continue
            left, top, right, bottom = bounds
            results.append(
                {
                    "text": node.get("text", ""),
                    "resource-id": node.get("resource-id", ""),
                    "content-desc": node.get("content-desc", ""),
                    "class": node.get("class", ""),
                    "bounds": bounds,
                    "center": ((left + right) // 2, (top + bottom) // 2),
                }
            )
        return results

    def wait_for(self, timeout: float = 10.0, interval: float = 1.0, **criteria: Any) -> Dict[str, Any]:
        """Block until an element matching `criteria` appears, then return it."""
        deadline = time.time() + timeout
        while True:
            matches = self.find(**criteria)
            if matches:
                return matches[0]
            if time.time() >= deadline:
                raise TikMatrixError(f"No element matched {criteria} within {timeout}s")
            time.sleep(interval)

    def click(self, timeout: float = 10.0, **criteria: Any) -> Dict[str, Any]:
        """Wait for an element and tap its centre."""
        element = self.wait_for(timeout=timeout, **criteria)
        self.click_xy(*element["center"])
        return element

    def exists(self, **criteria: Any) -> bool:
        return bool(self.find(**criteria))

    def input_text(self, text: str) -> str:
        """Type into the focused field using the bundled fast-input IME."""
        return self.adb("shell", "am", "broadcast", "-a", "ADB_INPUT_TEXT", "--es", "msg", text)


def _parse_bounds(raw: str) -> Optional[tuple]:
    # "[0,100][200,300]" -> (0, 100, 200, 300)
    try:
        first, second = raw.split("][")
        left, top = first.lstrip("[").split(",")
        right, bottom = second.rstrip("]").split(",")
        return int(left), int(top), int(right), int(bottom)
    except (ValueError, AttributeError):
        return None


def _error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return payload.get("message") or response.text
    except ValueError:
        pass
    return response.text
