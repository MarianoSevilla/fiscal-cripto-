# Isolated one-shot PG18 client; never starts postgres server or Flask.
FROM postgres:18.6-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/s01-backup-venv \
    && /opt/s01-backup-venv/bin/pip install --no-cache-dir boto3==1.40.59

WORKDIR /app
COPY backup.py /app/backup.py
USER postgres
ENTRYPOINT ["/opt/s01-backup-venv/bin/python", "/app/backup.py"]
