FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --upgrade pip && pip install .

RUN mkdir -p /data && chown nobody:nogroup /data

USER nobody

ENTRYPOINT ["dropbox-to-gdrive"]
CMD ["migrate"]
