FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV API_PORT=8000

COPY requirements/runtime.txt /app/requirements/runtime.txt
RUN pip install --no-cache-dir -r /app/requirements/runtime.txt

COPY . /app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
