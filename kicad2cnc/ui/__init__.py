"""Plugin dialogs."""

import logging
from pathlib import Path

import wx


def set_dialog_icon(dialog: wx.TopLevelWindow, filename: str = "cnc.png") -> None:
    path = Path(__file__).resolve().parents[2] / "icons" / filename
    icon = wx.Icon(str(path), wx.BITMAP_TYPE_PNG)
    if not icon.IsOk():
        logging.error("Could not load dialog icon: %s", path)
        return
    dialog.SetIcon(icon)
