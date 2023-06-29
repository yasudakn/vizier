FROM python:3.11.4-slim
RUN apt-get update && apt-get install -y --no-install-recommends build-essential wget && \
    apt-get purge -y --auto-remove && \
    rm -rf /var/lib/apt/lists/*

COPY ./ .

RUN pip3 install --no-cache-dir -U -r requirements.txt && \
    pip3 install --no-cache-dir -U -r requirements-jax.txt && \
    pip3 install -U "google-vizier[jax]"

RUN ./build_protos.sh
