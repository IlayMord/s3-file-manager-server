FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/server.py .
COPY app/templates.py .
COPY app/templates/ ./templates/
COPY app/static/ ./static/

RUN useradd -m appuser
USER appuser

EXPOSE 80
CMD ["python", "server.py"]
