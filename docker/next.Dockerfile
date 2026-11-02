# Сборка одного из Next.js-приложений монорепозитория: --build-arg APP=client | admin
FROM node:22-alpine AS build
ARG APP
WORKDIR /repo
COPY package.json package-lock.json ./
COPY packages/shared/package.json packages/shared/
COPY apps/client/package.json apps/client/
COPY apps/admin/package.json apps/admin/
RUN npm ci
COPY packages ./packages
COPY apps/${APP} ./apps/${APP}
ENV NEXT_TELEMETRY_DISABLED=1
# Адрес API для прокси /api/* фиксируется при сборке (rewrites в next.config.ts)
ARG API_INTERNAL_URL=http://api:8000
ENV API_INTERNAL_URL=${API_INTERNAL_URL}
ARG NEXT_PUBLIC_CLIENT_URL=http://localhost:3000
ENV NEXT_PUBLIC_CLIENT_URL=${NEXT_PUBLIC_CLIENT_URL}
RUN npm run build -w @islamic-car/${APP}

FROM node:22-alpine
ARG APP
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0
WORKDIR /srv
COPY --from=build /repo/apps/${APP}/.next/standalone ./
COPY --from=build /repo/apps/${APP}/.next/static ./apps/${APP}/.next/static
USER node
ENV APP_DIR=apps/${APP}
CMD ["sh", "-c", "node $APP_DIR/server.js"]
