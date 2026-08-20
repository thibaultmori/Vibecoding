#!/usr/bin/env bash
# Tests de bout en bout du serveur v2 (server.py) : API, rôles, conflits, SSE, relais.
# Lancement : bash tests/server.sh — code de sortie non nul en cas d'échec.
set -u
cd "$(dirname "$0")/.."
FAIL=0
STUB_PORT=19998
SRV_PORT=18810
DATA=$(mktemp -d)
B="http://127.0.0.1:$SRV_PORT"

expect(){ if [ "$2" = "$3" ]; then echo "OK   $1"; else echo "FAIL $1 (attendu: $2, obtenu: $3)"; FAIL=1; fi }
contains(){ case "$3" in *"$2"*) echo "OK   $1";; *) echo "FAIL $1 (absent: $2) → ${3:0:200}"; FAIL=1;; esac }
not_contains(){ case "$3" in *"$2"*) echo "FAIL $1 (présent: $2)"; FAIL=1;; *) echo "OK   $1";; esac }

ADMIN=(-H 'X-Auth-Request-Email: admin@test' -H 'X-Auth-Request-Preferred-Username: Admin Test')
WRITER=(-H 'X-Auth-Request-Email: writer@test' -H 'X-Auth-Request-Preferred-Username: Wanda Writer')
READER=(-H 'X-Auth-Request-Email: reader@test' -H 'X-Auth-Request-Preferred-Username: Rémi Reader')
JSONH=(-H 'Content-Type: application/json')

# --- Amont Atlassian factice ---
python3 - "$STUB_PORT" <<'EOF' &
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = json.dumps({'displayName': 'Robot Stub', 'echo': self.path}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
HTTPServer(('127.0.0.1', int(sys.argv[1])), H).serve_forever()
EOF
STUB=$!

DATA_DIR="$DATA" ADMIN_EMAILS=admin@test WRITE_EMAILS='writer@test,admin@test' \
ATL_SITE="http://127.0.0.1:$STUB_PORT" ATL_EMAIL=svc@t ATL_TOKEN=tk \
  python3 server.py --port "$SRV_PORT" 2>"$DATA/server.log" &
SRV=$!
for i in $(seq 1 30); do curl -sf "$B/healthz" >/dev/null 2>&1 && break; sleep 0.2; done

# 1. Public / auth
contains "healthz public" '"ok": true' "$(curl -s "$B/healthz")"
contains "metrics public" 'passerelle_info' "$(curl -s "$B/metrics")"
expect "api sans identité → 401" 401 "$(curl -s -o /dev/null -w '%{http_code}' "$B/api/me")"
contains "rôle admin" '"role": "admin"' "$(curl -s "${ADMIN[@]}" "$B/api/me")"
contains "rôle contributeur" '"role": "contributeur"' "$(curl -s "${WRITER[@]}" "$B/api/me")"
contains "rôle lecteur" '"role": "lecteur"' "$(curl -s "${READER[@]}" "$B/api/me")"
contains "l'app est servie" '<title>Passerelle MEE</title>' "$(curl -s "$B/")"

# 2. Écritures & rôles
expect "création par lecteur → 403" 403 "$(curl -s -o /dev/null -w '%{http_code}' -X POST "${READER[@]}" "${JSONH[@]}" -d '{"data":{"id":"p-a","name":"A"}}' "$B/api/platforms")"
contains "création par contributeur" '"rev": 1' "$(curl -s -X POST "${WRITER[@]}" "${JSONH[@]}" -d '{"data":{"id":"p-a","name":"Fiche A"}}' "$B/api/platforms")"
expect "double création même id → 409" 409 "$(curl -s -o /dev/null -w '%{http_code}' -X POST "${WRITER[@]}" "${JSONH[@]}" -d '{"data":{"id":"p-a","name":"A2"}}' "$B/api/platforms")"
contains "lecture par lecteur" '"Fiche A"' "$(curl -s "${READER[@]}" "$B/api/state")"

# 3. Concurrence optimiste
R409=$(curl -s -X PUT "${WRITER[@]}" "${JSONH[@]}" -d '{"rev":7,"data":{"name":"X"}}' "$B/api/platforms/p-a")
contains "PUT rev périmée → conflit" 'Conflit de version' "$R409"
contains "conflit : version courante renvoyée" '"updatedBy": "Wanda Writer"' "$R409"
contains "PUT rev correcte" '"rev": 2' "$(curl -s -X PUT "${WRITER[@]}" "${JSONH[@]}" -d '{"rev":1,"data":{"name":"Fiche A v2"}}' "$B/api/platforms/p-a")"

# 4. SSE : une modification est diffusée
curl -s -N -m 4 "${READER[@]}" "$B/api/events" > "$DATA/sse.out" &
SSE=$!
sleep 0.8
curl -s -X PUT "${WRITER[@]}" "${JSONH[@]}" -d '{"rev":2,"data":{"name":"Fiche A v3"}}' "$B/api/platforms/p-a" >/dev/null
wait $SSE 2>/dev/null
contains "SSE reçoit l'événement" '"type": "platform"' "$(cat "$DATA/sse.out")"
contains "SSE porte l'auteur" 'Wanda Writer' "$(cat "$DATA/sse.out")"

# 5. Teams / settings
contains "PUT teams contributeur" '"rev": 2' "$(curl -s -X PUT "${WRITER[@]}" "${JSONH[@]}" -d '{"rev":1,"data":[{"id":"t1","name":"Équipe test"}]}' "$B/api/teams")"
expect "PUT settings contributeur → 403" 403 "$(curl -s -o /dev/null -w '%{http_code}' -X PUT "${WRITER[@]}" "${JSONH[@]}" -d '{"rev":1,"data":{"readyThreshold":80}}' "$B/api/settings")"
contains "PUT settings admin" '"rev": 2' "$(curl -s -X PUT "${ADMIN[@]}" "${JSONH[@]}" -d '{"rev":1,"data":{"readyThreshold":80,"dmexLabel":"asset-dip","siteUrl":""}}' "$B/api/settings")"

# 6. Audit nominatif
AUD=$(curl -s "${READER[@]}" "$B/api/audit?limit=10")
contains "audit : création tracée" '"action": "création"' "$AUD"
contains "audit : e-mail de l'auteur" 'writer@test' "$AUD"

# 7. Export / import / sauvegarde
EXP=$(curl -s "${READER[@]}" "$B/api/export")
contains "export compatible v1" '"version": 1' "$EXP"
expect "import par contributeur → 403" 403 "$(curl -s -o /dev/null -w '%{http_code}' -X POST "${WRITER[@]}" "${JSONH[@]}" -d "$EXP" "$B/api/import")"
contains "import par admin" '"platforms": 1' "$(curl -s -X POST "${ADMIN[@]}" "${JSONH[@]}" -d "$EXP" "$B/api/import")"
contains "sauvegarde manuelle admin" '"ok": true' "$(curl -s -X POST "${ADMIN[@]}" "$B/api/backup")"
N_BAK=$(ls "$DATA/backups" | wc -l | tr -d ' ')
if [ "$N_BAK" -ge 2 ]; then echo "OK   sauvegardes présentes ($N_BAK : quotidienne + avant import + manuelle)"; else echo "FAIL sauvegardes présentes ($N_BAK)"; FAIL=1; fi

# 8. Suppression + relais Atlassian intégré
expect "suppression par lecteur → 403" 403 "$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "${READER[@]}" "$B/api/platforms/p-a")"
contains "suppression par contributeur" '"ok": true' "$(curl -s -X DELETE "${WRITER[@]}" "$B/api/platforms/p-a")"
expect "relais sans identité → 401" 401 "$(curl -s -o /dev/null -w '%{http_code}' "$B/atlassian/rest/api/3/myself")"
contains "relais authentifié" 'Robot Stub' "$(curl -s "${READER[@]}" "$B/atlassian/rest/api/3/myself")"
expect "relais hors liste blanche → 403" 403 "$(curl -s -o /dev/null -w '%{http_code}' "${READER[@]}" "$B/atlassian/rest/api/3/issue/X")"

# 9. Journaux JSON
contains "journaux JSON structurés" '"path": "/api/me"' "$(cat "$DATA/server.log")"
not_contains "jamais de query string en journal" 'jql=' "$(cat "$DATA/server.log")"

kill $SRV $STUB 2>/dev/null
wait 2>/dev/null
rm -rf "$DATA"

if [ "$FAIL" = "0" ]; then echo; echo "TOUS LES TESTS DU SERVEUR PASSENT"; else echo; echo "ÉCHECS DANS LES TESTS DU SERVEUR"; fi
exit $FAIL
