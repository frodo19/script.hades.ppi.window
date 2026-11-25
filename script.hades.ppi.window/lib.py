"""The little the web server needs: settings, logging, label translation."""
import xbmc
import xbmcaddon

import look
import strings_en

ID = 'script.hades.ppi.window'
ADDON = xbmcaddon.Addon(ID)


def log(msg, level=xbmc.LOGINFO):
    xbmc.log('script.hades.ppi.window: ' + msg, level)


def T(text):
    """Label of the mobile app (the source is Hungarian); English when the add-on language is English."""
    if look.language(ADDON) == 'en':
        return strings_en.APP.get(text, text)
    return text
