import json
import time
import requests
import os
from flask import Flask, jsonify
from prometheus_api_client import PrometheusConnect
from threading import Thread
from kafka import KafkaProducer


app = Flask(__name__)

PROMETHEUS_URL = os.getenv('PROMETHEUS_URL', 'http://prometheus:9090')
KAFKA_BROKER = os.getenv('KAFKA_BROKER', 'kafka:9092')
PG_BENCH_RESULTS_PATH = '/pgbench_results/pgbench_last_result.txt'
TOPIC_NAME = 'health-metrics'
BASE_SCORE = 100
ERROR_WEIGHT = 80
LATENCY_WEIGHT = 15
DB_LATENCY_WEIGHT = 5
APP_NAMES = ['flask-app:5000', 'app1:5000', 'app2:5000', 'app3:5000', 'app4:5000']

prom = PrometheusConnect(url=PROMETHEUS_URL, disable_ssl=True)

producer = KafkaProducer(
    bootstrap_servers=KAFKA_BROKER,
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

def fetch_prometheus_metric(query):
    try:
        result = prom.custom_query(query)
        if result:
            return float(result[0]['value'][1])
    except Exception as e:
        print(f"Error fetching metric: {e}")
    return 0.0

def calculate_health(app_name):
    error_rate_query = f'rate(flask_http_request_total{{instance="{app_name}", status="500"}}[5m])'
    avg_latency_query = f'rate(flask_http_request_duration_seconds_sum{{instance="{app_name}"}}[5m]) / 'f'rate(flask_http_request_duration_seconds_count{{instance="{app_name}"}}[5m])'

    error_rate = fetch_prometheus_metric(error_rate_query)
    avg_latency = fetch_prometheus_metric(avg_latency_query)

    pg_bench_latency = 1.0
    pg_bench_tps = 10.0
    try:
        if not os.path.exists(PG_BENCH_RESULTS_PATH):
            print(f"File {PG_BENCH_RESULTS_PATH} does not exist.")
        else:
            print(f"Reading file {PG_BENCH_RESULTS_PATH}...")
            with open(PG_BENCH_RESULTS_PATH, 'r') as f:
                pgbench_output = f.readlines()
            for line in pgbench_output:
                if "latency average" in line:
                    parts = line.split("=")
                    if len(parts) > 1:
                        pg_bench_latency = float(parts[1].strip().partition(" ")[0])
                        print(f"Parsed latency: {pg_bench_latency}")
                elif "tps" in line:
                    parts = line.split("=")
                    if len(parts) > 1:
                        pg_bench_tps = float(line.split("=")[1].strip().partition(" ")[0])
                        print(f"Parsed tps: {pg_bench_tps}")
    except Exception as e:
        print(f"Exception occured while reading pgbench results: {e}")

    error_penalty = ERROR_WEIGHT * min(1, error_rate)
    latency_penalty = LATENCY_WEIGHT * min(1, avg_latency / 2)  # Normalizing by dividing by 2
    db_latency_penalty = DB_LATENCY_WEIGHT * min(1, pg_bench_latency / 0.5)
    tps_bonus = min(10, pg_bench_tps) / 10
    health_score = BASE_SCORE - (error_penalty + latency_penalty + db_latency_penalty) + tps_bonus * 10
    health_score = max(0, health_score)  # Ensure it doesn't go below

    metrics = {
        "app_name": app_name,
        "health_score": health_score,
        "error_rate": error_rate,
        "avg_latency": avg_latency,
        "pg_bench_latency": pg_bench_latency,
        "tps_bonus": tps_bonus,
        "error_penalty": error_penalty,
        "latency_penalty": latency_penalty,
        "db_latency_penalty": db_latency_penalty,
        "timestamp": time.time()
    }

    print(f"Metrics generated: {metrics}")
    return metrics

def send_metrics_to_kafka(metrics):
    try:
        producer.send(TOPIC_NAME, metrics)
        producer.flush()
        print(f"Metrics sent to Kafka: {metrics}")
    except Exception as e:
        print(f"Failed to send metrics to Kafka: {e}")

@app.route('/health')
def health():
    for app_name in APP_NAMES :
        metrics = calculate_health(app_name)
        return jsonify(metrics)

def periodic_task():
    while True:
        for app_name in APP_NAMES:
            metrics = calculate_health(app_name)
            send_metrics_to_kafka(metrics)
            time.sleep(10)

if __name__ == "__main__":
    thread = Thread(target=periodic_task)
    thread.start()

    app.run(host='0.0.0.0', port=5002)
