import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

import lib
import web

# Versions before 0.0.25 wrote a keymap file of their own; it is removed once (the key is set in the
# Keymap Editor now: Action RunScript(script.hades.ppi.window)).
OLD = 'special://profile/keymaps/hades_ppi_window.xml'

p = xbmcvfs.translatePath(OLD)
if xbmcvfs.exists(p):
    xbmcvfs.delete(p)
    xbmc.log('script.hades.ppi.window: old keymap file removed', xbmc.LOGINFO)

WEB = web.Web()


class Mon(xbmc.Monitor):
    pending = 0.0

    def onNotification(self, sender, method, data):
        if method.startswith('VideoLibrary.On'):
            import media
            media.bump()

    def onSettingsChanged(self):
        self.pending = time.time()


def main():
    mon = Mon()
    lib.ADDON = xbmcaddon.Addon(lib.ID)
    WEB.apply()
    home = xbmcgui.Window(10000)
    held = False   # hades.check.running is ours: the Hades core publishes its values while it is set
    while not mon.waitForAbort(1.0):
        want = lib.ADDON.getSetting('web_enabled') == 'true' and xbmc.getCondVisibility('Player.HasVideo')
        if want and not held:
            home.setProperty('hades.check.running', '1')
            held = True
        elif not want and held:
            held = False
            if not home.getProperty('hades_ppi_window.open'):  # the window of the add-on keeps it while it is open
                home.clearProperty('hades.check.running')
        if mon.pending and time.time() - mon.pending > 1.2:
            mon.pending = 0.0
            try:
                lib.ADDON = xbmcaddon.Addon(lib.ID)  # fresh settings
                WEB.apply()
            except Exception as e:
                lib.log('web apply error: %s' % e, xbmc.LOGWARNING)
    WEB.stop()
    if held:
        home.clearProperty('hades.check.running')


main()
