from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from twitch import Twitch


class HeadlessLoginForm:
    def __init__(self):
        pass

    async def ask_enter_code(self, verification_uri, user_code: str):
        print(f"Please visit {verification_uri} and enter the code: {user_code}")
        print("Waiting for activation...")

    def update(self, message: str, user_id: int | None = None):
        print(f"Login: {message}")

    def close(self):
        pass


class HeadlessTray:
    def change_icon(self, icon: str):
        print(f"Tray icon: {icon}")


class HeadlessStatus:
    def update(self, message: str):
        print(f"Status: {message}")


class HeadlessGUIManager:
    def __init__(self, twitch: Twitch):
        self.twitch = twitch
        self.login = HeadlessLoginForm()
        self.tray = HeadlessTray()
        self.status = HeadlessStatus()
        self.close_requested = False

    def start(self):
        print("Starting headless mode")

    def print(self, message: str):
        print(message)

    def close(self):
        self.close_requested = True
        print("Closing headless mode")

    def set_games(self, games):
        print(f"Games set: {len(games)} games")

    async def coro_unless_closed(self, coro):
        if self.close_requested:
            from exceptions import ExitRequest
            raise ExitRequest()
        return await coro

    async def wait_until_closed(self):
        # In headless, never close unless interrupted
        await asyncio.sleep(1)

    def grab_attention(self, sound: bool = False):
        print("Attention grabbed")

    def stop(self):
        print("Stopping headless GUI")

    def close_window(self):
        print("Window closed")