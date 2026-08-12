FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY . /app
RUN python -m pip install --no-cache-dir '.[serve]' \
    && useradd --create-home --uid 10001 prompt-playoff \
    && chown -R prompt-playoff:prompt-playoff /app

USER prompt-playoff
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["python", "-m", "uvicorn", "prompt_playoff.api:app", "--host", "0.0.0.0", "--port", "8000"]
