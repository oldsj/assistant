# syntax=docker/dockerfile:1

# Use Python 3.13 slim image
FROM python:3.13-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1

# Install uv
RUN pip install --no-cache-dir uv

# Create non-root user
RUN groupadd -r assistant && useradd -r -g assistant assistant

# Set working directory
WORKDIR /app

# Copy all files
COPY pyproject.toml uv.lock main.py ./

# Install dependencies using uv
RUN uv pip install --system --no-cache .

# Change ownership to non-root user
RUN chown -R assistant:assistant /app

# Switch to non-root user
USER assistant

# Expose application port
EXPOSE 5050

# Run the application
CMD ["python", "main.py"]
