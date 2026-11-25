"""Read-mostly web server for a compatible mobile app (TinyPPI Mobile).

Independent implementation of the app's published HTTP/JSON interface
(/api/hello, /api/state, /api/stream, /api/history); the data comes from the
Hades's hades.* window properties and from Kodi's own info labels. No code or
artwork of the TinyPPI add-on is used. VS10 is not offered: hello reports it off.
"""
import json, re, secrets, threading, time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import xbmc

import lib, media

PROP = 'Window(Home).Property(%s)'
INTERVAL = 1.0
HEARTBEAT = 15.0
MAX_STREAMS = 6
def control_on():
    return lib.ADDON.getSetting('web_control') != 'false'


TOKEN_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # nincs I, O, 0, 1

# (group id, title, [(row id, label, [DV properties or info labels])])
# hades.* names are Window(Home) properties ('info:' = Kodi info label); labels are Hungarian here and translated by lib.T().
GROUPS = [
    ('source', 'Forrás', [
        ('layers', 'Rétegek', ['hades.dv.layers']),
        ('fel', 'FEL', ['hades.dv.fel']),
        ('colour', 'Színtér', ['hades.video.matrix']),
        ('mastering', 'Masterelés', ['hades.src.mastering']),
        ('light', 'Fényerő', ['hades.dv.source']),
        ('area', 'Képterület', ['hades.video.area']),
    ]),
    ('output', 'Kimenet', [
        ('display', 'Kimeneti felbontás', ['hades.out.modeplain']),
        ('intent', 'Kimeneti színtér', ['hades.dv.signal']),
        ('transport', 'Kimeneti konténer', ['hades.dv.transport']),
        ('committed', 'Adatfolyam / kép / revízió', ['hades.dv.sent']),
        ('precision', 'Framebuffer', ['hades.dv.depth']),
        ('stage', 'Kimeneti fokozat', ['hades.dv.step']),
    ]),
    ('mapping', 'Leképezés', [
        ('tvprofile', 'Kijelző-leképezés', ['hades.dv.mode']),
        ('trims', 'Kreatív trimmek', ['hades.dv.trims']),
        ('localcm4', 'Leképezési metaadat', ['hades.dv.cm']),
        ('engine', 'Motor', ['hades.dv.path']),
    ]),
    ('system', 'Rendszer', [
        ('cpu', 'CPU', ['info:System.CPUUsage']),
        ('memory', 'Memória', ['hades.sys.memorypct']),
        ('gpu', 'GPU render', ['hades.dv.gpu']),
    ]),
]

METADATA = [
    ('Dolby Vision blokkok', [
        ('Alkalmazott', 'hades.dv.lvused'), ('Elemzett', 'hades.dv.lvfile'),
        ('Továbbított', 'hades.dv.lvsent'), ('RPU', 'hades.dv.blocks'),
    ]),
    ('Fényerő és maszkolás', [
        ('L1 nit', 'hades.dv.l1'),
        ('L3', 'hades.dv.l3'), ('L4', 'hades.dv.l4'), ('L5', 'hades.dv.l5'), ('L9', 'hades.dv.l9'),
        ('L10', 'hades.dv.l10'), ('L11', 'hades.dv.l11'), ('Mastering', 'hades.src.mastering'),
    ]),
]


def _label(expr):
    return (xbmc.getInfoLabel(expr) or '').strip()


LAYERS = {
    'FEL': 'BL + EL (FEL)',
    'FELGAP': 'BL (FEL: a kiegészítő réteg újraszinkronizál)',
    'MEL': 'BL + EL (MEL)',
    'MELSKIP': 'BL + EL (MEL, nincs dekódolva)',  # van MEL, de a Hades nem dekódolja
    'BL': 'BL',
}


def _prop(name):
    value = _label(name[5:] if name.startswith('info:') else PROP % name)
    if name == 'hades.dv.layers' and value in LAYERS:
        return lib.T(LAYERS[value])
    return '' if value in ('N/A', 'n/a') else value


def _number(text):
    m = re.search(r'-?\d+(?:[.,]\d+)?', text or '')
    return float(m.group(0).replace(',', '.')) if m else None


def _numbers(text):
    return [float(x.replace(',', '.')) for x in re.findall(r'-?\d+(?:[.,]\d+)?', text or '')]


def _group_rows(rows):
    out = []
    for rid, label, props in rows:
        value = ''
        for p in props:
            value = _prop(p)
            if value:
                break
        if value:
            out.append({'id': rid, 'label': lib.T(label), 'value': value, 'detail': ''})
    return out


def _metadata():
    rows = []
    for title, items in METADATA:
        part = []
        for name, prop in items:
            value = _prop(prop)
            if value:
                part.append({'kind': 'row', 'name': lib.T(name), 'value': value})
        if part:
            rows.append({'kind': 'section', 'name': lib.T(title), 'value': ''})
            rows.extend(part)
    return rows


def _l1():
    text = _prop('hades.dv.l1')
    n = _numbers(text)
    if len(n) >= 3:
        return {'min': n[0], 'max': n[1], 'avg': n[2]}
    if len(n) == 2:
        return {'max': n[0], 'avg': n[1]}
    return {}


def build(seq):
    playing = xbmc.Player().isPlayingVideo() if xbmc.getCondVisibility('Player.HasVideo') else False
    if not playing:
        out = {'seq': seq, 'playing': False, 'paused': False, 'title': '',
               'groups': [], 'metadata': [], 'metrics': {}, 'library': media.LIB_REV}
        if control_on():
            out['controls'] = media.controls()
        return out
    hdr = _label('VideoPlayer.HdrType')
    snap = {
        'seq': seq,
        'playing': True,
        'paused': bool(xbmc.getCondVisibility('Player.Paused')),
        'title': _label('VideoPlayer.Title') or _label('Player.Filename'),
        'hdr_type': hdr,
        'effective': hdr,
        'output_type': _label('Player.Process(videooutputhdrtype)'),
        'time': _label('Player.Time'),
        'duration': _label('Player.Duration'),
        'finish': _label('Player.FinishTime'),
        'groups': [{'id': gid, 'title': lib.T(title), 'rows': _group_rows(rows)}
                   for gid, title, rows in GROUPS],
        'metadata': _metadata(),
        'media': {
            'year': _label('VideoPlayer.Year'),
            'genre': _label('VideoPlayer.Genre'),
            'show': _label('VideoPlayer.TVShowTitle'),
            'season': _label('VideoPlayer.Season'),
            'episode': _label('VideoPlayer.Episode'),
            'plot': _label('VideoPlayer.Plot'),
        },
    }
    snap['groups'] = [g for g in snap['groups'] if g['rows']]
    ag = media.audio_group()
    if ag:
        snap['groups'].append(ag)
    snap['art'] = {'poster': media.tag(media.playing_art('poster')),
                   'fanart': media.tag(media.playing_art('fanart'))}
    dbid, dbtype = _label('VideoPlayer.DBID'), _label('VideoPlayer.DBType')
    if dbid.isdigit() and int(dbid) > 0 and dbtype in ('movie', 'episode'):
        snap['media']['item'] = {'kind': dbtype, 'id': int(dbid)}
        snap['media'].update(media.playing_extras(dbtype, int(dbid)))
    metrics = {}
    l1 = _l1()
    if l1:
        metrics['l1'] = l1
    for key, expr in (('aspect', 'VideoPlayer.VideoAspect'),
                      ('fps_in', 'Player.Process(videofps)'),
                      ('progress', 'Player.Progress'),
                      ('cpu', 'System.CPUUsage'),
                      ('cpu_temp', 'System.CPUTemperature'),
                      ('memory', 'System.Memory(used.percent)'),
                      ('cache', 'Player.CacheLevel')):
        n = _number(_label(expr))
        if n is not None:
            metrics[key] = n
    try:
        fw, fh = int(_label('Player.Process(videowidth)') or 0), int(_label('Player.Process(videoheight)') or 0)
        if fw > 0 and fh > 0:
            metrics['frame'] = {'w': fw, 'h': fh}
    except ValueError:
        pass
    snap['metrics'] = metrics
    snap['library'] = media.LIB_REV
    if control_on():
        snap['controls'] = media.controls()
    return snap


class Producer:
    """Cached snapshot: several clients do not load Kodi repeatedly."""
    def __init__(self):
        self.lock = threading.Lock()
        self.seq = 0
        self.at = 0.0
        self.snap = {'seq': 0, 'playing': False}

    def fresh(self):
        with self.lock:
            if time.monotonic() - self.at > 0.4:
                self.seq += 1
                try:
                    self.snap = build(self.seq)
                except Exception as e:  # the client must not see the error
                    lib.log('web: snapshot error: %s' % e, xbmc.LOGWARNING)
                self.at = time.monotonic()
            return dict(self.snap)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port, token):
        super().__init__(('0.0.0.0', port), Handler)
        self.token = token
        self.producer = Producer()
        self.stop_event = threading.Event()
        self.streams = 0
        self.streams_lock = threading.Lock()


READ_ROUTES = ('/api/state', '/api/stream', '/api/history', '/api/art', '/api/library',
               '/api/series', '/api/episodes', '/api/continue', '/api/details')


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'hades-ppi'

    def log_message(self, fmt, *args):
        pass

    def _json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self, query):
        offered = (self.headers.get('X-TinyPPI-Token', '') or
                   (query.get('token') or [''])[0]).strip().upper()
        ok = secrets.compare_digest(offered.encode('utf-8', 'replace'),
                                    self.server.token.encode('utf-8'))
        if not ok:
            self._json({'error': 'token required'}, HTTPStatus.UNAUTHORIZED)
        return ok

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        route = url.path
        if route == '/api/hello':
            self._json({'name': 'Hades PPI', 'version': lib.ADDON.getAddonInfo('version'),
                        'auth_read': True, 'control': control_on(),
                        'library': control_on(), 'series': control_on(), 'interval_ms': int(INTERVAL * 1000),
                        'strings': {}})
            return
        if route not in READ_ROUTES:
            self._json({'error': 'no such route'}, HTTPStatus.NOT_FOUND)
            return
        if not self._authorised(query):
            return
        if route == '/api/state':
            snap = self.server.producer.fresh()
            snap['control'] = control_on()
            snap['streams_full'] = self.server.streams >= MAX_STREAMS
            self._json(snap)
        elif route == '/api/history':
            self._json({'now': 0.0, 'step': 1.0, 't': [], 'max': [], 'avg': [],
                        'events': [], 'seq': 0, 'switches': 0})
        elif route == '/api/stream':
            self._stream()
        elif route == '/api/art':
            self._art(query)
        elif not control_on():
            self._json({'error': 'control disabled'}, HTTPStatus.FORBIDDEN)
        elif route == '/api/library':
            self._json(media.movies())
        elif route == '/api/series':
            self._json(media.shows())
        elif route == '/api/episodes':
            sid = (query.get('tvshowid') or [''])[0]
            self._json(media.episodes(int(sid))) if sid.isdigit() else \
                self._json({'error': 'tvshowid required'}, HTTPStatus.BAD_REQUEST)
        elif route == '/api/continue':
            self._json(media.continuing())
        elif route == '/api/details':
            data = media.details(query)
            self._json(data) if data else self._json({'error': 'not found'}, HTTPStatus.NOT_FOUND)

    def _art(self, query):
        kind = (query.get('kind') or [''])[0]
        if kind not in ('poster', 'fanart', 'thumb') or (query.get('portrait') or [''])[0]:
            self._json({'error': 'no such artwork'}, HTTPStatus.NOT_FOUND)
            return
        found = media.read_picture(media.item_art(kind, query))
        if not found:
            self._json({'error': 'no artwork'}, HTTPStatus.NOT_FOUND)
            return
        body, ctype = found
        has_tag = bool((query.get('v') or [''])[0])
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'private, max-age=604800, immutable' if has_tag else 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(min(length, 65536)) if length else b''
        route = urlparse(self.path).path
        try:
            body = json.loads(raw.decode('utf-8')) if raw else {}
        except ValueError:
            body = None
        if not isinstance(body, dict):
            self._json({'error': 'bad json'}, HTTPStatus.BAD_REQUEST)
            return
        if route not in ('/api/command', '/api/play', '/api/watched', '/api/resume', '/api/mode'):
            self._json({'error': 'no such route'}, HTTPStatus.NOT_FOUND)
            return
        if not control_on() or route == '/api/mode':
            self._json({'error': 'control disabled'}, HTTPStatus.FORBIDDEN)
            return
        if not self._authorised({}):
            return
        if route == '/api/command':
            action = str(body.get('action', '')).strip()
            ok = media.command(action, body.get('value'))
        elif route == '/api/play':
            action, ok = 'play', media.play(body)
        elif route == '/api/watched':
            action, ok = 'watched', media.set_watched(body)
        else:
            action, ok = 'resume', media.clear_resume(body)
        if ok:
            self._json({'ok': True, 'action': action})
        else:
            self._json({'error': 'command failed'}, HTTPStatus.BAD_REQUEST)

    def _stream(self):
        srv = self.server
        with srv.streams_lock:
            if srv.streams >= MAX_STREAMS:
                self._json({'error': 'too many streams'}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            srv.streams += 1
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()
            self.close_connection = True
            self.connection.settimeout(10)
            last, beat = None, time.monotonic()
            while not srv.stop_event.is_set():
                snap = srv.producer.fresh()
                snap['control'] = control_on()
                key = json.dumps({k: v for k, v in snap.items() if k != 'seq'},
                                 sort_keys=True, ensure_ascii=False)
                now = time.monotonic()
                if key != last:
                    last, beat = key, now
                    data = json.dumps(snap, ensure_ascii=False)
                    self.wfile.write(('event: state\ndata: %s\n\n' % data).encode('utf-8'))
                    self.wfile.flush()
                elif now - beat >= HEARTBEAT:
                    beat = now
                    self.wfile.write(b': ping\n\n')
                    self.wfile.flush()
                srv.stop_event.wait(INTERVAL)
            self.wfile.write(b'event: bye\ndata: {"retry_ms": 20000}\n\n')
            self.wfile.flush()
        except (OSError, ValueError):
            pass
        finally:
            with srv.streams_lock:
                srv.streams -= 1


class Web:
    """Start/stop the server according to the settings."""
    def __init__(self):
        self.server = None
        self.thread = None

    def token(self):
        t = (lib.ADDON.getSetting('web_token') or '').strip().upper()
        if not re.fullmatch('[%s]{8}' % TOKEN_ALPHABET, t):
            t = ''.join(secrets.choice(TOKEN_ALPHABET) for _ in range(8))
            lib.ADDON.setSetting('web_token', t)
        return t

    def stop(self):
        if self.server:
            self.server.stop_event.set()
            self.server.shutdown()
            self.server.server_close()
            lib.log('web: stopped')
        self.server = self.thread = None

    def apply(self):
        self.stop()
        if lib.ADDON.getSetting('web_enabled') != 'true':
            return
        try:
            port = int(lib.ADDON.getSetting('web_port') or 8099)
            self.server = Server(port, self.token())
        except (OSError, ValueError) as e:
            lib.log('web: cannot start: %s' % e, xbmc.LOGERROR)
            self.server = None
            return
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        lib.log('web: fut a %d porton' % port)
