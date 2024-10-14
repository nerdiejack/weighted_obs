
FROM python:3.8-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY health.py .
EXPOSE 5002
CMD ["python", "health.py"]
