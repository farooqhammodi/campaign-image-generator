FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY static/ ./static/
RUN mkdir -p /app/data

# Render/Railway inject PORT; default to 8000 for local docker run
ENV PORT=8000
EXPOSE 8000

CMD ["python", "main.py"]
