FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

RUN addgroup --system syncinerary \
    && adduser --system --ingroup syncinerary --home /app syncinerary

COPY pyproject.toml alembic.ini ./
COPY syncinerary ./syncinerary

RUN python -m pip install --no-cache-dir . \
    && mkdir -p /data/attachments \
    && chown -R syncinerary:syncinerary /app /data

USER syncinerary

ENV ATTACHMENT_UPLOAD_DIR=/data/attachments

EXPOSE 8000

CMD ["python", "-m", "syncinerary.api.server"]
