FROM python:3.11-slim

# Install system deps for psycopg (pg_config), onnxruntime,
# tesseract OCR, and poppler (pdf2image)
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
        tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Pre-download the embedding model into the image so the serving container
# never downloads from scratch at runtime.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='nlp_models/embeddings')"

# Entrypoint pre-warms the model in a tiny process (cache trust fix) then execs
# uvicorn with the args from `command:` in docker-compose.yml.
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Run with single worker as required by CLAUDE.md rule 4
EXPOSE 8011
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--workers", "1", "--host", "0.0.0.0", "--port", "8011"]
