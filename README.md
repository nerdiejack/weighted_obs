## Configuration

### health_weights.yml Example

thresholds:
db_latency: 0.5
error_rate: 4
latency: 2
weights:
base_score: 100
db_latency_weight: 10
error_weight: 15
latency_threshold: 5
latency_weight: 25
tps_bonus_max: 10
