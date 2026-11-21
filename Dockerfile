# Bookhouse — read-only Calibre libraries, multi-library web reader
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /bookhouse

# libmagic is required by python-magic (file type detection)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as non-root; we mount:
#   /config            — writable (app.db Bookhouse state, settings)
#   /calibre-library   — read-only Calibre library (metadata.db + books)
#   /calibre-library2  — read-only (optional second library)
RUN useradd -m -u 1000 bookhouse
RUN mkdir -p /config && chown -R bookhouse:bookhouse /config /bookhouse
USER bookhouse

EXPOSE 8083

VOLUME ["/config"]

ENTRYPOINT ["python", "cps.py", "-p", "/config/app.db", "-g", "/config/gdrive.db", "-i", "0.0.0.0"]
