# web-nextjs

A Next.js 15 App Router app with standalone output: one page at `/` and a JSON health
endpoint at `/api/health`. Both return HTTP 200.

- Port: **3000** (`ENV PORT=3000 HOSTNAME=0.0.0.0`, `EXPOSE 3000`)
- User: `1000` (numeric, so the pod runs hardened)
- Files: `app/` (pages and routes), `next.config.mjs` (standalone output and security
  headers), `package.json` + `package-lock.json` (exact versions), `.npmrc` (install scripts
  off), `public/`, `Dockerfile`, `.dockerignore`

## Deploy with the CLI

```bash
guidal deploy ./web-nextjs                                   # prints "Image: <ref>"
guidal services create --name web --image <ref> --port 3000
```

## Deploy with the local MCP server

```text
deploy_from_source(path="/absolute/path/to/web-nextjs", service_name="web", port=3000)
get_build_status(build_id="...", wait_seconds=55)
get_service(service_id="...", wait_seconds=55)
```

## Verify

```bash
curl https://<service-url>/api/health
# {"status":"ok","app":"web-nextjs"}
curl -sI https://<service-url>/ | grep -i content-security-policy
```

Open the URL in a browser (or a headless one such as the Playwright MCP server): the page
renders and the console shows no CSP violations.

## Update

Edit files under `app/`. After changing dependencies, run `npm install` so
`package-lock.json` matches `package.json` (the build runs `npm ci` and fails if they differ).
Then:

```bash
guidal deploy ./web-nextjs --service web
```

Build-time variables (`NEXT_PUBLIC_*`) cannot be passed: there are no build arguments, and
`.env.production` / `.env.local` are withheld from the upload like every `.env*` file. Read
configuration at runtime (server components, route handlers) from `guidal env set` values.

## Design notes

- **Why it is built this way.** The standalone output contains only the files the server
  needs. The runtime image has Node and that output, with npm, npx, corepack and yarn removed;
  files are owned by root and the server runs as user 1000 with a read-only root filesystem.
- **Keep:** `output: "standalone"`; `poweredByHeader: false`; the `headers()` block (CSP,
  `nosniff`, frame denial, `Referrer-Policy`, `Permissions-Policy`, HSTS); no browser source
  maps; `.npmrc` `ignore-scripts=true` (dependency install scripts are a common supply-chain
  attack path; Next.js and its native packages ship prebuilt, so nothing breaks).
- **CSP.** Next.js inlines small scripts with the page data, so `script-src` allows
  `'unsafe-inline'`. That is acceptable for pages without user-supplied content. If a page
  renders user content, switch to a nonce-based CSP set in middleware.
- **Image optimizer off** (`images.unoptimized`). It fetches and decodes images on the server
  and has had remote-code-execution and SSRF advisories. If you enable it, it writes to
  `.next/cache`, which must then be made writable (point it at `/tmp`).
- **Versions.** Dependencies are at least two weeks old, with one deliberate exception:
  `next` 15.5.28 (2026-10-14) is a security release (a critical image-optimizer RCE and a
  Server Actions DoS), so it is used despite being newer.
- **`overrides.postcss`.** Next.js 15 pins an older `postcss` with known HIGH advisories; the
  override lifts it to a fixed 8.5 release. Drop it once Next.js ships a fixed version.
- **For a real app:** fetch data on the server; put secrets in `guidal secrets` and read them
  only in server code; never prefix a secret with `NEXT_PUBLIC_`.
