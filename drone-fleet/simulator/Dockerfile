FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir pymongo

COPY simulator.py .

CMD ["python", "simulator.py"]
