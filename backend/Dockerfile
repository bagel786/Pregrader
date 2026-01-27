FROM python:3.11-slim

# Install system dependencies for OpenCV (updated package names for Debian Trixie)
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Default port (Railway will override via PORT env var)
ENV PORT=8000

# Expose port
EXPOSE 8000

# Start command - using shell form for proper variable expansion
CMD uvicorn main:app --host 0.0.0.0 --port $PORT
