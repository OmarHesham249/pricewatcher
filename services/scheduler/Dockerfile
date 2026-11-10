FROM python:3.12.6-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12.6-slim
WORKDIR /app
RUN groupadd -r sarak && useradd -r -g sarak -u 10001 sarak
COPY --from=builder /install /usr/local
COPY app ./app
USER 10001
CMD ["python", "-m", "app.scheduler"]
