# MC Labor frontend (Next.js) container image: multi-stage, standalone output, non-root, port 3000 inside the
# container only. NEXT_PUBLIC_API_URL is empty at build time so the browser calls /api on the site's own address.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# empty (default) = the browser calls /api on the site's own address; the DEMO profile passes http://localhost:8000
ARG NEXT_PUBLIC_API_URL=""
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
# HOSTNAME "::" = IPv6 and IPv4 (a hosting service's private network may resolve names to IPv6 only); PORT is
# overridden by the hosting service when it sets one.
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=::
RUN addgroup -S app && adduser -S -G app -u 10001 app
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static
COPY --from=build --chown=app:app /app/public ./public
USER app
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD wget -qO- http://127.0.0.1:3000/healthz || exit 1
CMD ["node", "server.js"]
