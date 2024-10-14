import time
import requests
import os
from flask import Flask, jsonify
from elasticsearch import Elasticsearch, exceptions
from threading import Thread


app = Flask(__name__)

PROMETHEUS_URL = 'http://prometheus:9090/api/v1/query'
ES_HOST ='http://elasticsearch:9200'
PG_BENCH_RESULTS_PATH = '/pgbench_results/pgbench_last_result.txt'
INDEX_NAME = 'health_metrics'

BASE_SCORE = 100
ERROR_WEIGHT = 80
LATENCY_WEIGHT = 15
DB_LATENCY_WEIGHT = 5

es = Elasticsearch([ES_HOST])

def create_index():
    mappings = {
        "mappings": {
            "properties": {
                "health_score": {"type": "float"},
                "error_rate": {"type": "float"},
                "avg_latency": {"type": "float"},
                "pg_bench_latency": {"type": "float"},
                "tps_bonus": {"type": "float"},
                "error_penalty": {"type": "float"},
                "latency_penalty": {"type": "float"},
                "db_latency_penalty": {"type": "float"},
                "timestamp": {"type": "date", "format": "epoch_second"}
            }
        }
    }
    if not es.indices.exists(index=INDEX_NAME):
        try:
            es.indices.create(index=INDEX_NAME, body=mappings)
            print(f"Index '{INDEX_NAME}' created successfully.")
        except Exception as e:
            print(f"Failed to create index '{INDEX_NAME}': {e}")

def fetch_metric(query):
    response = requests.get(PROMETHEUS_URL, params={'query': query})
    data = response.json().get('data', {}).get('result', [])
    if data:
        return float(data[0]['value'][1])
    return 0.0

def calculate_health():
    # rate of HTTP 500 errors
    error_rate = fetch_metric('rate(flask_http_request_total{status="500"}[5m])')
    # average http query latency
    avg_latency = fetch_metric('avg(flask_http_request_duration_seconds_sum / flask_http_request_duration_seconds_count)')

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

    print(metrics)
    return metrics

def send_to_elasticsearch(metrics):
    try:
        es.index(index=INDEX_NAME, body=metrics)
        print("Metrics successfully sent to Elasticsearch.")
    except Exception as e:
        print(f"Failed to send metrics to Elasticsearch: {e}")

@app.route('/health')
def health():
    metrics = calculate_health()
    return jsonify(metrics)

def periodic_task():
    time.sleep(20)
    create_index()
    while True:
        metrics = calculate_health()
        send_to_elasticsearch(metrics)
        time.sleep(10)

if __name__ == "__main__":
    thread = Thread(target=periodic_task)
    thread.start()

    app.run(host='0.0.0.0', port=5002)
