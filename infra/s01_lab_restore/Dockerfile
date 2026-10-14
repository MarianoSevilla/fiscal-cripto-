# One-shot read-only probe: never contains restore code or application server.
FROM postgres:18.6-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY probe.py /app/probe.py
USER postgres
ENTRYPOINT ["python3", "/app/probe.py"]
