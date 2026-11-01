import logging

import wx
from kipy import KiCad

from kicad2cnc.ui.dialog import BoardInfoDialog


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    app = wx.App(False)
    dialog = BoardInfoDialog(KiCad(timeout_ms=2000))
    dialog.Show()
    app.SetTopWindow(dialog)
    wx.CallAfter(dialog.refresh_board)
    app.MainLoop()
    return 0
