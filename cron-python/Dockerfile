# Base image pinned by tag AND digest (linux/amd64 + arm64 index). To bump:
#   docker buildx imagetools inspect python:<new-tag>   # copy the top-level "Digest"
# and replace both FROM lines.

# --- build stage: install dependencies (none yet), verified by hash ---
FROM python:3.12.16-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54 AS build
RUN python -m venv --without-pip /venv
COPY requirements.txt .
RUN if grep -q '^[^#]' requirements.txt; then \
      pip --python /venv/bin/python install --no-cache-dir --disable-pip-version-check \
        --require-hashes --only-binary=:all: -r requirements.txt; \
    fi

# --- runtime stage ---
FROM python:3.12.16-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54
# No package manager at runtime: remove pip and the ensurepip wheel it could be
# reinstalled from, so the running image has no installer.
RUN python -m pip uninstall --yes --no-cache-dir pip \
    && rm -rf /usr/local/lib/python3.12/ensurepip
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/venv/bin:$PATH
COPY --from=build /venv /venv
WORKDIR /app
COPY job.py ./
USER 1000
CMD ["python", "job.py"]
