FROM python:3.11-slim

# Install system dependencies for OpenCV
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

# Default port
ENV PORT=8000

# Expose port
EXPOSE 8000

# Use ENTRYPOINT with shell to ensure variable expansion
ENTRYPOINT ["/bin/sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
