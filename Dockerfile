# Python 3.12
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements.txt
COPY requirements.txt .

# Install the dependencies
RUN pip install --no-cache -r requirements.txt

# Copy the content of the local src directory to the working directory
COPY . .

# Expose the port
EXPOSE 80

# Non-root user
RUN adduser --disabled-password --gecos "" appuser

# run tests
RUN python -m pytest

# Command to run on container start
CMD [ "uvicorn", "api:api", "--host", "0.0.0.0", "--port", "80" ]