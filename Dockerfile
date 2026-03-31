FROM ghcr.io/astral-sh/uv:debian

# Install dependencies
RUN apt-get update && \
	apt-get install -y --no-install-recommends \
		gcc \
		git \
		python3-dev \
		libpq-dev \
		make && \
	rm -rf /var/lib/apt/lists/*

# Copy code
WORKDIR /app
COPY . .

# Expose port
EXPOSE 8000

# Run FastAPI
CMD ["uv", "run", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "8", "--loop", "uvloop"]
