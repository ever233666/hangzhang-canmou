# 网页层零依赖；导出 PDF/Word 需要 Pillow 与 python-docx，中文 PDF 还需要系统 CJK 字体。
FROM python:3.11-slim

# 中文字体：没有它，PIL 排出来的 PDF 全是方块（或直接 UnicodeEncodeError）
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-noto-cjk \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    HOST=0.0.0.0 \
    AUTO_REFRESH=0 \
    TZ=Asia/Shanghai

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8000')+'/api/health',timeout=4)" || exit 1

CMD ["python", "run.py"]
