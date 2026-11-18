"""Prometheus metrics, exposed at /metrics (optionally protected by METRICS_TOKEN).

Any monitoring tool (Grafana Cloud's free tier, for example) can scrape these
and graph latency, live games and connected players over time.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

HTTP_LATENCY = Histogram(
    "shahmaat_http_request_seconds",
    "HTTP request latency",
    ["method", "route", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
WS_CONNECTIONS = Gauge("shahmaat_ws_connections", "Open WebSocket connections on this instance")
MOVES = Counter("shahmaat_moves_total", "Moves accepted by the referee")
MOVE_LATENCY = Histogram(
    "shahmaat_move_seconds",
    "Time to validate, save and broadcast one move",
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25),
)
GAMES_STARTED = Counter("shahmaat_games_started_total", "Games started", ["time_class", "source"])
GAMES_FINISHED = Counter("shahmaat_games_finished_total", "Games finished", ["termination"])
CAS_CONFLICTS = Counter("shahmaat_cas_conflicts_total", "Optimistic-lock retries on live games")
QUEUE_WAIT = Histogram(
    "shahmaat_matchmaking_wait_seconds",
    "Time from joining the queue to being paired",
    buckets=(1, 2, 5, 10, 20, 40, 80),
)
