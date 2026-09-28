from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import traceback
import warnings

import truststore

from constants import (
    FILE_FORMATTER,
    LOCK_PATH,
    LOG_PATH,
    LOGGING_LEVELS,
    OUTPUT_FORMATTER,
    SELF_PATH,
)
from exceptions import CaptchaRequired
from settings import Settings
from translate import _
from twitch import Twitch
from utils import lock_file
from version import __version__


class ParsedArgs(argparse.Namespace):
    _verbose: int
    _debug_ws: bool
    _debug_gql: bool
    log: bool
    dump: bool

    @property
    def logging_level(self) -> int:
        return LOGGING_LEVELS[min(self._verbose, 4)]

    @property
    def debug_ws(self) -> int:
        if self._debug_ws:
            return logging.DEBUG
        if self._verbose >= 4:
            return logging.INFO
        return logging.NOTSET

    @property
    def debug_gql(self) -> int:
        if self._debug_gql:
            return logging.DEBUG
        if self._verbose >= 4:
            return logging.INFO
        return logging.NOTSET


async def main(args: ParsedArgs, settings: Settings) -> int:
    if settings.logging_level > logging.DEBUG:
        logging.getLogger().addHandler(logging.NullHandler())
    logger = logging.getLogger("TwitchDrops")
    logger.setLevel(settings.logging_level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(OUTPUT_FORMATTER)
    logger.addHandler(handler)
    if settings.log:
        handler = logging.FileHandler(LOG_PATH)
        handler.setFormatter(FILE_FORMATTER)
        logger.addHandler(handler)
    logging.getLogger("TwitchDrops.gql").setLevel(settings.debug_gql)
    logging.getLogger("TwitchDrops.websocket").setLevel(settings.debug_ws)

    exit_status = 0
    client = Twitch(settings)
    loop = asyncio.get_running_loop()
    if sys.platform == "linux":
        loop.add_signal_handler(signal.SIGINT, lambda *_: client.gui.close())
        loop.add_signal_handler(signal.SIGTERM, lambda *_: client.gui.close())
    try:
        await client.run()
    except CaptchaRequired:
        exit_status = 1
        client.prevent_close()
        client.print(_("error", "captcha"))
    except Exception:
        exit_status = 1
        client.prevent_close()
        client.print("Fatal error encountered:\n")
        client.print(traceback.format_exc())
    finally:
        if sys.platform == "linux":
            loop.remove_signal_handler(signal.SIGINT)
            loop.remove_signal_handler(signal.SIGTERM)
        client.print(_("gui", "status", "exiting"))
        await client.shutdown()
    if not client.gui.close_requested:
        client.gui.tray.change_icon("error")
        client.print(_("status", "terminated"))
        client.gui.status.update(_("gui", "status", "terminated"))
    await client.gui.wait_until_closed()
    client.save(force=True)
    client.gui.stop()
    client.gui.close_window()
    return exit_status


if __name__ == "__main__":
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10 or higher is required")
    truststore.inject_into_ssl()
    warnings.simplefilter("default", ResourceWarning)

    parser = argparse.ArgumentParser(
        SELF_PATH.name,
        description="A program that allows you to mine timed drops on Twitch.",
    )
    parser.add_argument("--version", action="version", version=f"v{__version__}")
    parser.add_argument("-v", dest="_verbose", action="count", default=0)
    parser.add_argument("--log", action="store_true")
    parser.add_argument("--dump", action="store_true")
    parser.add_argument("--debug-ws", dest="_debug_ws", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--debug-gql", dest="_debug_gql", action="store_true", help=argparse.SUPPRESS
    )
    args = parser.parse_args(namespace=ParsedArgs())
    settings = Settings(args)

    success, file = lock_file(LOCK_PATH)
    try:
        if not success:
            sys.exit(3)
        sys.exit(asyncio.run(main(args, settings)))
    finally:
        file.close()
