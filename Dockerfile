# Passerelle v2 — image unique : front + API + relais Atlassian.
# Construction sans accès réseau : Python standard uniquement.
FROM python:3.12-slim

WORKDIR /app
COPY server.py relay.py index.html ./

# Données (SQLite + sauvegardes) sur volume persistant
ENV DATA_DIR=/data
RUN useradd --system --uid 10001 passerelle && mkdir -p /data && chown 10001:10001 /data
VOLUME /data
USER 10001

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD ["python3", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).status==200 else 1)"]

CMD ["python3", "server.py", "--host", "0.0.0.0", "--port", "8080"]
