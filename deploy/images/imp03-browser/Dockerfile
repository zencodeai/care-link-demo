FROM mcr.microsoft.com/playwright@sha256:9beb546099e11f52d62e505537914870e01a67e0e6b00ae41da4775324e73dbe
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libnss3-tools \
    && rm -rf /var/lib/apt/lists/*
COPY playwright-core /opt/playwright-core
COPY ca /trust
RUN chmod -R a+rX /opt/playwright-core /trust
USER pwuser
ENV HOME=/run/browser-home PLAYWRIGHT_BROWSERS_PATH=/ms-playwright NODE_EXTRA_CA_CERTS=/trust/ca.crt
CMD ["node", "/opt/playwright-core/cli.js", "--version"]
