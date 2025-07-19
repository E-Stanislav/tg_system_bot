#!/usr/bin/env python3
"""
Authentication module for Telegram Remote Monitoring & Management Bot
"""

import logging
from typing import Callable, Awaitable
from aiogram.types import Message, CallbackQuery

from core.config import ADMIN_ID_INT

logger = logging.getLogger("auth")

# ----------------------------------------------------------------------------
# Admin access control
# ----------------------------------------------------------------------------

def is_admin(user_id: int | None) -> bool:
    return user_id == ADMIN_ID_INT

def admin_only(func: Callable[[Message, ...], Awaitable[None]]):  # type: ignore[override]
    """Decorator to restrict commands to the configured admin.

    If a non-admin attempts to use a command, they receive a refusal message and the
    action is logged.
    """
    async def wrapper(message: Message, *args, **kwargs):
        user_id = message.from_user.id if message.from_user else None
        if not is_admin(user_id):
            logger.warning("Unauthorized access attempt from user_id=%s username=%s", 
                          user_id, message.from_user.username if message.from_user else None)
            await message.answer("❌ Доступ запрещён. Вы не являетесь администратором этого бота.")
            return
        return await func(message, *args, **kwargs)
    return wrapper

async def admin_only_callback(callback: CallbackQuery, *, silent: bool = False) -> bool:
    """Check admin for callback queries.

    Returns True if authorized, False otherwise.
    If not authorized, optionally send message unless silent=True.
    """
    user_id = callback.from_user.id if callback.from_user else None
    if not is_admin(user_id):
        logger.warning("Unauthorized callback attempt from user_id=%s username=%s", 
                      user_id, callback.from_user.username if callback.from_user else None)
        if not silent:
            await callback.answer("Доступ запрещён", show_alert=True)
        return False
    return True 