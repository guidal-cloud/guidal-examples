# Base image pinned by tag AND digest (linux/amd64 + arm64 index). To bump:
#   docker buildx imagetools inspect python:<new-tag>   # copy the top-level "Digest"
# and replace both FROM lines.

# --- build stage: resolve and install dependencies, verified by hash ---
FROM python:3.12.16-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54 AS build
RUN python -m venv --without-pip /venv
COPY requirements.txt .
RUN pip --python /venv/bin/python install --no-cache-dir --disable-pip-version-check \
      --require-hashes --only-binary=:all: -r requirements.txt

# --- runtime stage: the venv and the app, nothing else ---
FROM python:3.12.16-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54
# No package manager at runtime: remove pip and the ensurepip wheel it could be
# reinstalled from, so the running image has no installer.
RUN python -m pip uninstall --yes --no-cache-dir pip \
    && rm -rf /usr/local/lib/python3.12/ensurepip
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/venv/bin:$PATH PORT=8000
COPY --from=build /venv /venv
WORKDIR /app
# Files stay owned by root, so the app user cannot modify its own code.
COPY main.py security.py ./
USER 1000
EXPOSE 8000
# --proxy-headers stays at uvicorn's default trust (127.0.0.1 only): X-Forwarded-*
# from anyone else is ignored, so clients cannot spoof their IP or scheme.
# --limit-concurrency answers 503 once 100 connections/tasks are open (it counts open
# connections, including idle keep-alive ones, not running handlers), instead of
# running out of memory.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", \
     "--no-access-log", "--limit-concurrency", "100", "--timeout-keep-alive", "5", \
     "--timeout-graceful-shutdown", "20"]
