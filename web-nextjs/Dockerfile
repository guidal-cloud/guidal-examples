# Base image pinned by tag AND digest (linux/amd64 + arm64 index). To bump:
#   docker buildx imagetools inspect node:<new-tag>   # copy the top-level "Digest"
# and replace both FROM lines.

# --- build stage: install from the lockfile and build ---
FROM node:22.23.3-trixie-slim@sha256:154ba2f4d6fec323d28e4f4bb86bba4677f1223391a1979cf521304e03a98dfa AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json .npmrc ./
# Exact versions and integrity hashes from package-lock.json; install scripts off (.npmrc).
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# --- runtime stage: the standalone server only ---
FROM node:22.23.3-trixie-slim@sha256:154ba2f4d6fec323d28e4f4bb86bba4677f1223391a1979cf521304e03a98dfa
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
# No package managers at runtime: the running image has no installer.
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack \
      /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack /opt/yarn-* \
      /usr/local/bin/yarn /usr/local/bin/yarnpkg
WORKDIR /app
# Files stay owned by root, so the app user cannot modify its own code.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
USER 1000
EXPOSE 3000
CMD ["node", "server.js"]
