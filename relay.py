#!/usr/bin/env python3
"""Passerelle — relais Atlassian Cloud en lecture seule + service de l'application.

Pourquoi : Atlassian Cloud n'émet pas d'en-têtes CORS pour les pages tierces ;
ce relais fait le pont depuis l'intranet et garde le jeton API côté serveur
(jamais dans le navigateur). Il sert aussi index.html : tout est même origine,
aucun CORS nécessaire.

Usage :
    ATL_SITE=https://mon-entreprise.atlassian.net \
    ATL_EMAIL=compte-service@mon-entreprise.fr \
    ATL_TOKEN=xxxxxxxx \
    python3 relay.py [--host 127.0.0.1] [--port 8765] [--app ./index.html] [--open-cors]

Puis ouvrir http://127.0.0.1:8765/

Sécurité : GET uniquement, liste blanche stricte de chemins, hôte amont fixe
(ATL_SITE), aucun en-tête client transmis à l'amont, jeton jamais loggé.
Utiliser un compte de service en LECTURE SEULE au périmètre minimal ; les
jetons Atlassian expirent au bout d'un an maximum : prévoir la rotation.
"""
import argparse
import base64
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

VERSION = '1.3.0'
MAX_BODY = 5 * 1024 * 1024  # taille maximale d'une réponse amont relayée


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Ne jamais suivre une redirection : l'Authorization ne doit pas suivre un Location."""
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(_NoRedirect)

# Chemins amont autorisés (regex ancrées, évaluées sur le chemin DÉCODÉ)
ALLOWED = [re.compile(p) for p in (
    r'^/rest/api/3/search/jql$',       # recherche JQL Jira
    r'^/rest/api/3/myself$',           # test de connexion Jira
    r'^/wiki/api/v2/pages$',           # pages Confluence en lot (?id=1,2,3)
    r'^/wiki/api/v2/pages/[0-9]+$',    # page par id
    r'^/wiki/api/v2/spaces$',          # espaces en lot (?ids=…)
    r'^/wiki/api/v2/spaces/[0-9]+$',   # espace par id
    r'^/wiki/rest/api/user/current$',  # test de connexion Confluence
    r'^/wiki/rest/api/user$',          # ?accountId=… → nom de l'auteur
    r'^/wiki/rest/api/content/search$',# recherche CQL (pages DMEX par label)
)]

# Seuls en-têtes amont relayés au navigateur (jamais WWW-Authenticate ni Set-Cookie)
PASS_HEADERS = ('Retry-After', 'X-RateLimit-Limit', 'X-RateLimit-Remaining', 'X-RateLimit-Reset')

CONFIG = {}


def parse_config():
    ap = argparse.ArgumentParser(description="Relais Atlassian en lecture seule pour Passerelle.")
    ap.add_argument('--host', default='127.0.0.1',
                    help="adresse d'écoute (défaut 127.0.0.1 ; 0.0.0.0 pour exposer au réseau)")
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--app', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html'),
                    help="chemin d'index.html à servir (défaut : à côté de ce script)")
    ap.add_argument('--open-cors', action='store_true',
                    help="ajoute Access-Control-Allow-Origin:* (uniquement si l'app est ouverte en file://)")
    args = ap.parse_args()

    if args.open_cors and args.host not in ('127.0.0.1', 'localhost', '::1'):
        sys.exit('--open-cors est réservé à un usage local (127.0.0.1) : ne l’exposez pas au réseau '
                 '(toute page web visitée pourrait lire Jira à travers le relais).')

    site = os.environ.get('ATL_SITE', '').rstrip('/')
    email = os.environ.get('ATL_EMAIL', '')
    token = os.environ.get('ATL_TOKEN', '')
    access_token = os.environ.get('RELAY_ACCESS_TOKEN', '')
    missing = [n for n, v in (('ATL_SITE', site), ('ATL_EMAIL', email), ('ATL_TOKEN', token)) if not v]
    if missing:
        sys.exit('Variables d’environnement manquantes : ' + ', '.join(missing) +
                 '\nExemple : ATL_SITE=https://xxx.atlassian.net ATL_EMAIL=… ATL_TOKEN=… python3 relay.py')
    if not site.startswith(('https://', 'http://')):
        sys.exit('ATL_SITE doit être une URL complète (https://xxx.atlassian.net)')
    if site.startswith('http://'):
        print('AVERTISSEMENT : ATL_SITE en http:// (jeton transmis en clair) — réservé aux tests.',
              file=sys.stderr)

    app_path = os.path.abspath(args.app)
    if not os.path.isfile(app_path):
        sys.exit('Application introuvable : ' + app_path)

    auth = 'Basic ' + base64.b64encode((email + ':' + token).encode()).decode()
    return args, {'site': site, 'auth': auth, 'app': app_path, 'open_cors': args.open_cors,
                  'access_token': access_token}


CSP = ("default-src 'none'; script-src 'unsafe-inline'; "
       "style-src 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; "
       "connect-src 'self'; base-uri 'none'; form-action 'self'")


class Handler(BaseHTTPRequestHandler):
    server_version = 'PasserelleRelay/' + VERSION
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *fmt_args):
        # Jamais de query string dans les logs (la JQL peut contenir des noms internes)
        sys.stderr.write('%s %s - %s\n' % (time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                                           self.address_string(), fmt % fmt_args))

    def log_request(self, code='-', size='-'):
        # Horodatage + code de statut, chemin sans query string
        self.log_message('%s %s %s', self.command, urlsplit(self.path).path, str(code))

    def _send(self, code, body, ctype='application/json; charset=utf-8', extra=()):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        if ctype.startswith('text/html'):
            self.send_header('Content-Security-Policy', CSP)
            self.send_header('X-Frame-Options', 'DENY')
        if CONFIG['open_cors']:
            self.send_header('Access-Control-Allow-Origin', '*')
            if CONFIG['access_token']:
                self.send_header('Access-Control-Allow-Headers', 'X-Relay-Token, Accept')
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _err(self, code, msg):
        self._send(code, json.dumps({'error': msg}, ensure_ascii=False).encode())

    def do_GET(self):
        parts = urlsplit(self.path)
        path = unquote(parts.path)

        if path in ('/', '/index.html'):
            with open(CONFIG['app'], 'rb') as f:
                return self._send(200, f.read(), 'text/html; charset=utf-8')

        if path == '/healthz':
            return self._send(200, json.dumps({
                'ok': True, 'version': VERSION,
                'upstream': bool(CONFIG['site']), 'auth_required': bool(CONFIG['access_token']),
            }).encode())

        if not path.startswith('/atlassian/'):
            return self._err(404, 'Chemin inconnu. L’API est sous /atlassian/…, l’application sous /.')

        if CONFIG['access_token']:
            supplied = self.headers.get('X-Relay-Token', '')
            if not hmac.compare_digest(supplied, CONFIG['access_token']):
                return self._err(403, 'Jeton d’accès au relais manquant ou invalide (en-tête X-Relay-Token — '
                                      'à renseigner dans Paramètres → Intégration Atlassian).')

        upstream_path = path[len('/atlassian'):]
        if '..' in upstream_path or '\\' in upstream_path or '\x00' in upstream_path or '//' in upstream_path:
            return self._err(403, 'Chemin refusé.')
        if not any(rx.match(upstream_path) for rx in ALLOWED):
            return self._err(403, 'Chemin non autorisé par le relais (liste blanche en lecture seule).')

        # Query string retransmise TELLE QUELLE (jamais décodée/ré-encodée)
        url = CONFIG['site'] + upstream_path + (('?' + parts.query) if parts.query else '')
        req = urllib.request.Request(url, headers={
            'Authorization': CONFIG['auth'],
            'Accept': 'application/json',
            'User-Agent': self.server_version,
        })
        try:
            with OPENER.open(req, timeout=15) as up:
                body = up.read(MAX_BODY + 1)
                if len(body) > MAX_BODY:
                    return self._err(502, 'Relais : réponse amont trop volumineuse (> 5 Mo).')
                ctype = up.headers.get('Content-Type', 'application/json')
                extra = [(k, up.headers[k]) for k in PASS_HEADERS if up.headers.get(k)]
                return self._send(up.status, body, ctype, extra)
        except urllib.error.HTTPError as e:
            body = e.read(MAX_BODY)
            ctype = e.headers.get('Content-Type', 'application/json')
            extra = [(k, e.headers[k]) for k in PASS_HEADERS if e.headers.get(k)]
            return self._send(e.code, body, ctype, extra)
        except Exception as e:
            return self._err(502, 'Relais : Atlassian injoignable (%s). Vérifiez le réseau/proxy de la machine du relais.'
                             % e.__class__.__name__)

    def _method_not_allowed(self):
        self.close_connection = True
        self._err(405, 'GET uniquement : ce relais est en lecture seule.')

    do_POST = _method_not_allowed
    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed


def main():
    args, conf = parse_config()
    CONFIG.update(conf)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    print('Passerelle v%s : http://%s:%d/  →  %s  (GET uniquement, liste blanche%s)'
          % (VERSION, args.host, args.port, CONFIG['site'],
             ', jeton d’accès requis' if CONFIG['access_token'] else ''))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
