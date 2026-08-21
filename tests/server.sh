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

# --- Stub SMTP (capture les messages) ---
SMTP_PORT=19997
SMTP_CAP="$DATA/smtp.txt"
python3 - "$SMTP_PORT" "$SMTP_CAP" <<'EOF' &
import socket, sys
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(('127.0.0.1', int(sys.argv[1]))); srv.listen(8)
cap = sys.argv[2]
while True:
    c, _ = srv.accept()
    f = c.makefile('rb')
    c.sendall(b'220 stub ESMTP\r\n')
    data, rcpt = None, []
    for raw in f:
        line = raw.decode('utf-8', 'replace').rstrip('\r\n')
        u = line.upper()
        if data is not None:
            if line == '.':
                with open(cap, 'a', encoding='utf-8') as g:
                    g.write('=== RCPT:%s ===\n%s\n' % (','.join(rcpt), '\n'.join(data)))
                data, rcpt = None, []
                c.sendall(b'250 ok\r\n')
            else:
                data.append(line)
        elif u.startswith('EHLO') or u.startswith('HELO'):
            c.sendall(b'250-stub\r\n250 ok\r\n')
        elif u.startswith('MAIL') or u.startswith('NOOP') or u.startswith('RSET'):
            c.sendall(b'250 ok\r\n')
        elif u.startswith('RCPT'):
            rcpt.append(line.split(':', 1)[-1].strip('<> ')); c.sendall(b'250 ok\r\n')
        elif u.startswith('DATA'):
            data = []; c.sendall(b'354 go\r\n')
        elif u.startswith('QUIT'):
            c.sendall(b'221 bye\r\n'); break
        else:
            c.sendall(b'250 ok\r\n')
    c.close()
EOF
SMTPSTUB=$!

# --- Stub webhook Teams (répond 202, capture le corps) ---
TEAMS_PORT=19996
TEAMS_CAP="$DATA/teams.txt"
python3 - "$TEAMS_PORT" "$TEAMS_CAP" <<'EOF' &
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
cap = sys.argv[2]
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        with open(cap, 'ab') as g:
            g.write(self.rfile.read(n) + b'\n')
        self.send_response(202)
        self.send_header('Content-Length', '0')
        self.end_headers()
HTTPServer(('127.0.0.1', int(sys.argv[1])), H).serve_forever()
EOF
TEAMSSTUB=$!

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
SMTP_HOST=127.0.0.1 SMTP_PORT=$SMTP_PORT SMTP_FROM=passerelle@test \
TEAMS_WEBHOOK_URL="http://127.0.0.1:$TEAMS_PORT/hook" NOTIFY_EMAIL=direction@test \
NOTIFY_HOUR=0 PUBLIC_URL=http://passerelle.test \
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

# 10. Référentiel de checklist (doc versionné, admin)
expect "PUT template contributeur → 403" 403 "$(curl -s -o /dev/null -w '%{http_code}' -X PUT "${WRITER[@]}" "${JSONH[@]}" -d '{"rev":0,"data":{"version":1,"cats":[]}}' "$B/api/template")"
contains "PUT template admin (création)" '"rev": 1' "$(curl -s -X PUT "${ADMIN[@]}" "${JSONH[@]}" -d '{"rev":0,"data":{"version":1,"cats":[{"id":"c1","label":"Cat test","team":"","items":[{"id":"1","label":"Item test","crits":["C1"]}]}]}}' "$B/api/template")"
expect "PUT template rev périmée → 409" 409 "$(curl -s -o /dev/null -w '%{http_code}' -X PUT "${ADMIN[@]}" "${JSONH[@]}" -d '{"rev":0,"data":{"version":2,"cats":[]}}' "$B/api/template")"
contains "template servi dans /api/state" '"Cat test"' "$(curl -s "${READER[@]}" "$B/api/state")"

# 11. Garde serveur des signatures Go/No-Go
expect "création avec signature usurpée → 403" 403 "$(curl -s -o /dev/null -w '%{http_code}' -X POST "${WRITER[@]}" "${JSONH[@]}" -d '{"data":{"id":"p-g","name":"G","gonogo":{"decision":"go","pending":true,"decidedBy":"X","decidedByEmail":"autre@test"}}}' "$B/api/platforms")"
contains "création avec sa propre signature" '"rev": 1' "$(curl -s -X POST "${WRITER[@]}" "${JSONH[@]}" -d '{"data":{"id":"p-g","name":"G","gonogo":{"decision":"go","pending":true,"decidedBy":"Wanda","decidedByEmail":"writer@test"}}}' "$B/api/platforms")"
expect "contre-validation par le proposeur → 403" 403 "$(curl -s -o /dev/null -w '%{http_code}' -X PUT "${WRITER[@]}" "${JSONH[@]}" -d '{"rev":1,"data":{"id":"p-g","name":"G","gonogo":{"decision":"go","pending":false,"decidedBy":"Wanda","decidedByEmail":"writer@test","confirmedBy":"Wanda","confirmedByEmail":"writer@test"}}}' "$B/api/platforms/p-g")"
expect "contre-validation usurpée → 403" 403 "$(curl -s -o /dev/null -w '%{http_code}' -X PUT "${WRITER[@]}" "${JSONH[@]}" -d '{"rev":1,"data":{"id":"p-g","name":"G","gonogo":{"decision":"go","pending":false,"decidedBy":"Wanda","decidedByEmail":"writer@test","confirmedBy":"A","confirmedByEmail":"admin@test"}}}' "$B/api/platforms/p-g")"
contains "contre-validation légitime (autre utilisateur)" '"rev": 2' "$(curl -s -X PUT "${ADMIN[@]}" "${JSONH[@]}" -d '{"rev":1,"data":{"id":"p-g","name":"G","gonogo":{"decision":"go","pending":false,"decidedBy":"Wanda","decidedByEmail":"writer@test","confirmedBy":"Anne","confirmedByEmail":"admin@test"}}}' "$B/api/platforms/p-g")"

# 12. Notifications (SMTP + Teams via stubs)
TOMORROW=$(python3 -c "from datetime import date, timedelta; print(date.today()+timedelta(days=1))")
YESTERDAY=$(python3 -c "from datetime import date, timedelta; print(date.today()-timedelta(days=1))")
TREV=$(curl -s "${ADMIN[@]}" "$B/api/state" | python3 -c "import json,sys; print(json.load(sys.stdin)['teams']['rev'])")
curl -s -X PUT "${WRITER[@]}" "${JSONH[@]}" -d '{"rev":'"$TREV"',"data":[{"id":"t1","name":"Équipe test","contact":"equipe@test"}]}' "$B/api/teams" >/dev/null
curl -s -X POST "${WRITER[@]}" "${JSONH[@]}" -d '{"data":{"id":"p-n","name":"Fiche à échéances","stage":"build","targetDate":"'"$YESTERDAY"'","checklist":[{"id":"x.1","cat":"x","label":"Item avec échéance proche","status":"todo","team":"t1","due":"'"$TOMORROW"'"}],"actions":[{"id":"a1","label":"Action bloquante retardée","due":"'"$YESTERDAY"'","blocking":true,"done":false}]}}' "$B/api/platforms" >/dev/null
expect "notify/run par contributeur → 403" 403 "$(curl -s -o /dev/null -w '%{http_code}' -X POST "${WRITER[@]}" "$B/api/notify/run")"
NOTIF=$(curl -s -X POST "${ADMIN[@]}" "$B/api/notify/run")
contains "notify/run admin" '"ok": true' "$NOTIF"
contains "e-mail d'équipe envoyé" 'equipe@test' "$NOTIF"
sleep 0.5
contains "SMTP : item d'échéance reçu par l'équipe" 'Item avec' "$(cat "$SMTP_CAP" 2>/dev/null)"
contains "SMTP : e-mail global à la direction" 'direction@test' "$(cat "$SMTP_CAP" 2>/dev/null)"
contains "SMTP : en-tête d'automate" 'Auto-Submitted: auto-generated' "$(cat "$SMTP_CAP" 2>/dev/null)"
contains "Teams : carte Adaptive au format Workflows" 'application/vnd.microsoft.card.adaptive' "$(cat "$TEAMS_CAP" 2>/dev/null)"
contains "Teams : action bloquante signalée" 'Action bloquante' "$(cat "$TEAMS_CAP" 2>/dev/null)"
contains "healthz expose les canaux" '"notify": "email+teams"' "$(curl -s "$B/healthz")"

kill $SRV $STUB $SMTPSTUB $TEAMSSTUB 2>/dev/null
wait 2>/dev/null
rm -rf "$DATA"

if [ "$FAIL" = "0" ]; then echo; echo "TOUS LES TESTS DU SERVEUR PASSENT"; else echo; echo "ÉCHECS DANS LES TESTS DU SERVEUR"; fi
exit $FAIL
