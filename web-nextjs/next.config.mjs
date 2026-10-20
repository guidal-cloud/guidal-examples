// Content-Security-Policy without nonces. Next.js inlines small <script> tags with
// the page data, so script-src needs 'unsafe-inline' unless every page renders
// dynamically with a per-request nonce (middleware). The other directives still
// block framing, plugins, <base> hijacking, foreign form posts and foreign fetches.
// If a page renders user-supplied content, move to the nonce-based CSP.
const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  // TLS terminates at the platform edge, so every public request is HTTPS.
  { key: "Strict-Transport-Security", value: "max-age=31536000" },
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Emits .next/standalone/server.js with only the files the server needs, which
  // keeps the image small (default limit: 512Mi memory).
  output: "standalone",
  poweredByHeader: false,
  productionBrowserSourceMaps: false,
  // The image optimizer fetches and decodes images on the server: most recent
  // Next.js remote-code-execution and SSRF advisories were in it. Off unless needed;
  // if you turn it on, it caches under .next/cache, which must then be writable.
  images: { unoptimized: true },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
