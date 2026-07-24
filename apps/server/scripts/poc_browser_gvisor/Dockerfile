# PoC image (NOT a product image): gVisor(runsc) + Playwright Chromium on the
# SAME base as the server runtime (python:3.12-slim). Self-contained; the product
# Dockerfile is untouched. Build context = this directory.
FROM python:3.12-slim

# CN-friendly mirrors (override with --build-arg for GHA/overseas). RUNSC_URL can
# point at a mirror if storage.googleapis.com is blocked.
ARG APT_MIRROR=mirrors.aliyun.com
ARG PYPI_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple/
ARG RUNSC_URL=https://storage.googleapis.com/gvisor/releases/release/latest/x86_64/runsc

# Browser bundle lives OUTSIDE /usr on purpose, to force the L2 sandbox to add an
# explicit ro-bind for it (a key "diff vs product OCI" finding). Playwright's
# default download CDN is reachable from this host, so no mirror override.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    PIP_INDEX_URL=${PYPI_INDEX} \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# apt mirror + base tooling (ca-certificates for TLS/pip, procps/iproute2 for debugging).
RUN set -eux; \
    if [ -n "$APT_MIRROR" ]; then \
      if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|security.debian.org|${APT_MIRROR}|g" \
          /etc/apt/sources.list.d/debian.sources; \
      elif [ -f /etc/apt/sources.list ]; then \
        sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|security.debian.org|${APT_MIRROR}|g" \
          /etc/apt/sources.list; \
      fi; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates procps iproute2; \
    rm -rf /var/lib/apt/lists/*

# runsc: a single static binary is enough for `runsc run`. No sha verify (PoC).
RUN set -eux; \
    python -c "import urllib.request; open('/usr/local/bin/runsc','wb').write(urllib.request.urlopen('${RUNSC_URL}', timeout=600).read())"; \
    chmod 0755 /usr/local/bin/runsc; \
    runsc --version

# Playwright into SYSTEM site-packages (/usr/local/... => visible to a sandbox
# that ro-binds /usr) + Chromium bundle + its OS deps (--with-deps => apt libs).
RUN set -eux; \
    pip install --no-cache-dir playwright; \
    playwright install --with-deps chromium
RUN set -eux; \
    playwright --version; \
    python -c "from playwright.sync_api import sync_playwright; print('playwright import OK')"

COPY *.py *.sh /poc/
RUN chmod +x /poc/*.sh

WORKDIR /poc
CMD ["bash"]
