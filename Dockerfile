FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput -v0 \
    && useradd --create-home --uid 1000 app && chown -R app /app
USER app

EXPOSE 8000
ENTRYPOINT ["./docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
