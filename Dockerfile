FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1

RUN useradd --create-home --uid 10001 c360
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE NOTICE /app/
COPY src /app/src
COPY configs /app/configs
RUN pip install --no-cache-dir --disable-pip-version-check uv \
    && uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}"
USER c360
ENTRYPOINT ["/app/.venv/bin/c360"]
