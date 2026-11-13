# Tedarik Portalı. KS GRC Dockerfile düzeni: özetle sabit taban, hash ile sabit paketler, pip kaldırılır, UID 10001.
FROM python:3.12-alpine@sha256:213242b537a1c166a0c53e903461fc18d5518e7196c93dbecda452660a848918
WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --disable-pip-version-check --no-cache-dir --only-binary=:all: --require-hashes -r requirements.txt \
    && python -m pip uninstall -y pip \
    && rm -rf /usr/local/lib/python3.12/ensurepip \
    && addgroup -S -g 10001 tedarik && adduser -S -D -u 10001 -G tedarik tedarik
COPY app.py /app/
COPY tedarik/ /app/tedarik/
USER 10001:10001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TEDARIK_HOST=0.0.0.0 PORT=8090
EXPOSE 8090
# /api/health kimlik ister; 401 yanıtı uygulamanın ayakta olduğunu gösterir (KS GRC ile aynı).
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD ["python", "-c", "import http.client; c=http.client.HTTPConnection('127.0.0.1',8090,timeout=3); c.request('GET','/api/health'); raise SystemExit(c.getresponse().status!=401)"]
CMD ["python", "/app/app.py"]
