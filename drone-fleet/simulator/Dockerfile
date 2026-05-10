FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git wget curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pymongo pymavlink

COPY *.py .

CMD ["python", "sitl_bridge.py"]