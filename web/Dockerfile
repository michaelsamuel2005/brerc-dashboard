# Multi-stage build: compile the static site with Node, then serve it with a
# tiny nginx. The Caddy reverse proxy sits in front and routes /api and /tiles
# same-origin (see proxy/Caddyfile), so this image only needs to serve the
# static assets on :80.

# --- Build stage -----------------------------------------------------------
FROM node:26-alpine AS build
WORKDIR /app
# Install against the lockfile for reproducibility (falls back to install if the
# lockfile is absent).
COPY package.json package-lock.json* ./
RUN npm ci || npm install
COPY . .
RUN npm run build

# --- Runtime stage ---------------------------------------------------------
FROM nginx:1.27-alpine AS runtime
# SPA-friendly config with long-lived caching for hashed assets.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/ /usr/share/nginx/html/
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -qO- http://localhost:80/ >/dev/null 2>&1 || exit 1
