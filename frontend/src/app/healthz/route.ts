// Liveness for the frontend container / load balancer: answers as long as the Next.js server runs. No data, no auth.
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ status: "ok", app: "mclabor-frontend" });
}
