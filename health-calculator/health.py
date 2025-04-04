import json
import time
import requests
import os
import yaml
from flask import Flask, jsonify, request, render_template
from prometheus_api_client import PrometheusConnect
from threading import Thread, Lock
from kafka import KafkaProducer
from datetime import datetime

app = Flask(__name__)

PROMETHEUS_URL = os.getenv('PROMETHEUS_URL', 'http://prometheus:9090')
KAFKA_BROKER = os.getenv('KAFKA_BROKER', 'kafka:9092')
PG_BENCH_RESULTS_PATH = '/pgbench_results/pgbench_last_result.txt'
WEIGHTS_CONFIG_PATH = '/yaml/health_weights.yml'
TOPIC_NAME = 'health-metrics'
APP_NAMES = ['flask-app:5000', 'app2:5000', 'app3:5000', 'app4:5000']

# Prometheus and Kafka connections
prom = PrometheusConnect(url=PROMETHEUS_URL, disable_ssl=True)
producer = KafkaProducer(
    bootstrap_servers=KAFKA_BROKER,
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

weights = {}
weights_lock = Lock()

class HealthScoreHistory:
    def __init__(self, max_size=100):
        self.history = {}
        self.max_size = max_size
        self.lock = Lock()
        
    def add_score(self, app_name, score, timestamp):
        with self.lock:
            if app_name not in self.history:
                self.history[app_name] = []
            
            self.history[app_name].append({
                'score': score,
                'timestamp': timestamp
            })
            
            # Keep only last max_size entries
            if len(self.history[app_name]) > self.max_size:
                self.history[app_name] = self.history[app_name][-self.max_size:]
                
    def get_trend(self, app_name):
        with self.lock:
            if app_name not in self.history:
                return None
            return self.history[app_name]

health_history = HealthScoreHistory()

def validate_metrics(metrics):
    validation_rules = {
        'error_rate': {'min': 0, 'max': 100},
        'avg_latency': {'min': 0, 'max': 60},  # seconds
        'pg_bench_latency': {'min': 0, 'max': 10},  # seconds
        'pg_bench_tps': {'min': 0, 'max': 10000}  # TPS = transactions per second
    }
    
    for metric, value in metrics.items():
        if metric in validation_rules:
            rules = validation_rules[metric]
            if value < rules['min'] or value > rules['max']:
                print(f"Warning: {metric} value {value} outside expected range")
                return False
    return True

def check_alert_conditions(metrics, health_score):
    alert_conditions = {
        'critical': {
            'health_score': 50,
            'error_rate': 10,
            'latency': 5
        },
        'warning': {
            'health_score': 70,
            'error_rate': 5,
            'latency': 2
        }
    }
    
    alerts = []
    
    if health_score < alert_conditions['critical']['health_score']:
        alerts.append({
            'level': 'critical',
            'message': f'Health score critically low: {health_score}'
        })
    elif health_score < alert_conditions['warning']['health_score']:
        alerts.append({
            'level': 'warning',
            'message': f'Health score warning: {health_score}'
        })
    
    if metrics.get('error_rate', 0) > alert_conditions['critical']['error_rate']:
        alerts.append({
            'level': 'critical',
            'message': f'Error rate critically high: {metrics["error_rate"]}'
        })
    elif metrics.get('error_rate', 0) > alert_conditions['warning']['error_rate']:
        alerts.append({
            'level': 'warning',
            'message': f'Error rate warning: {metrics["error_rate"]}'
        })
    
    return alerts

def load_weights():
    try:
        with open(WEIGHTS_CONFIG_PATH, 'r') as f:
            config = yaml.safe_load(f)
            
            # Validate required fields and types
            required_fields = {
                'weights': ['base_score', 'error_weight', 'latency_weight', 
                           'db_latency_weight', 'latency_threshold', 'tps_bonus_max'],
                'thresholds': ['error_rate', 'latency', 'db_latency']
            }
            
            for section, fields in required_fields.items():
                if section not in config:
                    raise ValueError(f"Missing section: {section}")
                for field in fields:
                    if field not in config[section]:
                        raise ValueError(f"Missing field: {field} in {section}")
                    if not isinstance(config[section][field], (int, float)) or config[section][field] < 0:
                        raise ValueError(f"Invalid value for {field} in {section}")
            
            with weights_lock:
                global weights
                weights = config
                
    except Exception as e:
        print(f"Error loading weights: {e}")
        # Set default weights if file loading fails
        with weights_lock:
            weights = {
                'weights': {
                    'base_score': 100,
                    'error_weight': 30,
                    'latency_weight': 20,
                    'db_latency_weight': 10,
                    'latency_threshold': 5,
                    'tps_bonus_max': 10
                },
                'thresholds': {
                    'error_rate': 4,
                    'latency': 2,
                    'db_latency': 0.5
                }
            }

def save_weights():
    try:
        with open(WEIGHTS_CONFIG_PATH, 'w') as f:
            yaml.dump(weights, f)
    except Exception as e:
        print(f"Error saving weights: {e}")

def fetch_prometheus_metric(query):
    try:
        result = prom.custom_query(query)
        if result and len(result) > 0 and 'value' in result[0]:
            return float(result[0]['value'][1])
        else:
            print(f"Invalid or empty result for query: {query}")
            return None
    except Exception as e:
        print(f"Error fetching metric: {e}")
        return None

def get_pgbench_metrics():
    try:
        if not os.path.exists(PG_BENCH_RESULTS_PATH):
            print(f"File {PG_BENCH_RESULTS_PATH} does not exist.")
            return None, None
            
        with open(PG_BENCH_RESULTS_PATH, 'r') as f:
            pgbench_output = f.readlines()
            
        pg_bench_latency = None
        pg_bench_tps = None
        
        for line in pgbench_output:
            if "latency average" in line:
                try:
                    parts = line.split("=")
                    if len(parts) > 1:
                        pg_bench_latency = float(parts[1].strip().partition(" ")[0])
                        print(f"Parsed latency: {pg_bench_latency}")
                except ValueError as e:
                    print(f"Failed to parse latency value: {e}")
                    
            elif "tps" in line:
                try:
                    parts = line.split("=")
                    if len(parts) > 1:
                        pg_bench_tps = float(parts[1].strip().partition(" ")[0])
                        print(f"Parsed tps: {pg_bench_tps}")
                except ValueError as e:
                    print(f"Failed to parse TPS value: {e}")
                    
        return pg_bench_latency, pg_bench_tps
        
    except Exception as e:
        print(f"Error reading pgbench results: {e}")
        return None, None

def calculate_health(app_name):
    """Calculate health score with improved error handling and validation"""
    error_rate_query = f'rate(flask_http_request_total{{instance="{app_name}", status="500"}}[1m])'
    avg_latency_query = f'rate(flask_http_request_duration_seconds_sum{{instance="{app_name}"}}[1m]) / 'f'rate(flask_http_request_duration_seconds_count{{instance="{app_name}"}}[1m])'

    # Get metrics with fallback values
    error_rate = fetch_prometheus_metric(error_rate_query) or 0.0
    avg_latency = fetch_prometheus_metric(avg_latency_query) or 0.0
    
    # Track missing metrics
    missing_metrics = []
    if error_rate is None:
        missing_metrics.append("error_rate")
    if avg_latency is None:
        missing_metrics.append("avg_latency")

    pg_bench_latency, pg_bench_tps = get_pgbench_metrics()
    if pg_bench_latency is None:
        missing_metrics.append("pg_bench_latency")
        pg_bench_latency = 0.0
    if pg_bench_tps is None:
        missing_metrics.append("pg_bench_tps")
        pg_bench_tps = 0.0

    with weights_lock:
        w = weights['weights']
        t = weights['thresholds']

    error_penalty = w['error_weight'] * min(1, error_rate / t['error_rate'])
    latency_penalty = w['latency_weight'] * min(1, avg_latency / t['latency'])
    db_latency_penalty = w['db_latency_weight'] * min(1, pg_bench_latency / t['db_latency'])
    tps_bonus = min(1, pg_bench_tps) / 10

    if avg_latency > w['latency_threshold']:
        health_score = 0
    else:
        health_score = w['base_score'] - (error_penalty + latency_penalty + db_latency_penalty) + tps_bonus * w['tps_bonus_max']
        health_score = max(0, min(100, health_score))  # Ensure score is between 0 and 100

    # Validate metrics
    metrics_valid = validate_metrics({
        'error_rate': error_rate,
        'avg_latency': avg_latency,
        'pg_bench_latency': pg_bench_latency,
        'pg_bench_tps': pg_bench_tps
    })

    alerts = check_alert_conditions({
        'error_rate': error_rate,
        'avg_latency': avg_latency
    }, health_score)

    timestamp = datetime.utcnow().isoformat()
    health_history.add_score(app_name, health_score, timestamp)

    # Metrics for Kibana
    metrics = {
        "@timestamp": timestamp,
        "app_name": app_name,
        "health_score": health_score,
        "metrics": {
            "error_rate": error_rate,
            "avg_latency": avg_latency,
            "pg_bench_latency": pg_bench_latency,
            "pg_bench_tps": pg_bench_tps
        },
        "contributions": {
            "error_penalty": error_penalty,
            "latency_penalty": latency_penalty,
            "db_latency_penalty": db_latency_penalty,
            "tps_bonus": tps_bonus * w['tps_bonus_max']
        },
        "weights": {
            "error_weight": w['error_weight'],
            "latency_weight": w['latency_weight'],
            "db_latency_weight": w['db_latency_weight'],
            "tps_bonus_max": w['tps_bonus_max']
        },
        "status": {
            "missing_metrics": missing_metrics,
            "metrics_valid": metrics_valid,
            "alerts": alerts
        }
    }

    print(f"Metrics generated: {metrics}")
    return metrics

def send_metrics_to_kafka(metrics):
    """Send metrics to Kafka with improved error handling"""
    try:
        producer.send(TOPIC_NAME, metrics)
        producer.flush()
        print(f"Metrics sent to Kafka: {metrics}")
    except Exception as e:
        print(f"Failed to send metrics to Kafka: {e}")
        
@app.route('/health')
def health():
    """Get health metrics for all apps"""
    all_metrics = []
    for app_name in APP_NAMES:
        metrics = calculate_health(app_name)
        all_metrics.append(metrics)
    return jsonify(all_metrics)

@app.route('/health/history/<app_name>')
def health_history_endpoint(app_name):
    """Get historical health scores for an app"""
    history = health_history.get_trend(app_name)
    if history is None:
        return jsonify({"error": "No history found for app"}), 404
    return jsonify(history)

@app.route('/weights', methods=['GET'])
def get_weights():
    """Get current weights configuration"""
    with weights_lock:
        return jsonify(weights)

@app.route('/weights', methods=['POST'])
def update_weights():
    """Update weights with validation"""
    try:
        new_weights = request.get_json()
        
        required_fields = {
            'weights': ['base_score', 'error_weight', 'latency_weight', 
                       'db_latency_weight', 'latency_threshold', 'tps_bonus_max'],
            'thresholds': ['error_rate', 'latency', 'db_latency']
        }
        
        for section, fields in required_fields.items():
            if section not in new_weights:
                return jsonify({"status": "error", 
                              "message": f"Missing section: {section}"}), 400
            for field in fields:
                if field not in new_weights[section]:
                    return jsonify({"status": "error", 
                                  "message": f"Missing field: {field} in {section}"}), 400
                if not isinstance(new_weights[section][field], (int, float)) or new_weights[section][field] < 0:
                    return jsonify({"status": "error", 
                                  "message": f"Invalid value for {field} in {section}"}), 400
        
        with weights_lock:
            global weights
            weights = new_weights
        save_weights()
        return jsonify({"status": "success", "message": "Weights updated successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

def periodic_task():
    while True:
        time.sleep(10)
        for app_name in APP_NAMES:
            try:
                metrics = calculate_health(app_name)
                send_metrics_to_kafka(metrics)
            except Exception as e:
                print(f"Error in periodic task for {app_name}: {e}")

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == "__main__":
    # Load initial weights
    load_weights()
    
    thread = Thread(target=periodic_task)
    thread.daemon = True
    thread.start()

    app.run(host='0.0.0.0', port=5002)
