import time
import random
import os
from prometheus_flask_exporter import PrometheusMetrics
from prometheus_client import generate_latest
from flask import Response, Flask, jsonify


app = Flask(__name__)

metrics = PrometheusMetrics(app)

@app.route('/process')
def process_data():
    process_time = random.uniform(0.1, 0.5)
    time.sleep(process_time)
    return jsonify({"status": "processing", "time_taken": process_time})

@app.route("/error")
def error():
    return "Error occurred!", 500

@app.route('/metrics')
def metrics_endpoint():
    return Response(generate_latest(), mimetype="text/plain")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)