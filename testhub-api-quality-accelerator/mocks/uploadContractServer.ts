import http from "http";

/**
 * Spec-compliant mock for the form-data upload contract exercised by
 * src/tests/formExample. Unlike the generic MockServer (exact method+path,
 * no request introspection) this server inspects the real request signals —
 * method, auth header, Accept, Content-Type, body size and the parsed
 * multipart parts — and returns standards-correct status codes.
 *
 * Contract for POST /api/upload (checks applied in this order):
 *   1. method !== POST                         -> 405
 *   2. x-api-key missing or wrong              -> 401
 *   3. Accept present and not JSON-compatible  -> 406
 *   4. Content-Type not multipart/form-data    -> 415
 *   5. body larger than MAX_UPLOAD_BYTES       -> 413
 *   6. a field `simulateDuplicate=true`        -> 409  (deterministic trigger:
 *                                                       "duplicate" is stateful
 *                                                       and can't be inferred
 *                                                       from a single request)
 *   7. an `Email` field present but invalid    -> 400
 *   8. a file part present but zero bytes       -> 400
 *   9. otherwise                                -> 201
 * Any other path -> 404 (covers the "Invalid Endpoint" scenario).
 */

const MAX_UPLOAD_BYTES = 1024 * 1024; // 1 MB — anything larger is "too large"

interface Part {
    name: string;
    filename?: string;
    size: number;
    value: string;
}

/** Minimal multipart/form-data parser — enough to read field values and file sizes. */
function parseMultipart(buf: Buffer, boundary: string): Part[] {
    const parts: Part[] = [];
    const delimiter = Buffer.from(`--${boundary}`);
    let start = buf.indexOf(delimiter);
    if (start === -1) return parts;
    start += delimiter.length;

    while (start < buf.length) {
        // End of stream: "--boundary--"
        if (buf.slice(start, start + 2).toString() === "--") break;
        // Skip the CRLF after the boundary
        if (buf.slice(start, start + 2).toString() === "\r\n") start += 2;

        const next = buf.indexOf(delimiter, start);
        if (next === -1) break;

        // The part content ends with a CRLF before the next boundary
        const rawPart = buf.slice(start, next - 2);
        const headerEnd = rawPart.indexOf("\r\n\r\n");
        if (headerEnd !== -1) {
            const headerText = rawPart.slice(0, headerEnd).toString();
            const content = rawPart.slice(headerEnd + 4);
            const nameMatch = headerText.match(/name="([^"]*)"/i);
            const fileMatch = headerText.match(/filename="([^"]*)"/i);
            parts.push({
                name: nameMatch ? nameMatch[1] : "",
                filename: fileMatch ? fileMatch[1] : undefined,
                size: content.length,
                value: content.toString(),
            });
        }
        start = next + delimiter.length;
    }
    return parts;
}

const isValidEmail = (v: string) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v.trim());
const acceptsJson = (a: string) =>
    !a || /application\/json|\*\/\*/i.test(a);

export interface UploadMock {
    url: string;
    stop(): Promise<void>;
}

// Pass port 0 to bind an ephemeral port (avoids clashing with formExample's
// fixed 4010 when suites run together); the bound URL is returned in `url`.
export async function startUploadMock(port = 4010): Promise<UploadMock> {
    const validKey = process.env.API_KEY ?? "";

    const server = http.createServer((req, res) => {
        const send = (status: number, body: any) => {
            res.writeHead(status, { "Content-Type": "application/json" });
            res.end(JSON.stringify(body));
        };

        const url = (req.url ?? "").split("?")[0];

        // Only /api/upload is a real route; everything else is 404.
        if (url !== "/api/upload") {
            send(404, { error: "not found", path: req.url });
            return;
        }

        // 1. Method
        if (req.method !== "POST") {
            send(405, { error: "method not allowed", method: req.method });
            return;
        }

        // 2. Auth
        const key = (req.headers["x-api-key"] as string) ?? "";
        if (!key || key !== validKey) {
            send(401, { error: key ? "invalid api key" : "missing api key" });
            return;
        }

        // 3. Accept
        const accept = (req.headers["accept"] as string) ?? "";
        if (!acceptsJson(accept)) {
            send(406, { error: "not acceptable", accept });
            return;
        }

        // 4. Content-Type
        const contentType = (req.headers["content-type"] as string) ?? "";
        if (!/^multipart\/form-data/i.test(contentType)) {
            send(415, { error: "unsupported media type", contentType });
            return;
        }

        // Buffer the body, then apply size/content checks.
        const chunks: Buffer[] = [];
        req.on("data", (c) => chunks.push(c));
        req.on("end", () => {
            const body = Buffer.concat(chunks);

            // 5. Size
            if (body.length > MAX_UPLOAD_BYTES) {
                send(413, { error: "payload too large", bytes: body.length });
                return;
            }

            const boundaryMatch = contentType.match(/boundary=(.+)$/i);
            const parts = boundaryMatch
                ? parseMultipart(body, boundaryMatch[1].trim())
                : [];

            const field = (name: string) =>
                parts.find((p) => p.name.toLowerCase() === name.toLowerCase() && !p.filename);
            const files = parts.filter((p) => p.filename !== undefined);

            // 6. Deterministic duplicate trigger
            if (field("simulateDuplicate")?.value.trim() === "true") {
                send(409, { error: "duplicate upload" });
                return;
            }

            // 7. Email validity (only when an Email field is present)
            const email = field("Email");
            if (email && email.value !== "" && !isValidEmail(email.value)) {
                send(400, { error: "invalid email", email: email.value });
                return;
            }

            // 8. Empty file
            if (files.some((f) => f.size === 0)) {
                send(400, { error: "empty file" });
                return;
            }

            // 9. Success
            send(201, {
                status: "uploaded",
                files: files.map((f) => ({ field: f.name, filename: f.filename, size: f.size })),
                fields: parts
                    .filter((p) => p.filename === undefined)
                    .reduce((o, p) => ({ ...o, [p.name]: p.value }), {}),
            });
        });
    });

    await new Promise<void>((resolve, reject) => {
        server.on("error", reject);
        server.listen(port, resolve);
    });

    const addr = server.address();
    const boundPort = typeof addr === "object" && addr ? addr.port : port;
    return {
        url: `http://localhost:${boundPort}`,
        stop: () => new Promise<void>((resolve) => server.close(() => resolve())),
    };
}
