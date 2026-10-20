# Base image pinned by tag AND digest (linux/amd64 + arm64 index). To bump:
#   docker buildx imagetools inspect python:<new-tag>   # copy the top-level "Digest"
# and replace both FROM lines.

# --- build stage: install dependencies (none yet), verified by hash ---
FROM python:3.12.15-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS build
RUN python -m venv --without-pip /venv
COPY requirements.txt .
RUN if grep -q '^[^#]' requirements.txt; then \
      pip --python /venv/bin/python install --no-cache-dir --disable-pip-version-check \
        --require-hashes --only-binary=:all: -r requirements.txt; \
    fi

# --- runtime stage ---
FROM python:3.12.15-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
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
