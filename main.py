#!/usr/bin/env python3
"""
Compatibility shim for legacy entrypoint.
Runs the bot from bot.py.
"""

from bot import main
import asyncio


if __name__ == "__main__":
    asyncio.run(main())


