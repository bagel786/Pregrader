FROM python:3.11-slim

# Install system dependencies for OpenCV (minimal set)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies with minimal memory footprint
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Run startup check to verify dependencies
RUN python startup_check.py || echo "Warning: Startup check had issues"

# Create temp directory
RUN mkdir -p temp_uploads && chmod 777 temp_uploads

# Default port (Railway will override this)
ENV PORT=8000

# Memory optimization: limit OpenCV threads
ENV OMP_NUM_THREADS=2
ENV OPENBLAS_NUM_THREADS=2
ENV MKL_NUM_THREADS=2
# Release freed memory back to OS more aggressively
ENV MALLOC_TRIM_THRESHOLD_=65536

# Expose port
EXPOSE 8000

# Use CMD with single worker to limit memory
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --limit-concurrency 10

