FROM python:3.11-slim

# Install system dependencies for OpenCV
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    libfontconfig1 \
    libice6 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Run startup check to verify dependencies
RUN python startup_check.py || echo "Warning: Startup check had issues"

# Create temp directory
RUN mkdir -p temp_uploads && chmod 777 temp_uploads

# Default port (Railway will override this)
ENV PORT=8000

# Expose port
EXPOSE 8000

# Use CMD instead of ENTRYPOINT for Railway compatibility
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
