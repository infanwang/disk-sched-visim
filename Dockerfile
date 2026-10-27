# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 纯标准库，没有 requirements.txt —— 直接拷源码即可
COPY disksched.py ./
COPY disk_sched/ ./disk_sched/
COPY web/ ./web/

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=2).status == 200 else 1)"

CMD ["python", "disksched.py", "serve", "--host", "0.0.0.0", "--port", "8765", "--no-open"]
