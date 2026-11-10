# Offline Docker-Hub fallback; runtime tarball must pass scripts/fetch-node check.
FROM daifeilong-maibot-core:1.4.3
ENTRYPOINT []
USER root
COPY docker/runtime/node-linux.tar.xz /tmp/node.tar.xz
RUN python -c "import tarfile; t=tarfile.open('/tmp/node.tar.xz'); t.extractall('/opt/node-runtime', filter='data')" && mv /opt/node-runtime/node-* /opt/node && rm /tmp/node.tar.xz
ENV PATH=/opt/node/bin:$PATH HOME=/state/home CODEX_HOME=/state/auth
WORKDIR /opt/worker
COPY services/codex-worker/package*.json ./
RUN npm ci --omit=dev --ignore-scripts --registry=https://registry.npmjs.org --fetch-retries=0 --fetch-timeout=15000
COPY services/codex-worker/src ./src
RUN mkdir -p /state/auth /state/home /state/tasks && chown -R 1000:1000 /state
USER 1000:1000
CMD ["node","src/main.js"]
