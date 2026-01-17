# Use the official Python 3.10 image as the base image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory to the location where the Django project is
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    ipmitool \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the working directory
COPY requirements.txt .

# Install Python dependencies
#RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project into the working directory (where manage.py is located)
COPY . .

# Expose port (placeholder, will be used with the ENV variable)
#EXPOSE 8000

# Start the Django application using daphne and bind to the specified port
# daphne --bind 0.0.0.0 -p 8000 cineor.asgi:application
# gunicorn --bind 0.0.0.0:8000 cineor.wsgi:application

CMD ["sh", "-c", "python control.py"]