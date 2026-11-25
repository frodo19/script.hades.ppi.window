import sys
import time

import xbmc
import xbmcaddon

import win

PATH = xbmcaddon.Addon().getAddonInfo('path')
# the buttons of the window that open a list of Hades: the window goes first, then the list opens over the video
LISTS = {'dvoutput': 'PlayerControl(HadesDVOutput)', 'upscaler': 'PlayerControl(HadesUpscaler)'}

arg = sys.argv[1] if len(sys.argv) > 1 else ''
if arg == 'reset':
    import xbmcgui
    import look
    L = xbmcaddon.Addon().getLocalizedString
    if xbmcgui.Dialog().yesno('Hades PPI window', L(32064)):
        xbmc.executebuiltin('Dialog.Close(addonsettings,true)')
        look.reset_look(PATH)
        xbmcgui.Dialog().notification('Hades PPI window', L(32063), xbmcgui.NOTIFICATION_INFO, 3000)
    sys.exit()
if arg in LISTS:
    win._home().setProperty(win.CLOSE, 'true')
    for _ in range(30):  # up to 3 s for the window to close
        if not win.is_open():
            break
        xbmc.sleep(100)
    xbmc.executebuiltin(LISTS[arg])
elif arg == 'restore':
    # the window goes first, Hades asks (and restores), then the window comes back
    win._home().setProperty(win.CLOSE, 'true')
    for _ in range(30):
        if not win.is_open():
            break
        xbmc.sleep(100)
    xbmc.executebuiltin('PlayerControl(HadesRestorePicture)')
    for _ in range(20):  # up to 2 s for its question to appear
        if xbmc.getCondVisibility('System.HasModalDialog'):
            break
        xbmc.sleep(100)
    while xbmc.getCondVisibility('System.HasModalDialog') and not xbmc.Monitor().abortRequested():
        xbmc.sleep(200)
    if xbmc.getCondVisibility('Player.HasVideo'):
        win.show(PATH)
else:
    # the key that opened the player information (or by hand, from Programs): this window, directly
    win.show(PATH)
