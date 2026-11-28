import math
import re
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

# Per-core CPU load for skins, the same Window(Home) properties as service.cb1.ppi:
#   cb1.cores  = '| 18 | 24 | 02 |'   cb1.coresc = '18|24|02' (compact)   cb1.cpu = '14%' (average)
CPU_VALUE_COLOUR = 'FFFFFFFF'   # busy cores
CPU_ZERO_COLOUR = 'FF808080'    # idle cores (00)
CPU_SEP_COLOUR = '80FFFFFF'     # separator of the compact line (white, 50 % opaque)
CPU_PROPS = ('cb1.cores', 'cb1.coresc', 'cb1.cpu')
_CORE = re.compile(r'#(\d+):\s*([^%\s]+)%')
_last = {}


def core_loads(raw):
    """Per-core load from System.CpuUsage; a nan core keeps its last value."""
    out = []
    for core, val in _CORE.findall(raw or ''):
        try:
            v = float(val)
        except ValueError:
            continue
        i = int(core)
        if math.isfinite(v):
            v = max(0.0, min(v, 100.0))
            _last[i] = v
        elif i in _last:
            v = _last[i]
        else:
            continue
        out.append(v)
    return out


def clear_cpu(home):
    for k in CPU_PROPS:
        home.clearProperty(k)


def publish_cpu(home):
    loads = core_loads(xbmc.getInfoLabel('System.CpuUsage'))
    if not loads:
        clear_cpu(home)
        return
    two = []
    for v in loads:
        t = '%02d' % min(int(v), 99)
        col = CPU_ZERO_COLOUR if t == '00' else CPU_VALUE_COLOUR
        two.append('[COLOR %s]%s[/COLOR]' % (col, t))
    home.setProperty('cb1.cores', '| ' + ' | '.join(two) + ' |')
    home.setProperty('cb1.coresc', ('[COLOR %s]|[/COLOR]' % CPU_SEP_COLOUR).join(two))
    home.setProperty('cb1.cpu', '%d%%' % round(sum(loads) / len(loads)))


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
        try:
            if lib.ADDON.getSetting('cpu_props') != 'false':
                publish_cpu(home)
            else:
                clear_cpu(home)
        except Exception as e:
            lib.log('cpu property error: %s' % e, xbmc.LOGWARNING)
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
    clear_cpu(home)
    if held:
        home.clearProperty('hades.check.running')


main()
