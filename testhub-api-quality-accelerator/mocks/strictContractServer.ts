import http from "http";

/**
 * STRICT, standards-correct contract mock for the generated JSON / XML /
 * URL-encoded / binary suites. Unlike reqresContractServer (permissive, mirrors
 * the public reqres.in the hand-written examples were authored against), this
 * server REJECTS non-compliant requests with the correct HTTP status — so a
 * generated negative test genuinely fails a non-compliant API. That is the
 * "catches real defects" property a bank's C4E is buying.
 *
 * Contract (checks applied in order), for the single POST endpoint the suite
 * targets (any other path -> 404):
 *   1. path contains /invalid            -> 404
 *   2. method !== POST                   -> 405   (method not allowed)
 *   3. x-api-key missing or wrong        -> 401
 *   4. Accept present & not JSON-capable -> 406
 *   5. Content-Type not an allowed type  -> 415
 *   6. body too large (> 1 MB)           -> 413
 *   7. empty binary body                 -> 400
 *   8. malformed JSON / non-object JSON  -> 400
 *   9. malformed XML                     -> 400
 *  10. SQL-injection / XSS in the body   -> 403
 *  11. otherwise                         -> 201
 *
 * Response bodies are nominal JSON — the generated specs assert on status.
 */

const MAX_BYTES = 1024 * 1024;
const ALLOWED_CT = [
  "application/json", "application/xml", "text/xml",
  "application/x-www-form-urlencoded",
  "application/octet-stream", "application/pdf", "application/zip",
  "image/png", "image/jpeg",
];
const BINARY_CT = /octet-stream|application\/pdf|application\/zip|image\//i;
// Injection markers — NOT bare "--" (matches multipart boundaries; irrelevant
// here but kept consistent with the other mock).
const SQLI_XSS = /('\s*or\s*['"\d]|union\s+select|<script|onerror\s*=|alert\s*\()/i;

const acceptsJson = (a: string) => !a || /application\/json|\*\/\*/i.test(a);

/** Cheap well-formedness check for XML: every tag opened is closed, in order. */
function xmlLooksWellFormed(s: string): boolean {
  const body = s.replace(/<\?[^?]*\?>/g, "").trim();
  if (!body.startsWith("<")) return false;
  const tagRe = /<\s*(\/?)\s*([a-zA-Z_][\w.-]*)[^>]*?(\/?)\s*>/g;
  const stack: string[] = [];
  let m: RegExpExecArray | null;
  let sawAny = false;
  while ((m = tagRe.exec(body)) !== null) {
    sawAny = true;
    const [, closing, name, selfClose] = m;
    if (selfClose) continue;
    if (closing) {
      if (stack.pop() !== name) return false;
    } else {
      stack.push(name);
    }
  }
  return sawAny && stack.length === 0;
}

/**
 * Extract a flat field map from a request body by content-type, so required-
 * field (request-contract) validation works across JSON, urlencoded and XML.
 */
function extractFields(raw: string, ct: string): Record<string, string> {
  try {
    if (ct === "application/json") {
      const o = JSON.parse(raw);
      return o && typeof o === "object" && !Array.isArray(o) ? o : {};
    }
    if (ct === "application/x-www-form-urlencoded") {
      const m: Record<string, string> = {};
      for (const pair of raw.split("&")) {
        if (!pair) continue;
        const i = pair.indexOf("=");
        const dec = (s: string) => { try { return decodeURIComponent(s.replace(/\+/g, " ")); } catch { return s; } };
        m[dec(i < 0 ? pair : pair.slice(0, i))] = dec(i < 0 ? "" : pair.slice(i + 1));
      }
      return m;
    }
    if (ct === "application/xml" || ct === "text/xml") {
      const m: Record<string, string> = {};
      const re = /<([A-Za-z_][\w.-]*)>([^<]*)<\/\1>/g;
      let x: RegExpExecArray | null;
      while ((x = re.exec(raw)) !== null) m[x[1]] = x[2];
      return m;
    }
  } catch { /* fall through */ }
  return {};
}

export interface StrictMock {
  url: string;
  stop(): Promise<void>;
}

export interface StrictOpts {
  /** Request-contract required fields — a body missing/emptying any of these -> 400. */
  requiredFields?: string[];
}

export async function startStrictMock(port = 0, opts: StrictOpts = {}): Promise<StrictMock> {
  const validKey = process.env.API_KEY ?? "";
  const required = opts.requiredFields ?? [];

  const server = http.createServer((req, res) => {
    const method = (req.method ?? "GET").toUpperCase();
    const path = (req.url ?? "").split("?")[0];
    const send = (status: number, body?: any) => {
      res.writeHead(status, { "Content-Type": "application/json" });
      res.end(JSON.stringify(body ?? { status }));
    };

    if (path.includes("/invalid")) { send(404, { error: "not found", path }); return; }
    if (method !== "POST") { send(405, { error: "method not allowed", method }); return; }

    const key = (req.headers["x-api-key"] as string) ?? "";
    if (!key || key !== validKey) { send(401, { error: key ? "invalid api key" : "missing api key" }); return; }

    const accept = (req.headers["accept"] as string) ?? "";
    if (!acceptsJson(accept)) { send(406, { error: "not acceptable", accept }); return; }

    const ct = ((req.headers["content-type"] as string) ?? "").toLowerCase();
    const ctBare = ct.split(";")[0].trim();
    if (!ALLOWED_CT.includes(ctBare)) { send(415, { error: "unsupported media type", contentType: ct }); return; }

    const chunks: Buffer[] = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      const buf = Buffer.concat(chunks);
      const raw = buf.toString();
      let decoded = raw;
      try { decoded = decodeURIComponent(raw.replace(/\+/g, " ")); } catch { /* keep raw */ }

      if (buf.length > MAX_BYTES) { send(413, { error: "payload too large", bytes: buf.length }); return; }

      if (BINARY_CT.test(ctBare) && buf.length === 0) { send(400, { error: "empty binary body" }); return; }

      if (ctBare === "application/json" && raw.trim() !== "") {
        let parsed: any;
        try { parsed = JSON.parse(raw); }
        catch { send(400, { error: "malformed json" }); return; }
        if (parsed === null || typeof parsed !== "object") { send(400, { error: "json body must be an object" }); return; }
      }

      if ((ctBare === "application/xml" || ctBare === "text/xml") && raw.trim() !== "") {
        if (!xmlLooksWellFormed(raw)) { send(400, { error: "malformed xml" }); return; }
      }

      if (SQLI_XSS.test(raw) || SQLI_XSS.test(decoded)) { send(403, { error: "forbidden: injection detected" }); return; }

      // Request-contract validation: every required field must be present and non-empty.
      if (required.length) {
        const fields = extractFields(raw, ctBare);
        for (const rf of required) {
          const v = fields[rf];
          if (v === undefined || String(v).trim() === "") {
            send(400, { error: `missing required field: ${rf}` }); return;
          }
        }
      }

      send(201, { id: "10", createdAt: "now" });
    });
  });

  await new Promise<void>((resolve, reject) => {
    server.on("error", reject);
    server.listen(port, resolve);
  });
  const addr = server.address();
  const boundPort = typeof addr === "object" && addr ? addr.port : port;
  return {
    url: `http://127.0.0.1:${boundPort}`,
    stop: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}
