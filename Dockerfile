FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY config ./config
COPY data ./data
COPY Procfile ./

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "-m", "pulse.server"]
