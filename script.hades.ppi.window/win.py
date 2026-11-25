import threading

import xbmc
import xbmcaddon
import xbmcgui
import hvars
import look

ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92
PROP = 'hades_ppi_window.open'
SHOW = 'hades_ppi_window.show'
CLOSE = 'hades_ppi_window.close'  # set by the buttons that open a list: the window goes first
STARTING = 'hades_ppi_window.starting'  # a press is opening the window already (a quick second press is ignored)
# The core of Hades publishes the hades.* properties only while a player information window is shown,
# or while this property of the Home window is 1 (meant for add-ons; the GPU readings are not part of it).
CHECK = 'hades.check.running'
# the keys that open the window close it too: O, and the key of the keymap files that is bound to it.
# The Down arrow is not here: it moves to the buttons below, and closes the window from the last one (see the template).
KEYS = (0xF04F, 0xF06F)

# The window takes the keys while it is shown; the ones the video would use are passed on.
FORWARD = {
    12: 'PlayerControl(Play)', 13: 'PlayerControl(Stop)',
    79: 'PlayerControl(Play)', 229: 'PlayerControl(Play)',
}

CURRENT = None
VARS = None
_logged = 0


def _home():
    return xbmcgui.Window(10000)


class Win(xbmcgui.WindowXMLDialog):
    def onInit(self):
        _home().setProperty(PROP, 'true')

    def onAction(self, action):
        global _logged
        aid = action.getId()
        if _logged < 30:
            _logged += 1
            xbmc.log('script.hades.ppi.window: action %s, button %s' % (aid, hex(action.getButtonCode())), xbmc.LOGINFO)
        if aid in (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK) or action.getButtonCode() in KEYS:
            self.close()
        elif aid in FORWARD:
            xbmc.executebuiltin(FORWARD[aid])
        else:
            super().onAction(action)


def close_current():
    if CURRENT is not None:
        try:
            CURRENT.close()
        except Exception:  # the window is already gone
            pass


def is_open():
    return bool(_home().getProperty(PROP))


def _aspect(home):
    # the row "Video aspect" is shown only when it differs from the displayed aspect ratio
    def num(label):
        try:
            return round(float(xbmc.getInfoLabel(label).replace(',', '.')), 2)
        except ValueError:
            return None
    a, b = num('Player.Process(videodar)'), num('VideoPlayer.VideoAspect')
    if b is not None and a != b:
        home.setProperty('hppi.aspdiff', '1')
    else:
        home.clearProperty('hppi.aspdiff')


def _speakers(home):
    # hppi.spk is hades.audio.spk; for Atmos / DTS:X (objects, passthrough) the four height channels are added, if the setting says so
    spk = home.getProperty('hades.audio.spk')
    codec = xbmc.getInfoLabel('VideoPlayer.AudioCodec')
    if spk and xbmcaddon.Addon(look.ID).getSetting('atmos_heights') != 'false' \
            and (codec in ('truehd_atmos', 'eac3_ddp_atmos') or codec.startswith('dtshd_ma_x')):
        for ch in ('TFL', 'TFR', 'TBL', 'TBR'):
            if ';%s;' % ch not in spk:
                spk = spk.rstrip(';') + ';%s;' % ch
    if spk:
        home.setProperty('hppi.spk', spk)
    else:
        home.clearProperty('hppi.spk')


def _watch(w):
    # the window goes when the video ends
    mon = xbmc.Monitor()
    n = 0
    while not mon.waitForAbort(0.03):
        if CURRENT is not w:
            return
        n += 1
        if xbmc.getCondVisibility('Window.IsActive(seekbar)'):
            # the core opens it on left/right: it only goes away, nothing is seeked
            xbmc.executebuiltin('Dialog.Close(seekbar,true)')
        if n % 16 == 0 and VARS is not None:
            VARS.publish(_home())  # the variables of the window, twice a second
            _aspect(_home())
            _speakers(_home())
        if _home().getProperty(CLOSE):
            close_current()
            return
        if not xbmc.getCondVisibility('Player.HasVideo'):
            close_current()
            return


def _gpu():
    # AMD (amdgpu): the load and the temperature from sysfs; the core of Hades gives them only to its own windows
    import glob
    load = temp = ''
    try:
        for f in glob.glob('/sys/class/drm/card*/device/gpu_busy_percent'):
            load = open(f).read().strip()
            break
        for f in glob.glob('/sys/class/drm/card*/device/hwmon/hwmon*/temp1_input'):
            temp = str(int(open(f).read().strip()) // 1000) + '\u00b0C'
            break
    except Exception:
        pass
    return load, temp


def _gpu_loop(w):
    mon = xbmc.Monitor()
    home = _home()
    while not mon.waitForAbort(1.0):
        if CURRENT is not w:
            return
        load, temp = _gpu()
        if load or temp:
            home.setProperty('hades.sys.gpuread', '1')
            home.setProperty('hades.sys.gpu', load)
            home.setProperty('hades.sys.gputemp', temp)


def show(path):
    global VARS
    """Open the window and keep it until it is closed (blocks)."""
    global CURRENT
    if is_open():
        close_current()
        return
    if _home().getProperty(STARTING):
        return
    _home().setProperty(STARTING, 'true')
    xbmc.log('script.hades.ppi.window: window opened', xbmc.LOGINFO)
    w = None
    try:
        look.generate(path)
        VARS = hvars.Vars(look.includes_file(path))
        _home().setProperty(CHECK, '1')
        xbmc.sleep(500)  # the core publishes its values; then the variables are worked out from them
        VARS.publish(_home())
        _aspect(_home())
        _speakers(_home())
        w = Win('PlayerInfo.xml', path, 'Default', '1080i')
        CURRENT = w
        _home().setProperty(CHECK, '1')
        _home().setProperty(SHOW, 'true')
        threading.Thread(target=_watch, args=(w,), daemon=True).start()
        threading.Thread(target=_gpu_loop, args=(w,), daemon=True).start()
        w.doModal()
    finally:
        CURRENT = None
        if VARS is not None:
            VARS.clear(_home())
        for name in (PROP, SHOW, CHECK, STARTING, CLOSE, 'hades.sys.gpuread', 'hades.sys.gpu', 'hades.sys.gputemp', 'hppi.aspdiff', 'hppi.spk'):
            _home().clearProperty(name)
        del w
