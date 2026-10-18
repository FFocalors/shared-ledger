# syntax=docker/dockerfile:1.7

FROM python:3.12-slim-bookworm AS dependencies
COPY --from=ghcr.io/astral-sh/uv:0.10.8 /uv /uvx /usr/local/bin/

WORKDIR /srv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

# The primary context is agent/ and its root .dockerignore is an allowlist.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim-bookworm AS runtime

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH=/srv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TMPDIR=/var/lib/shared-ledger-agent/.p1-06-tmp

WORKDIR /srv
COPY --from=dependencies /opt/venv /opt/venv
COPY app /srv/agent/app
COPY contracts /srv/agent/contracts
COPY migrations /srv/agent/migrations
COPY requirements-contracts.txt /srv/agent/requirements-contracts.txt
COPY toolchain-contracts.json /srv/agent/toolchain-contracts.json
COPY .env.example /srv/agent/.env.example

RUN groupadd --gid 10001 agent \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/agent --shell /usr/sbin/nologin agent \
    && install -d --owner=10001 --group=10001 --mode=0700 /var/lib/shared-ledger-agent \
    && install -d --owner=10001 --group=10001 --mode=0700 /var/lib/shared-ledger-agent/.p1-06-tmp

USER 10001:10001
ENTRYPOINT ["python", "-m", "agent.app.main"]
CMD ["--workers", "1"]
