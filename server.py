#!/usr/bin/env python3
"""Passerelle v2 — service partagé : front + API REST + relais Atlassian.

Un seul processus Python standard (aucun paquet à installer) :
- sert index.html (le front bascule automatiquement en mode serveur) ;
- API REST sur SQLite (WAL) : référentiel commun, concurrence optimiste
  (révision par fiche, 409 en cas de conflit), flux temps réel SSE ;
- identité déléguée au SSO d'entreprise : oauth2-proxy (ou équivalent)
  transmet l'utilisateur en en-têtes HTTP — l'outil ne gère aucun mot de passe ;
- rôles : admin / contributeur / lecteur ;
- relais Atlassian intégré (réutilise la liste blanche de relay.py) ;
- exploitation : /healthz, /metrics (Prometheus), logs JSON,
  sauvegarde SQLite quotidienne compressée avec rétention.

Usage :
    DATA_DIR=/data ADMIN_EMAILS=chef@exemple.fr \
    ATL_SITE=https://xxx.atlassian.net ATL_EMAIL=svc@exemple.fr ATL_TOKEN=… \
    python3 server.py --host 0.0.0.0 --port 8080

Variables d'environnement :
    DATA_DIR            répertoire des données (défaut ./data)
    ADMIN_EMAILS        e-mails administrateurs (CSV)
    WRITE_EMAILS        e-mails contributeurs (CSV) — vide = tout utilisateur
                        authentifié est contributeur ; sinon les autres sont lecteurs
    AUTH_MODE           header (défaut : identité exigée en en-têtes) | none (POC : admin anonyme)
    AUTH_EMAIL_HEADER   défaut X-Auth-Request-Email
    AUTH_NAME_HEADER    défaut X-Auth-Request-Preferred-Username
    ATL_SITE/ATL_EMAIL/ATL_TOKEN   intégration Atlassian (optionnelle)
    BACKUP_KEEP         nombre de sauvegardes conservées (défaut 14)

Sécurité : à placer derrière oauth2-proxy + reverse proxy TLS ; le serveur fait
confiance aux en-têtes d'identité, il ne doit donc être joignable QUE par le proxy.
"""
import argparse
import base64
import glob
import gzip
import json
import os
import queue
import shutil
import sqlite3
import sys
import threading
import time
import urllib.error
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

import relay  # liste blanche Atlassian, en-têtes relayés, opener sans redirection

VERSION = '2.0.0'
MAX_DOC = 512 * 1024          # taille maximale d'une fiche (JSON)
MAX_IMPORT = 20 * 1024 * 1024  # taille maximale d'un import complet
ROLES = ('admin', 'contributeur', 'lecteur')

CONF = {}


def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def env(k, d=''):
    return os.environ.get(k, d)


def load_conf(args):
    data_dir = os.path.abspath(env('DATA_DIR', './data'))
    os.makedirs(os.path.join(data_dir, 'backups'), exist_ok=True)
    conf = dict(
        data_dir=data_dir,
        db=os.path.join(data_dir, 'passerelle.db'),
        app=os.path.abspath(args.app),
        auth_mode=env('AUTH_MODE', 'header'),
        h_email=env('AUTH_EMAIL_HEADER', 'X-Auth-Request-Email'),
        h_name=env('AUTH_NAME_HEADER', 'X-Auth-Request-Preferred-Username'),
        admins={e.strip().lower() for e in env('ADMIN_EMAILS', '').split(',') if e.strip()},
        writers={e.strip().lower() for e in env('WRITE_EMAILS', '').split(',') if e.strip()},
        atl_site=env('ATL_SITE', '').rstrip('/'),
        atl_auth='',
        backup_keep=max(1, int(env('BACKUP_KEEP', '14') or 14)),
    )
    if not os.path.isfile(conf['app']):
        sys.exit('Application introuvable : ' + conf['app'])
    if conf['atl_site']:
        if not (env('ATL_EMAIL') and env('ATL_TOKEN')):
            sys.exit('ATL_SITE est défini mais ATL_EMAIL / ATL_TOKEN manquent.')
        conf['atl_auth'] = 'Basic ' + base64.b64encode(
            (env('ATL_EMAIL') + ':' + env('ATL_TOKEN')).encode()).decode()
    if conf['auth_mode'] not in ('header', 'none'):
        sys.exit('AUTH_MODE doit valoir header ou none.')
    if conf['auth_mode'] == 'none':
        print('AVERTISSEMENT : AUTH_MODE=none — aucune identité exigée (POC uniquement, '
              'tout visiteur est administrateur anonyme).', file=sys.stderr, flush=True)
    return conf


# ---------- Base de données ----------

def db():
    c = sqlite3.connect(CONF['db'], timeout=15)
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA busy_timeout=8000')
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS platforms(
          id TEXT PRIMARY KEY, rev INTEGER NOT NULL, json TEXT NOT NULL,
          updated_at TEXT NOT NULL, updated_by TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS docs(
          key TEXT PRIMARY KEY, rev INTEGER NOT NULL, json TEXT NOT NULL,
          updated_at TEXT NOT NULL, updated_by TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit(
          seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, user TEXT NOT NULL,
          action TEXT NOT NULL, target TEXT, name TEXT, rev INTEGER);
        ''')
        defaults = (
            ('teams', '[]'),
            ('settings', json.dumps({'readyThreshold': 90, 'dmexLabel': 'asset-dip', 'siteUrl': ''})),
        )
        for key, val in defaults:
            c.execute('INSERT OR IGNORE INTO docs(key,rev,json,updated_at,updated_by) VALUES(?,1,?,?,?)',
                      (key, val, now(), 'système'))


def audit(user, action, target='', name='', rev=None):
    try:
        with db() as c:
            c.execute('INSERT INTO audit(ts,user,action,target,name,rev) VALUES(?,?,?,?,?,?)',
                      (now(), user, action, target, name, rev))
    except sqlite3.Error:
        pass


# ---------- Diffusion temps réel (SSE) ----------

SSE_CLIENTS = set()
SSE_LOCK = threading.Lock()


def broadcast(ev):
    data = json.dumps(ev, ensure_ascii=False)
    with SSE_LOCK:
        clients = list(SSE_CLIENTS)
    for q in clients:
        try:
            q.put_nowait(data)
        except queue.Full:
            pass


# ---------- Métriques ----------

MET = {'req': {}, 'atl': {}, 'started': time.time()}
MET_LOCK = threading.Lock()


def met_count(bucket, key):
    with MET_LOCK:
        MET[bucket][key] = MET[bucket].get(key, 0) + 1


def render_metrics():
    lines = [
        '# HELP passerelle_info Version du service',
        '# TYPE passerelle_info gauge',
        'passerelle_info{version="%s"} 1' % VERSION,
        '# TYPE passerelle_uptime_seconds gauge',
        'passerelle_uptime_seconds %d' % int(time.time() - MET['started']),
    ]
    with MET_LOCK:
        req = dict(MET['req'])
        atl = dict(MET['atl'])
    lines.append('# TYPE passerelle_http_requests_total counter')
    for k, v in sorted(req.items()):
        lines.append('passerelle_http_requests_total{class="%s"} %d' % (k, v))
    lines.append('# TYPE passerelle_atlassian_requests_total counter')
    for k, v in sorted(atl.items()):
        lines.append('passerelle_atlassian_requests_total{code="%s"} %d' % (k, v))
    with SSE_LOCK:
        lines.append('# TYPE passerelle_sse_clients gauge')
        lines.append('passerelle_sse_clients %d' % len(SSE_CLIENTS))
    try:
        with db() as c:
            n = c.execute('SELECT COUNT(*) FROM platforms').fetchone()[0]
        lines.append('# TYPE passerelle_platforms_total gauge')
        lines.append('passerelle_platforms_total %d' % n)
    except sqlite3.Error:
        pass
    try:
        lines.append('# TYPE passerelle_db_bytes gauge')
        lines.append('passerelle_db_bytes %d' % os.path.getsize(CONF['db']))
    except OSError:
        pass
    baks = sorted(glob.glob(os.path.join(CONF['data_dir'], 'backups', 'passerelle-*.db.gz')))
    if baks:
        lines.append('# TYPE passerelle_backup_age_seconds gauge')
        lines.append('passerelle_backup_age_seconds %d' % int(time.time() - os.path.getmtime(baks[-1])))
    return '\n'.join(lines) + '\n'


# ---------- Sauvegardes ----------

BAK_LOCK = threading.Lock()


def dump_db(reason):
    with BAK_LOCK:
        ts = time.strftime('%Y%m%d-%H%M%S')
        dest = os.path.join(CONF['data_dir'], 'backups', 'passerelle-%s.db' % ts)
        src = sqlite3.connect(CONF['db'])
        dst = sqlite3.connect(dest)
        try:
            with dst:
                src.backup(dst)
        finally:
            src.close()
            dst.close()
        with open(dest, 'rb') as f, gzip.open(dest + '.gz', 'wb') as g:
            shutil.copyfileobj(f, g)
        os.remove(dest)
        baks = sorted(glob.glob(os.path.join(CONF['data_dir'], 'backups', 'passerelle-*.db.gz')))
        for old in baks[:-CONF['backup_keep']]:
            os.remove(old)
        print(json.dumps({'ts': now(), 'msg': 'sauvegarde créée', 'reason': reason,
                          'file': os.path.basename(dest + '.gz')}, ensure_ascii=False),
              file=sys.stderr, flush=True)


def backup_loop():
    while True:
        try:
            baks = sorted(glob.glob(os.path.join(CONF['data_dir'], 'backups', 'passerelle-*.db.gz')))
            today = time.strftime('%Y%m%d')
            if not any(os.path.basename(b).startswith('passerelle-' + today) for b in baks):
                dump_db('quotidienne')
        except Exception as e:
            print(json.dumps({'ts': now(), 'msg': 'échec sauvegarde', 'err': str(e)}),
                  file=sys.stderr, flush=True)
        time.sleep(3600)


# ---------- Handler HTTP ----------

CSP = ("default-src 'none'; script-src 'unsafe-inline'; "
       "style-src 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; "
       "connect-src 'self'; base-uri 'none'; form-action 'self'")


def row_platform(row):
    return {'id': row['id'], 'rev': row['rev'], 'updatedAt': row['updated_at'],
            'updatedBy': row['updated_by'], 'data': json.loads(row['json'])}


def row_doc(row):
    return {'rev': row['rev'], 'updatedAt': row['updated_at'],
            'updatedBy': row['updated_by'], 'data': json.loads(row['json'])}


class Handler(BaseHTTPRequestHandler):
    server_version = 'Passerelle/' + VERSION
    protocol_version = 'HTTP/1.1'

    # ----- journalisation JSON (jamais de query string : les JQL sont sensibles) -----
    def log_request(self, code='-', size='-'):
        rec = {'ts': now(), 'ip': self.address_string(), 'user': getattr(self, '_user', '-'),
               'm': self.command, 'path': urlsplit(self.path).path, 'code': code,
               'ms': int((time.time() - getattr(self, '_t0', time.time())) * 1000)}
        print(json.dumps(rec, ensure_ascii=False), file=sys.stderr, flush=True)
        try:
            met_count('req', '%dxx' % (int(code) // 100))
        except (ValueError, TypeError):
            pass

    def log_message(self, fmt, *a):
        print(json.dumps({'ts': now(), 'msg': fmt % a}, ensure_ascii=False),
              file=sys.stderr, flush=True)

    # ----- envoi -----
    def _send(self, code, body, ctype='application/json; charset=utf-8', extra=()):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        if ctype.startswith('text/html'):
            self.send_header('Content-Security-Policy', CSP)
            self.send_header('X-Frame-Options', 'DENY')
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj, extra=()):
        self._send(code, json.dumps(obj, ensure_ascii=False), extra=extra)

    def _err(self, code, msg):
        self._json(code, {'error': msg})

    # ----- identité & corps -----
    def identity(self):
        if CONF['auth_mode'] == 'none':
            return {'email': 'poc@local', 'name': 'Utilisateur POC', 'role': 'admin'}
        email = (self.headers.get(CONF['h_email']) or '').strip().lower()
        if not email:
            return None
        name = (self.headers.get(CONF['h_name']) or self.headers.get('X-Auth-Request-User')
                or email.split('@')[0]).strip()
        if email in CONF['admins']:
            role = 'admin'
        elif not CONF['writers'] or email in CONF['writers']:
            role = 'contributeur'
        else:
            role = 'lecteur'
        return {'email': email, 'name': name, 'role': role}

    def read_body(self, cap=MAX_DOC * 2):
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            return None
        if n <= 0 or n > cap:
            return None
        try:
            return json.loads(self.rfile.read(n).decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return None

    # ----- routage -----
    def route(self, method):
        self._t0 = time.time()
        parts = urlsplit(self.path)
        path = unquote(parts.path)

        # Public : santé, métriques, application
        if method == 'GET' and path == '/healthz':
            try:
                with db() as c:
                    n = c.execute('SELECT COUNT(*) FROM platforms').fetchone()[0]
                return self._json(200, {'ok': True, 'app': 'passerelle', 'version': VERSION,
                                        'platforms': n, 'atlassian': bool(CONF['atl_site'])})
            except sqlite3.Error as e:
                return self._json(500, {'ok': False, 'error': str(e)})
        if method == 'GET' and path == '/metrics':
            return self._send(200, render_metrics(), 'text/plain; version=0.0.4; charset=utf-8')
        if method == 'GET' and path in ('/', '/index.html'):
            with open(CONF['app'], 'rb') as f:
                return self._send(200, f.read(), 'text/html; charset=utf-8')

        # Tout le reste exige une identité
        user = self.identity()
        if not user:
            return self._err(401, 'Identité requise : accédez à l’application via le proxy SSO '
                                  '(en-tête ' + CONF['h_email'] + ' absent).')
        self._user = user['email']

        if path.startswith('/atlassian/'):
            if method != 'GET':
                self.close_connection = True
                return self._err(405, 'GET uniquement.')
            return self.atlassian(path, parts.query)

        if not path.startswith('/api/'):
            return self._err(404, 'Chemin inconnu.')

        try:
            return self.api(method, path, parts, user)
        except sqlite3.Error as e:
            return self._err(500, 'Base de données : ' + str(e))

    # ----- API -----
    def api(self, method, path, parts, user):
        write = user['role'] in ('admin', 'contributeur')
        admin = user['role'] == 'admin'

        if method == 'GET' and path == '/api/me':
            return self._json(200, {'app': 'passerelle', 'version': VERSION,
                                    'email': user['email'], 'name': user['name'], 'role': user['role'],
                                    'atlassian': bool(CONF['atl_site'])})

        if method == 'GET' and path == '/api/state':
            with db() as c:
                plats = [row_platform(r) for r in c.execute('SELECT * FROM platforms')]
                teams = row_doc(c.execute("SELECT * FROM docs WHERE key='teams'").fetchone())
                settings = row_doc(c.execute("SELECT * FROM docs WHERE key='settings'").fetchone())
            return self._json(200, {'platforms': plats, 'teams': teams, 'settings': settings})

        if method == 'GET' and path == '/api/events':
            return self.sse()

        if method == 'GET' and path == '/api/audit':
            limit = 200
            try:
                limit = min(1000, max(1, int(parse_qs(parts.query).get('limit', ['200'])[0])))
            except ValueError:
                pass
            with db() as c:
                rows = [dict(r) for r in c.execute(
                    'SELECT ts,user,action,target,name,rev FROM audit ORDER BY seq DESC LIMIT ?', (limit,))]
            return self._json(200, {'entries': rows})

        if method == 'GET' and path == '/api/export':
            with db() as c:
                plats = [json.loads(r['json']) for r in c.execute('SELECT json FROM platforms')]
                teams = json.loads(c.execute("SELECT json FROM docs WHERE key='teams'").fetchone()['json'])
                st = json.loads(c.execute("SELECT json FROM docs WHERE key='settings'").fetchone()['json'])
            payload = {'version': 1, 'appVersion': VERSION, 'exportedAt': now(),
                       'seeded': False, 'seedBannerHidden': True, 'lastExportAt': now(),
                       'platforms': plats, 'teams': teams,
                       'settings': {'readyThreshold': st.get('readyThreshold', 90), 'userName': ''},
                       'integrations': {'relayUrl': '', 'siteUrl': st.get('siteUrl', ''),
                                        'dmexLabel': st.get('dmexLabel', 'asset-dip'), 'relayToken': ''}}
            return self._json(200, payload,
                              extra=[('Content-Disposition',
                                      'attachment; filename="passerelle-%s.json"' % time.strftime('%Y-%m-%d'))])

        m = path == '/api/platforms'
        mid = path.startswith('/api/platforms/')
        pid = unquote(path[len('/api/platforms/'):]) if mid else ''

        if method == 'GET' and mid:
            with db() as c:
                row = c.execute('SELECT * FROM platforms WHERE id=?', (pid,)).fetchone()
            return self._json(200, row_platform(row)) if row else self._err(404, 'Fiche introuvable.')

        # ---- écritures ----
        if method in ('POST', 'PUT', 'DELETE') and (m or mid) and not write:
            return self._err(403, 'Lecture seule : votre rôle ne permet pas de modifier.')

        if method == 'POST' and m:
            body = self.read_body()
            data = body.get('data') if isinstance(body, dict) else None
            if not isinstance(data, dict) or not data.get('id'):
                return self._err(400, 'Corps attendu : {"data": {…, "id": …}}.')
            js = json.dumps(data, ensure_ascii=False)
            if len(js) > MAX_DOC:
                return self._err(413, 'Fiche trop volumineuse (max 512 Ko).')
            with db() as c:
                try:
                    c.execute('INSERT INTO platforms(id,rev,json,updated_at,updated_by) VALUES(?,1,?,?,?)',
                              (str(data['id']), js, now(), user['name']))
                except sqlite3.IntegrityError:
                    return self._err(409, 'Une fiche porte déjà cet identifiant.')
            audit(user['email'], 'création', str(data['id']), str(data.get('name', '')), 1)
            broadcast({'type': 'platform', 'id': str(data['id']), 'rev': 1, 'by': user['name'],
                       'instance': self.headers.get('X-Client-Instance', '')})
            return self._json(201, {'id': str(data['id']), 'rev': 1})

        if method == 'PUT' and mid:
            body = self.read_body()
            if not isinstance(body, dict) or not isinstance(body.get('data'), dict):
                return self._err(400, 'Corps attendu : {"rev": n, "data": {…}}.')
            try:
                rev = int(body.get('rev') or 0)
            except (ValueError, TypeError):
                return self._err(400, 'Révision invalide.')
            data = body['data']
            data['id'] = pid
            js = json.dumps(data, ensure_ascii=False)
            if len(js) > MAX_DOC:
                return self._err(413, 'Fiche trop volumineuse (max 512 Ko).')
            with db() as c:
                cur = c.execute('UPDATE platforms SET rev=rev+1, json=?, updated_at=?, updated_by=? '
                                'WHERE id=? AND rev=?', (js, now(), user['name'], pid, rev))
                if cur.rowcount == 0:
                    row = c.execute('SELECT * FROM platforms WHERE id=?', (pid,)).fetchone()
                    if not row:
                        return self._err(404, 'Fiche introuvable (supprimée ?).')
                    return self._json(409, {'error': 'Conflit de version.', 'current': row_platform(row)})
            audit(user['email'], 'modification', pid, str(data.get('name', '')), rev + 1)
            broadcast({'type': 'platform', 'id': pid, 'rev': rev + 1, 'by': user['name'],
                       'instance': self.headers.get('X-Client-Instance', '')})
            return self._json(200, {'rev': rev + 1})

        if method == 'DELETE' and mid:
            with db() as c:
                row = c.execute('SELECT json FROM platforms WHERE id=?', (pid,)).fetchone()
                if not row:
                    return self._err(404, 'Fiche introuvable.')
                name = json.loads(row['json']).get('name', '')
                c.execute('DELETE FROM platforms WHERE id=?', (pid,))
            audit(user['email'], 'suppression', pid, str(name), None)
            broadcast({'type': 'platform_delete', 'id': pid, 'by': user['name'],
                       'instance': self.headers.get('X-Client-Instance', '')})
            return self._json(200, {'ok': True})

        if method == 'PUT' and path in ('/api/teams', '/api/settings'):
            key = path.rsplit('/', 1)[1]
            if key == 'settings' and not admin:
                return self._err(403, 'Réservé aux administrateurs.')
            if key == 'teams' and not write:
                return self._err(403, 'Lecture seule : votre rôle ne permet pas de modifier.')
            body = self.read_body()
            if not isinstance(body, dict) or 'data' not in body:
                return self._err(400, 'Corps attendu : {"rev": n, "data": …}.')
            try:
                rev = int(body.get('rev') or 0)
            except (ValueError, TypeError):
                return self._err(400, 'Révision invalide.')
            js = json.dumps(body['data'], ensure_ascii=False)
            if len(js) > MAX_DOC:
                return self._err(413, 'Document trop volumineux.')
            with db() as c:
                cur = c.execute('UPDATE docs SET rev=rev+1, json=?, updated_at=?, updated_by=? '
                                'WHERE key=? AND rev=?', (js, now(), user['name'], key, rev))
                if cur.rowcount == 0:
                    row = c.execute('SELECT * FROM docs WHERE key=?', (key,)).fetchone()
                    return self._json(409, {'error': 'Conflit de version.', 'current': row_doc(row)})
            audit(user['email'], key, key, '', rev + 1)
            broadcast({'type': key, 'rev': rev + 1, 'by': user['name'],
                       'instance': self.headers.get('X-Client-Instance', '')})
            return self._json(200, {'rev': rev + 1})

        if method == 'POST' and path == '/api/import':
            if not admin:
                return self._err(403, 'Réservé aux administrateurs.')
            body = self.read_body(cap=MAX_IMPORT)
            if not isinstance(body, dict) or not isinstance(body.get('platforms'), list) \
                    or not isinstance(body.get('teams'), list):
                return self._err(400, 'Format inattendu : export Passerelle requis.')
            dump_db('avant import')
            settings_in = body.get('settings') or {}
            integ_in = body.get('integrations') or {}
            st = {'readyThreshold': settings_in.get('readyThreshold', 90),
                  'dmexLabel': integ_in.get('dmexLabel', 'asset-dip'),
                  'siteUrl': integ_in.get('siteUrl', '')}
            with db() as c:
                c.execute('DELETE FROM platforms')
                seen = set()
                for p in body['platforms']:
                    if not isinstance(p, dict):
                        continue
                    pid = str(p.get('id') or ('p%d' % (len(seen) + 1)))
                    while pid in seen:
                        pid += 'x'
                    seen.add(pid)
                    p['id'] = pid
                    c.execute('INSERT INTO platforms(id,rev,json,updated_at,updated_by) VALUES(?,1,?,?,?)',
                              (pid, json.dumps(p, ensure_ascii=False), now(), user['name']))
                c.execute('UPDATE docs SET rev=rev+1, json=?, updated_at=?, updated_by=? WHERE key=?',
                          (json.dumps(body['teams'], ensure_ascii=False), now(), user['name'], 'teams'))
                c.execute('UPDATE docs SET rev=rev+1, json=?, updated_at=?, updated_by=? WHERE key=?',
                          (json.dumps(st, ensure_ascii=False), now(), user['name'], 'settings'))
            audit(user['email'], 'import', '', '%d fiches' % len(seen), None)
            broadcast({'type': 'reload', 'by': user['name'],
                       'instance': self.headers.get('X-Client-Instance', '')})
            return self._json(200, {'ok': True, 'platforms': len(seen)})

        if method == 'POST' and path == '/api/backup':
            if not admin:
                return self._err(403, 'Réservé aux administrateurs.')
            dump_db('manuelle (%s)' % user['email'])
            audit(user['email'], 'sauvegarde', '', '', None)
            return self._json(200, {'ok': True})

        return self._err(404, 'Chemin inconnu.')

    # ----- SSE -----
    def sse(self):
        q = queue.Queue(maxsize=200)
        with SSE_LOCK:
            SSE_CLIENTS.add(q)
        self.close_connection = True
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()
            self.wfile.write(b': connecte\n\n')
            self.wfile.flush()
            while True:
                try:
                    data = q.get(timeout=20)
                    self.wfile.write(('data: ' + data + '\n\n').encode())
                except queue.Empty:
                    self.wfile.write(b': ping\n\n')
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with SSE_LOCK:
                SSE_CLIENTS.discard(q)

    # ----- Relais Atlassian (liste blanche de relay.py) -----
    def atlassian(self, path, query):
        if not CONF['atl_site']:
            return self._err(503, 'Intégration Atlassian non configurée sur ce serveur (ATL_SITE).')
        upstream = path[len('/atlassian'):]
        if '..' in upstream or '\\' in upstream or '\x00' in upstream or '//' in upstream:
            return self._err(403, 'Chemin refusé.')
        if not any(rx.match(upstream) for rx in relay.ALLOWED):
            return self._err(403, 'Chemin non autorisé par le relais (liste blanche en lecture seule).')
        url = CONF['atl_site'] + upstream + (('?' + query) if query else '')
        import urllib.request
        req = urllib.request.Request(url, headers={
            'Authorization': CONF['atl_auth'],
            'Accept': 'application/json',
            'User-Agent': self.server_version,
        })
        try:
            with relay.OPENER.open(req, timeout=15) as up:
                body = up.read(relay.MAX_BODY + 1)
                if len(body) > relay.MAX_BODY:
                    return self._err(502, 'Relais : réponse amont trop volumineuse.')
                met_count('atl', str(up.status))
                extra = [(k, up.headers[k]) for k in relay.PASS_HEADERS if up.headers.get(k)]
                return self._send(up.status, body, up.headers.get('Content-Type', 'application/json'), extra)
        except urllib.error.HTTPError as e:
            met_count('atl', str(e.code))
            extra = [(k, e.headers[k]) for k in relay.PASS_HEADERS if e.headers.get(k)]
            return self._send(e.code, e.read(relay.MAX_BODY),
                              e.headers.get('Content-Type', 'application/json'), extra)
        except Exception as e:
            met_count('atl', 'err')
            return self._err(502, 'Relais : Atlassian injoignable (%s).' % e.__class__.__name__)

    # ----- verbes -----
    def do_GET(self):
        self.route('GET')

    def do_POST(self):
        self.route('POST')

    def do_PUT(self):
        self.route('PUT')

    def do_DELETE(self):
        self.route('DELETE')


def main():
    ap = argparse.ArgumentParser(description='Passerelle v2 — service partagé.')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8080)
    ap.add_argument('--app', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html'))
    args = ap.parse_args()
    CONF.update(load_conf(args))
    init_db()
    threading.Thread(target=backup_loop, daemon=True).start()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    print(json.dumps({'ts': now(), 'msg': 'Passerelle v%s démarrée' % VERSION,
                      'url': 'http://%s:%d/' % (args.host, args.port),
                      'data': CONF['data_dir'], 'auth': CONF['auth_mode'],
                      'atlassian': bool(CONF['atl_site'])}, ensure_ascii=False),
          file=sys.stderr, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
