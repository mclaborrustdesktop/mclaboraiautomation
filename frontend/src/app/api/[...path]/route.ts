/**
 * Same-origin API proxy for hosted deployments (deploy/railway): the browser calls /api/... on the website's own
 * address and this handler forwards the request over the private network to the FastAPI service named by
 * BACKEND_INTERNAL_URL (for example http://backend.railway.internal:8000). The backend then has no public address.
 *
 * What is forwarded: method, path and query, the JSON body, and the headers the backend needs to know who is asking
 * (Authorization for the sign-in token, Cookie and Cf-Access-Jwt-Assertion for Cloudflare Access, X-Request-ID).
 * Read at run time, so the target can be changed without a rebuild. On this PC (NEXT_PUBLIC_API_URL set) the
 * browser talks to the backend directly and this file is not used.
 */
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const FORWARD = ["authorization", "content-type", "accept", "cookie", "cf-access-jwt-assertion", "cf-access-authenticated-user-email", "x-request-id", "if-none-match"];
const RETURN = ["content-type", "x-request-id", "retry-after", "cache-control", "etag"];

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const target = (process.env.BACKEND_INTERNAL_URL ?? "").replace(/\/+$/, "");
  if (!target) {
    return Response.json({ detail: "The website is not connected to its API (BACKEND_INTERNAL_URL is not set)." }, { status: 503 });
  }
  const { path } = await ctx.params;
  const url = `${target}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers = new Headers();
  for (const name of FORWARD) {
    const v = req.headers.get(name);
    if (v) headers.set(name, v);
  }
  const hasBody = !["GET", "HEAD"].includes(req.method);
  let upstream: Response;
  try {
    upstream = await fetch(url, { method: req.method, headers, body: hasBody ? await req.arrayBuffer() : undefined, redirect: "manual", cache: "no-store" });
  } catch {
    return Response.json({ detail: "The API is not reachable right now. Please try again in a moment." }, { status: 503 });
  }
  const out = new Headers();
  for (const name of RETURN) {
    const v = upstream.headers.get(name);
    if (v) out.set(name, v);
  }
  return new Response(upstream.status === 204 ? null : upstream.body, { status: upstream.status, headers: out });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
