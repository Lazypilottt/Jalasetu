# Dockerfile for JalaSetu FastAPI backend (Render deployment)
# Uses Debian slim base and installs GDAL/PROJ system packages required by geospatial libraries.

FROM python:3.10-slim

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies for geospatial Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    git \
    curl \
    ca-certificates \
    libgdal-dev \
    gdal-bin \
    proj-bin \
    libproj-dev \
    libgeos-dev \
    libspatialindex-dev \
    libsqlite3-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Set GDAL environment variables so Python wheels can find headers at build time
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

# Create app directory
WORKDIR /app

# Copy only requirements first to leverage Docker cache
COPY requirements.txt /app/requirements.txt

# Upgrade pip and install Python requirements
RUN pip install --upgrade pip wheel setuptools
RUN pip install -r /app/requirements.txt

# Copy application code
COPY . /app

# Expose port (Render will map $PORT runtime env)
EXPOSE 8000

# Default command: use uvicorn. Render provides $PORT env variable.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
