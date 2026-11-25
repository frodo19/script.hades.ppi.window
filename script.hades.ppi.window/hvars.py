"""The skin variables of the window, worked out here.

Kodi reads the variables ($VAR) of a window only from the skin that is on, not from the add-on's own
Includes.xml. So the add-on works each one out itself (the same conditions, the same texts) and puts the
result in a property of the Home window, which PlayerInfo.xml reads. No file of the skin is needed.
"""
import xml.etree.ElementTree as ET
import xbmc

PREFIX = 'hppi.'


def _close(s, i):
    """The index of the ] that closes the [ at i."""
    depth = 0
    while i < len(s):
        if s[i] == '[':
            depth += 1
        elif s[i] == ']':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _split(s):
    """Split on the commas outside of brackets and of the parentheses of a function (Window(Home)...)."""
    out, depth, cur, prev = [], 0, '', ''
    for ch in s:
        if ch == '[' or (ch == '(' and (prev.isalnum() or prev in '._')):
            depth += 1
        elif (ch == ']' or ch == ')') and depth > 0:
            depth -= 1
        if ch == ',' and depth == 0:
            out.append(cur)
            cur = ''
        else:
            cur += ch
        prev = ch
    out.append(cur)
    return out


class Vars:
    def __init__(self, path):
        self.vars, self.maps = {}, {}
        for el in ET.parse(path).getroot().iter():
            if el.tag == 'variable':
                self.vars[el.get('name')] = [(v.get('condition'), v.text or '') for v in el.findall('value')]
            elif el.tag == 'map':
                self.maps[el.get('name')] = (el.get('ref'), {e.get('key'): e.text or '' for e in el.findall('entry')})
        self.cache = {}

    def _map(self, name, key):
        while name in self.maps:
            ref, entries = self.maps[name]
            if key in entries:
                return entries[key]
            name = ref
        return ''

    def expand(self, s):
        out, i = '', 0
        while i < len(s):
            if s[i] != '$':
                out += s[i]
                i += 1
                continue
            if s.startswith('$COMMA', i):
                out += ','
                i += 6
                continue
            br = s.find('[', i)
            name = s[i + 1:br] if br > 0 else ''
            end = _close(s, br) if br > 0 else -1
            if name not in ('INFO', 'VAR', 'MAP', 'LOCALIZE') or end < 0:
                out += s[i]
                i += 1
                continue
            args = _split(s[br + 1:end])
            i = end + 1
            if name == 'INFO':
                val = xbmc.getInfoLabel(args[0].strip())
                if val:
                    val = (self.expand(args[1]) if len(args) > 1 else '') + val + \
                        (self.expand(args[2]) if len(args) > 2 else '')
            elif name == 'VAR':
                val = self.value(args[0].strip())
                if val:
                    val = (args[1] if len(args) > 1 else '') + val + (args[2] if len(args) > 2 else '')
            elif name == 'MAP':
                val = self._map(args[0].strip(), xbmc.getInfoLabel(args[1].strip()))
            else:
                try:
                    val = xbmc.getLocalizedString(int(args[0]))
                except ValueError:
                    val = ''
            out += val
        return out

    def value(self, name):
        if name in self.cache:
            return self.cache[name]
        self.cache[name] = ''  # a loop would end here
        res = ''
        for cond, text in self.vars.get(name, []):
            if not cond or xbmc.getCondVisibility(cond):
                res = self.expand(text)
                break
        self.cache[name] = res
        return res

    def publish(self, home):
        self.cache = {}
        for name in self.vars:
            val = self.value(name)
            if home.getProperty(PREFIX + name) != val:
                home.setProperty(PREFIX + name, val)

    def clear(self, home):
        for name in self.vars:
            home.clearProperty(PREFIX + name)
