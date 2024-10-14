from multiprocessing.pool import job_counter

from flask import Flask, Response, jsonify
from jinja2.compiler import generate
from prometheus_client import generate_latest
from prometheus_flask_exporter import PrometheusMetrics
import requests
import time
import os
import logging

app = Flask(__name__)
metrics = PrometheusMetrics(app, path=None)

PG_BENCH_RESULTS_PATH = '/pgbench_results/pgbench_last_result.txt'

# Basic logging setup
logging.basicConfig(filename='/var/log/app.log', level=logging.INFO)

@app.route("/")
def hello():
    app.logger.info('Serving main endpoint')
    return "Hello World!"

@app.route("/error")
def error():
    app.logger.error('This is an error!')
    return "Error occurred!", 500

@app.route('/heavy')
def heavy():
    start_time = time.time()
    count = 0
    while time.time() - start_time < 5:
        count += 1
    return jsonify({"message": "Completed heavy computation", "iterations": count})

@app.route('/db-test')
def db_test():
    try:
        if not os.path.exists(PG_BENCH_RESULTS_PATH):
            return jsonify({"status": "error", "message": "pgbench results not available"}), 500

        with open(PG_BENCH_RESULTS_PATH, 'r') as f:
            pgbench_output = f.readlines()

        latency = None
        tps = None
        for line in pgbench_output:
            if "latency average" in line:
                latency = line.split("=")[1].strip() if "=" in line else None
            elif "tps" in line:
                tps = line.split("=")[1].strip() if "=" in line else None
        return jsonify({
            "status": "success",
            "latency": latency,
            "tps": tps
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/metrics")
def metrics_endpoint():
    return Response(generate_latest(), mimetype="text/plain")

if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True)
