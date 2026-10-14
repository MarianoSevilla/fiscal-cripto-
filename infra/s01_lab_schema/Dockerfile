# STG-B11B: READ-ONLY schema target probe; no app, Alembic or SQL writer.
FROM postgres:18.6-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY preflight.py /app/preflight.py
USER postgres
ENTRYPOINT ["python3", "/app/preflight.py"]
