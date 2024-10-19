FROM python:3.8-slim
RUN pip install Flask prometheus_flask_exporter
WORKDIR  /app
COPY . .
CMD ["python", "app3.py"]
