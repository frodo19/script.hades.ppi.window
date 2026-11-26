"""The colours and the shape of the window: the settings of the add-on go into PlayerInfo.xml.

resources/template/PlayerInfo.tpl.xml has @@tokens@@ where a colour or a rounded texture goes; this makes
resources/skins/Default/1080i/PlayerInfo.xml from it each time the window opens (only when it changed).
"""
import os
import re

import xbmc
import xbmcaddon
import xbmcvfs

ID = 'script.hades.ppi.window'
MEDIA = 'special://home/addons/%s/resources/media/' % ID

TEXT = {
    't_main': 'EEF1F6', 't_label': '8C93A1', 't_value': 'B6BDC9', 't_section': 'A9B6CC',
    't_accent': 'FFDEB3', 't_warn': 'F2A23C', 't_spk_on': '0D0E12', 't_spk_off': '6C7482', 't_hgt_on': '0D0E12',
}
# token -> (setting prefix, default RRGGBB)
BACKGROUNDS = {
    'bg_main': ('bg_main', '0D0E12'), 'bg_card': ('bg_card', '1E2128'), 'bg_card2': ('bg_card2', '2A2E37'),
    'bg_box': ('bg_box', '14171C'), 'bg_btn': ('bg_btn', '15181E'), 'bg_sel': ('bg_sel', 'FFDEB3'),
    'bg_tab': ('bg_tab', '20242C'), 'bg_spk_on': ('bg_spk_on', 'FFDEB3'), 'bg_hgt_on': ('bg_hgt_on', '4FC3F7'), 'bg_spk_off': ('bg_spk_off', '0D0E12'),
}
BORDER = ('bg_border', '262A33')


def _hex(value):
    v = (value or '').strip().lstrip('#').upper()
    return v if re.fullmatch(r'[0-9A-F]{6}|[0-9A-F]{8}', v) else ''


def _argb(v, alpha=0xFF):
    return v if len(v) == 8 else '%02X%s' % (alpha, v)


def colour_map(addon):
    def pick(setting, default, custom_id=None):
        return _hex(addon.getSetting(custom_id or setting + '_custom')) or _hex(addon.getSetting(setting)) or default

    m = {tok: _argb(pick(tok, default)) for tok, default in TEXT.items()}
    for tok, (prefix, default) in BACKGROUNDS.items():
        v = pick(prefix + '_color', default, prefix + '_custom')
        try:
            p = int(addon.getSetting(prefix + '_alpha'))
        except ValueError:
            p = 100
        m[tok] = _argb(v, max(1, round(max(0, min(100, p)) * 255 / 100)))
    if addon.getSetting('round_panel') != 'false':
        m.update(sb=' border="12"', stex=MEDIA + 'round-small.png', pb=' border="24"', ptex=MEDIA + 'panel-round.png',
                 hl_l='26', hl_w='1708', rtex=MEDIA + 'panel-ring.png', rb=' border="24"')
    else:
        m.update(sb='', stex='colors-white.png', pb='', ptex='colors-white.png', hl_l='0', hl_w='1760',
                 rtex='colors-white.png', rb='')
        if not m['bg_main'].upper().startswith('FF'):
            m.update(rtex=MEDIA + 'panel-ring-sq.png', rb=' border="1"')
    if addon.getSetting('show_lines') == 'true':
        m.update(ln_top='66DBE6FF', ln_a='FFDBE6FF')
    else:
        m.update(ln_top='01000000', ln_a='01000000')
    m['bg_border'] = _argb(pick(BORDER[0] + '_color', BORDER[1], BORDER[0] + '_custom'))
    return m


def language(addon=None):
    """'hu' or 'en': the setting, or (automatic) the language of Kodi; anything but Hungarian is English."""
    addon = addon or xbmcaddon.Addon(ID)
    v = addon.getSetting('lang')
    if v in ('hu', 'en'):
        return v
    try:
        return 'hu' if xbmc.getLanguage(xbmc.ISO_639_1).lower().startswith('hu') else 'en'
    except Exception:  # the language of Kodi is not known
        return 'en'


def includes_file(path):
    return os.path.join(path, 'resources', 'skins', 'Default', '1080i',
                        'Includes.en.xml' if language() == 'en' else 'Includes.xml')


def generate(path):
    """Write PlayerInfo.xml from the template and the settings; returns True when it was written."""
    addon = xbmcaddon.Addon(ID)
    m = colour_map(addon)
    with open(os.path.join(path, 'resources', 'template', 'PlayerInfo.tpl.en.xml' if language(addon) == 'en' else 'PlayerInfo.tpl.xml'), encoding='utf-8') as f:
        text = f.read()
    text = re.sub(r'@@(\w+)@@', lambda g: m.get(g.group(1), ''), text)
    out = os.path.join(path, 'resources', 'skins', 'Default', '1080i', 'PlayerInfo.xml')
    try:
        with open(out, encoding='utf-8') as f:
            if f.read() == text:
                return False
    except OSError:
        pass
    with open(out, 'w', encoding='utf-8') as f:
        f.write(text)
    return True


RESET_KEEP = ('reset_look', 'lang')


def reset_look(path):
    """Colours, opacities, shape and lines back to the defaults."""
    with open(os.path.join(path, 'resources', 'settings.xml'), encoding='utf-8') as f:
        xml = f.read()
    addon = xbmcaddon.Addon(ID)
    n = 0
    for sid, default in re.findall(r'<setting id="(\w+)" type="(?:string|integer|boolean)" label="\d+"[^>]*>'
                                   r'<level>0</level><default>([^<]*)</default>', xml):
        if sid in RESET_KEEP or sid.startswith('web_') or sid == 'mdblist_key':
            continue
        addon.setSetting(sid, default)
        n += 1
    return n
