#!/usr/bin/env bash
# Tests de bout en bout du relais Atlassian (relay.py) contre un amont factice.
# Lancement : bash tests/relay.sh — code de sortie non nul en cas d'échec.
set -u
cd "$(dirname "$0")/.."
FAIL=0
STUB_PORT=19999
RELAY_PORT=18766
RELAY_TOKEN_PORT=18767

expect(){ # desc attendu obtenu
  if [ "$2" = "$3" ]; then echo "OK   $1"; else echo "FAIL $1 (attendu: $2, obtenu: $3)"; FAIL=1; fi
}
contains(){ # desc aiguille meule
  case "$3" in *"$2"*) echo "OK   $1";; *) echo "FAIL $1 (absent: $2)"; FAIL=1;; esac
}
not_contains(){ # desc aiguille meule
  case "$3" in *"$2"*) echo "FAIL $1 (présent: $2)"; FAIL=1;; *) echo "OK   $1";; esac
}

# --- Amont Atlassian factice ---
python3 - "$STUB_PORT" <<'EOF' &
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.startswith('/wiki/rest/api/user/current'):
            body = json.dumps({'errorMessages': ['jeton expiré']}).encode()
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="stub"')
        elif self.path.startswith('/rest/api/3/myself'):
            body = b'{}'
            self.send_response(302)
            self.send_header('Location', 'https://attaquant.exemple/vol-de-jeton')
        else:
            body = json.dumps({'echo_path': self.path,
                               'auth_prefix': self.headers.get('Authorization', '')[:6],
                               'cookie_recu': 'Cookie' in self.headers}).encode()
            self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
HTTPServer(('127.0.0.1', int(sys.argv[1])), H).serve_forever()
EOF
STUB=$!

ATL_SITE="http://127.0.0.1:$STUB_PORT" ATL_EMAIL=svc@exemple.fr ATL_TOKEN=jeton-test \
  python3 relay.py --port "$RELAY_PORT" 2>/dev/null &
RELAY=$!
ATL_SITE="http://127.0.0.1:$STUB_PORT" ATL_EMAIL=svc@exemple.fr ATL_TOKEN=jeton-test \
  RELAY_ACCESS_TOKEN=sekret python3 relay.py --port "$RELAY_TOKEN_PORT" 2>/dev/null &
RELAY_T=$!
sleep 1.5

B="http://127.0.0.1:$RELAY_PORT"
BT="http://127.0.0.1:$RELAY_TOKEN_PORT"

# 1. Chemin autorisé : query string intacte, auth injectée, cookies non transmis
R=$(curl -s -H 'Cookie: session=abc' "$B/atlassian/rest/api/3/search/jql?jql=project%20%3D%20%22KAAS%22%20AND%20labels%20%3D%20m%C3%A9tier&maxResults=50")
contains "query string transmise telle quelle" 'jql=project%20%3D%20%22KAAS%22%20AND%20labels%20%3D%20m%C3%A9tier' "$R"
contains "auth Basic injectée" '"auth_prefix": "Basic "' "$R"
contains "cookies non transmis à l'amont" '"cookie_recu": false' "$R"

# 2-4. Refus : hors liste blanche, POST, traversal encodé
expect "hors liste blanche → 403" 403 "$(curl -s -o /dev/null -w '%{http_code}' "$B/atlassian/rest/api/3/issue/X-1")"
expect "POST → 405" 405 "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$B/atlassian/rest/api/3/search/jql")"
expect "traversal encodé → 403" 403 "$(curl -s --path-as-is -o /dev/null -w '%{http_code}' "$B/atlassian/rest/api/3/search/jql/%2e%2e/foo")"
expect "id de page non numérique → 403" 403 "$(curl -s -o /dev/null -w '%{http_code}' "$B/atlassian/wiki/api/v2/pages/abc")"
expect "recherche CQL autorisée → 200" 200 "$(curl -s -o /dev/null -w '%{http_code}' "$B/atlassian/wiki/rest/api/content/search?cql=label%3D%22asset-dip%22")"

# 5. 401 amont relayé sans WWW-Authenticate, corps préservé
H401=$(curl -s -i "$B/atlassian/wiki/rest/api/user/current")
contains "401 amont relayé" 'HTTP/1.1 401' "$H401"
not_contains "WWW-Authenticate filtré" 'WWW-Authenticate' "$H401"
contains "corps d'erreur préservé" 'jeton expir' "$H401"

# 6. Redirection amont NON suivie (le jeton ne part pas chez l'attaquant)
H302=$(curl -s -i "$B/atlassian/rest/api/3/myself")
contains "redirection relayée sans être suivie" 'HTTP/1.1 302' "$H302"
not_contains "en-tête Location non relayé" 'attaquant.exemple' "$H302"

# 7. Application servie + en-têtes de sécurité
HAPP=$(curl -s -i "$B/")
contains "index.html servi" '<title>Passerelle MEE</title>' "$HAPP"
contains "CSP présente" 'Content-Security-Policy' "$HAPP"
contains "nosniff présent" 'X-Content-Type-Options: nosniff' "$HAPP"
contains "X-Frame-Options présent" 'X-Frame-Options: DENY' "$HAPP"

# 8. Healthcheck
HZ=$(curl -s "$B/healthz")
contains "healthz ok" '"ok": true' "$HZ"

# 9. Jeton d'accès au relais
expect "sans jeton → 403" 403 "$(curl -s -o /dev/null -w '%{http_code}' "$BT/atlassian/rest/api/3/search/jql?jql=x")"
expect "mauvais jeton → 403" 403 "$(curl -s -o /dev/null -w '%{http_code}' -H 'X-Relay-Token: faux' "$BT/atlassian/rest/api/3/search/jql?jql=x")"
expect "bon jeton → 200" 200 "$(curl -s -o /dev/null -w '%{http_code}' -H 'X-Relay-Token: sekret' "$BT/atlassian/rest/api/3/search/jql?jql=x")"
expect "healthz accessible sans jeton" 200 "$(curl -s -o /dev/null -w '%{http_code}' "$BT/healthz")"
contains "healthz signale l'auth requise" '"auth_required": true' "$(curl -s "$BT/healthz")"

# 10. Verrou de sécurité : --open-cors interdit hors 127.0.0.1
if ATL_SITE="http://127.0.0.1:$STUB_PORT" ATL_EMAIL=a@b ATL_TOKEN=t \
   python3 relay.py --host 0.0.0.0 --port 18999 --open-cors >/dev/null 2>&1; then
  echo "FAIL --open-cors + 0.0.0.0 aurait dû être refusé"; FAIL=1
else
  echo "OK   --open-cors + 0.0.0.0 refusé au démarrage"
fi

kill $RELAY $RELAY_T $STUB 2>/dev/null
wait 2>/dev/null

if [ "$FAIL" = "0" ]; then echo; echo "TOUS LES TESTS DU RELAIS PASSENT"; else echo; echo "ÉCHECS DANS LES TESTS DU RELAIS"; fi
exit $FAIL
