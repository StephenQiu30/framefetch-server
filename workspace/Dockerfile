# syntax=docker/dockerfile:1.7

FROM node:24-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1 AS dependencies

ARG PNPM_VERSION=12.4.2
ENV SOURCE_DATE_EPOCH=0
WORKDIR /app/workspace

RUN --mount=type=cache,target=/root/.npm \
    npm install --global "pnpm@${PNPM_VERSION}" \
    && chown node:node /app/workspace
USER node
COPY --link --chown=1000:1000 package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN --mount=type=cache,id=framefetch-pnpm,target=/pnpm/store,uid=1000,gid=1000,sharing=locked \
    pnpm install --store-dir /pnpm/store --frozen-lockfile --ignore-scripts \
    && pnpm --store-dir /pnpm/store rebuild
FROM dependencies AS development
ENV NODE_ENV=development HOSTNAME=0.0.0.0 PORT=8130
COPY --link --chown=1000:1000 . ./
USER node
EXPOSE 8130
CMD ["node", "node_modules/next/dist/bin/next", "dev", "--webpack", "--hostname", "0.0.0.0", "--port", "8130"]

FROM dependencies AS workspace-builder
COPY --link --chown=1000:1000 . ./
RUN node node_modules/next/dist/bin/next build --webpack

FROM node:24-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1 AS runtime
ENV NODE_ENV=production HOSTNAME=0.0.0.0 PORT=8130
WORKDIR /app/workspace
COPY --link --from=workspace-builder --chown=1000:1000 /app/workspace/.next/standalone ./
COPY --link --from=workspace-builder --chown=1000:1000 /app/workspace/.next/static ./.next/static
COPY --link --from=workspace-builder --chown=1000:1000 /app/workspace/public ./public
RUN mkdir -p content && chown node:node content
USER node
EXPOSE 8130
CMD ["node", "server.js"]
