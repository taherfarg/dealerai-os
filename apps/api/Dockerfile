# One image, two processes (docs/01-system-architecture.md § 10):
#   the API     uvicorn dealerai.main:app --host 0.0.0.0 --port 8000   (the default)
#   the worker  python -m dealerai.worker
#
# Built from the repository's root, which is where .dockerignore is:
#   docker build -f apps/api/Dockerfile -t dealerai-api .
#
# Not in it: a browser. Marketing's compositor renders with Chromium, and the
# Sales module never does; `playwright install --with-deps chromium` goes here
# the day that module is deployed.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/apps/api/.venv/bin:$PATH"

WORKDIR /app/apps/api

# What it depends on first, so a change to the code does not install it all again.
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY apps/api/src ./src
RUN uv sync --frozen --no-dev

# config.repo_root() walks up from the code to the first package.json.
COPY package.json /app/package.json

# Nothing here is written at run time, so nothing needs to be owned.
USER nobody
EXPOSE 8000
CMD ["uvicorn", "dealerai.main:app", "--host", "0.0.0.0", "--port", "8000"]
