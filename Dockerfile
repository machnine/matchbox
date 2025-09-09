# ---- Base Stage ----
FROM python:3.13-slim AS base

# ---- Builder Stage ----
# Use a different image to build our dependencies
FROM base AS builder

# Set the working directory
WORKDIR /app

# Install uv for dependency management
RUN pip install uv

# Copy just the files needed to compile the dependencies
COPY pyproject.toml .
COPY uv.lock .

# Generate a requirements.txt file with all dependencies pinned
RUN uv pip compile --no-header --output requirements.txt

# ---- Final Stage ----
# Use the base image for a clean, minimal production environment
FROM base AS final

# Set the working directory
WORKDIR /app

# Copy the generated requirements.txt from the builder stage
COPY --from=builder /app/requirements.txt .

# Install the dependencies from the generated requirements file
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . .

# Expose the port
EXPOSE 80

# Non-root user
RUN adduser --disabled-password --gecos "" appuser

# Command to run on container start
CMD [ "uvicorn", "api:api", "--host", "0.0.0.0", "--port", "80" ]