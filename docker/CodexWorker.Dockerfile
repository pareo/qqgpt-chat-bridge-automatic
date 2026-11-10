FROM node:22-bookworm-slim
WORKDIR /opt/worker
COPY services/codex-worker/package*.json ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force
COPY services/codex-worker/src ./src
RUN mkdir -p /state/auth /state/home /state/tasks && chown -R node:node /state
USER node
ENV HOME=/state/home CODEX_HOME=/state/auth
CMD ["node","src/main.js"]
