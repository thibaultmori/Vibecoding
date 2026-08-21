import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def do_GET(self):
        p = self.path
        if '/issue/createmeta/' in p:
            return self._send({'issueTypes': [{'id': '10001', 'name': 'Task'}, {'id': '10004', 'name': 'Bug'}]})
        if '/search/jql' in p:
            return self._send({'issues': [{'key': 'INF-7', 'fields': {'summary': 'Ticket auto-synchro',
                'status': {'name': 'En cours', 'statusCategory': {'key': 'indeterminate'}},
                'assignee': {'displayName': 'Robot'}, 'issuetype': {'name': 'Task'},
                'priority': {'name': 'High'}, 'updated': '2026-08-20T10:00:00.000+0000'}}]})
        if '/wiki/api/v2/pages' in p:
            return self._send({'results': [{'id': '555001', 'title': 'DMEX stub', 'spaceId': '42',
                'version': {'number': 3, 'createdAt': '2026-08-01T00:00:00.000Z', 'authorId': 'a1'}}]})
        if '/wiki/api/v2/spaces' in p:
            return self._send({'results': [{'id': '42', 'name': 'Espace Stub'}]})
        if '/wiki/rest/api/user?' in p:
            return self._send({'displayName': 'Auteur Stub'})
        return self._send({'displayName': 'Robot Stub', 'path': p})
    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        body = json.loads(self.rfile.read(n) or b'{}')
        with open(sys.argv[2], 'a', encoding='utf-8') as g:
            g.write(json.dumps({'path': self.path, 'body': body}, ensure_ascii=False) + '\n')
        if self.path.startswith('/rest/api/3/issue'):
            return self._send({'id': '90001', 'key': 'INF-123', 'self': 'x'}, 201)
        return self._send({}, 202)
HTTPServer(('127.0.0.1', int(sys.argv[1])), H).serve_forever()
