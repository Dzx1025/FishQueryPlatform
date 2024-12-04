FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    GDAL_VERSION=3.6.2

# Set work directory
WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    software-properties-common \
    gnupg \
    wget \
    curl \
    git \
    pkg-config \
    python3-dev \
    postgresql-client \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install GDAL dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev \
    gdal-bin \
    && rm -rf /var/lib/apt/lists/*

# Set GDAL environment variables
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal \
    C_INCLUDE_PATH=/usr/include/gdal \
    GDAL_CONFIG=/usr/bin/gdal-config

# Verify GDAL installation and get version
RUN gdal-config --version

# Install Python dependencies
COPY requirements.txt /app/

# Install GDAL Python bindings first
RUN pip install --no-cache-dir wheel setuptools
RUN pip install --no-cache-dir GDAL==$(gdal-config --version)

# Install remaining requirements
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . /app/