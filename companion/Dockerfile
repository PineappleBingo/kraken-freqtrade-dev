FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt /app/companion/requirements.txt
RUN pip install --no-cache-dir -r /app/companion/requirements.txt

COPY . /app/companion

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "companion.main"]
