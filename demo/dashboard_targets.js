window.DASHBOARD_TARGETS = {
  "service": {
    "label": "Service Health",
    "dashboardUid": "service-health-01",
    "controllerUrl": "http://localhost:8010",
    "probeUrl": "http://localhost:8000",
    "renderProbeUrl": "http://localhost:8012",
    "grafanaSource": "Service Health",
    "grafanaSre": "[SRE] Service Health",
    "faultGroups": [
      {
        "key": "mock",
        "label": "Mock faults",
        "kind": "mock",
        "enabled": true,
        "description": "Synthetic mock Prometheus responses for the Service Health dashboard.",
        "disabledReason": null,
        "faults": [
          {
            "type": "no_data",
            "label": "No Data",
            "target": "http_requests_total",
            "affected_layers": [
              "datasource_api",
              "grafana_panel_path",
              "browser_render"
            ],
            "expected_sre_signals": [
              "no_data",
              "render_no_data"
            ]
          },
          {
            "type": "stale_data",
            "label": "Stale Data",
            "target": "http_requests_total",
            "affected_layers": [
              "stale_data"
            ],
            "expected_sre_signals": [
              "stale_data"
            ]
          },
          {
            "type": "slow_query",
            "label": "Slow Query",
            "target": "http_requests_total",
            "affected_layers": [
              "datasource_api",
              "grafana_panel_path",
              "browser_render"
            ],
            "expected_sre_signals": [
              "slow_query",
              "query_timeout",
              "render_timeout"
            ]
          },
          {
            "type": "var_resolution_fail",
            "label": "Var Fail",
            "target": "instance",
            "affected_layers": [
              "variable_resolution",
              "variable_dependency",
              "browser_render"
            ],
            "expected_sre_signals": [
              "var_resolution_fail",
              "blocked_by_variable",
              "render_no_data"
            ]
          },
          {
            "type": "variable_query_error",
            "label": "Var Query Error",
            "target": "instance",
            "affected_layers": [
              "variable_resolution",
              "variable_dependency",
              "browser_render"
            ],
            "expected_sre_signals": [
              "variable_query_error",
              "blocked_by_variable",
              "render_panel_error"
            ]
          },
          {
            "type": "metric_rename",
            "label": "Metric Rename",
            "target": "process_resident_memory_bytes",
            "affected_layers": [
              "datasource_api",
              "grafana_panel_path",
              "browser_render"
            ],
            "expected_sre_signals": [
              "no_data",
              "metric_rename",
              "render_no_data"
            ]
          },
          {
            "type": "cardinality_spike",
            "label": "Cardinality Spike",
            "target": "http_requests_total",
            "affected_layers": [
              "cardinality_spike"
            ],
            "expected_sre_signals": [
              "cardinality_spike"
            ]
          }
        ]
      }
    ],
    "surfaces": {
      "http_requests_total": "Grafana panels: Request Rate, Error Rate %",
      "process_resident_memory_bytes": "Grafana panel: Memory Usage",
      "up": "Grafana panel: Active Instances",
      "kube_pod_status_ready": "Grafana panel: Pod Readiness",
      "instance": "Grafana variable $pod",
      "namespace": "Grafana variable $namespace"
    }
  },
  "mongodb": {
    "label": "MongoDB Operations",
    "dashboardUid": "mongodb-ops-01",
    "controllerUrl": "http://localhost:8010",
    "probeUrl": "http://localhost:8002",
    "renderProbeUrl": "http://localhost:8012",
    "grafanaSource": "MongoDB Operations",
    "grafanaSre": "[SRE] MongoDB Operations",
    "faultGroups": [
      {
        "key": "mock",
        "label": "Mock faults",
        "kind": "mock",
        "enabled": true,
        "description": "Synthetic mock Prometheus responses for the MongoDB Operations dashboard.",
        "disabledReason": null,
        "faults": [
          {
            "type": "no_data",
            "label": "No Data",
            "target": "mongodb_op_counters_total",
            "affected_layers": [
              "datasource_api",
              "grafana_panel_path",
              "browser_render"
            ],
            "expected_sre_signals": [
              "no_data",
              "render_no_data"
            ]
          },
          {
            "type": "stale_data",
            "label": "Stale Data",
            "target": "mongodb_op_counters_total",
            "affected_layers": [
              "stale_data"
            ],
            "expected_sre_signals": [
              "stale_data"
            ]
          },
          {
            "type": "slow_query",
            "label": "Slow Query",
            "target": "mongodb_op_counters_total",
            "affected_layers": [
              "datasource_api",
              "grafana_panel_path",
              "browser_render"
            ],
            "expected_sre_signals": [
              "slow_query",
              "query_timeout",
              "render_timeout"
            ]
          },
          {
            "type": "var_resolution_fail",
            "label": "Var Fail",
            "target": "instance",
            "affected_layers": [
              "variable_resolution",
              "variable_dependency",
              "browser_render"
            ],
            "expected_sre_signals": [
              "var_resolution_fail",
              "blocked_by_variable",
              "render_no_data"
            ]
          },
          {
            "type": "variable_query_error",
            "label": "Var Query Error",
            "target": "instance",
            "affected_layers": [
              "variable_resolution",
              "variable_dependency",
              "browser_render"
            ],
            "expected_sre_signals": [
              "variable_query_error",
              "blocked_by_variable",
              "render_panel_error"
            ]
          },
          {
            "type": "metric_rename",
            "label": "Metric Rename",
            "target": "mongodb_memory_resident_bytes",
            "affected_layers": [
              "datasource_api",
              "grafana_panel_path",
              "browser_render"
            ],
            "expected_sre_signals": [
              "no_data",
              "metric_rename",
              "render_no_data"
            ]
          },
          {
            "type": "cardinality_spike",
            "label": "Cardinality Spike",
            "target": "mongodb_op_counters_total",
            "affected_layers": [
              "cardinality_spike"
            ],
            "expected_sre_signals": [
              "cardinality_spike"
            ]
          }
        ]
      }
    ],
    "surfaces": {
      "mongodb_up": "Grafana panel: MongoDB Up",
      "mongodb_op_counters_total": "Grafana panel: Operation Rate",
      "mongodb_connections": "Grafana panel: Current Connections",
      "mongodb_memory_resident_bytes": "Grafana panel: Resident Memory",
      "mongodb_mongod_replset_member_replication_lag": "Grafana panel: Replication Lag",
      "mongodb_mongod_replset_member_health": "Grafana panel: Replica Member Health",
      "instance": "Grafana variable $instance",
      "replset": "Grafana variable $replset"
    }
  },
  "mongodb_atlas": {
    "label": "MongoDB Atlas System Metrics",
    "dashboardUid": "mongodb-atlas-system-metrics",
    "controllerUrl": "http://localhost:8010",
    "probeUrl": "http://localhost:8004",
    "renderProbeUrl": "http://localhost:8012",
    "grafanaSource": "MongoDB Atlas System Metrics",
    "grafanaSre": "[SRE] MongoDB Atlas System Metrics",
    "faultGroups": [
      {
        "key": "mock",
        "label": "Mock faults",
        "kind": "mock",
        "enabled": true,
        "description": "Synthetic mock Prometheus responses for the official MongoDB Atlas dashboard.",
        "disabledReason": null,
        "faults": [
          {
            "type": "no_data",
            "label": "No Data",
            "target": "mongodb_opcounters_query",
            "affected_layers": [
              "datasource_api",
              "grafana_panel_path",
              "browser_render"
            ],
            "expected_sre_signals": [
              "no_data",
              "render_no_data"
            ]
          },
          {
            "type": "stale_data",
            "label": "Stale Data",
            "target": "mongodb_opcounters_query",
            "affected_layers": [
              "stale_data"
            ],
            "expected_sre_signals": [
              "stale_data"
            ]
          },
          {
            "type": "slow_query",
            "label": "Slow Query",
            "target": "mongodb_opcounters_query",
            "affected_layers": [
              "datasource_api",
              "grafana_panel_path",
              "browser_render"
            ],
            "expected_sre_signals": [
              "slow_query",
              "query_timeout",
              "render_timeout"
            ]
          },
          {
            "type": "var_resolution_fail",
            "label": "Var Fail",
            "target": "group_id",
            "affected_layers": [
              "variable_resolution",
              "variable_dependency",
              "browser_render"
            ],
            "expected_sre_signals": [
              "var_resolution_fail",
              "blocked_by_variable",
              "render_no_data"
            ]
          },
          {
            "type": "variable_query_error",
            "label": "Var Query Error",
            "target": "group_id",
            "affected_layers": [
              "variable_resolution",
              "variable_dependency",
              "browser_render"
            ],
            "expected_sre_signals": [
              "variable_query_error",
              "blocked_by_variable",
              "render_panel_error"
            ]
          },
          {
            "type": "metric_rename",
            "label": "Metric Rename",
            "target": "mongodb_mem_virtual",
            "affected_layers": [
              "datasource_api",
              "grafana_panel_path",
              "browser_render"
            ],
            "expected_sre_signals": [
              "no_data",
              "metric_rename",
              "render_no_data"
            ]
          },
          {
            "type": "cardinality_spike",
            "label": "Cardinality Spike",
            "target": "mongodb_opcounters_query",
            "affected_layers": [
              "cardinality_spike"
            ],
            "expected_sre_signals": [
              "cardinality_spike"
            ]
          }
        ]
      }
    ],
    "surfaces": {
      "mongodb_up": "Grafana panels: Group Metadata, Cluster host list",
      "mongodb_opcounters_query": "Grafana panel: Opcounter - Query",
      "mongodb_mem_resident": "Grafana panel: Memory - Resident",
      "mongodb_mem_virtual": "Grafana panel: Memory - Virtual",
      "mongodb_network_numRequests": "Grafana panel: Network - Requests",
      "mongodb_wiredTiger_cache_bytes_currently_in_the_cache": "Grafana panel: WT Cache - Bytes Currently in Cache",
      "group_id": "Grafana variable $group_id",
      "cl_name": "Grafana variable $cl_name",
      "rs_nm": "Grafana variable $rs_nm",
      "host": "Grafana variable $host",
      "process_port": "Grafana variable $process_port"
    }
  },
  "mongodb_live": {
    "label": "MongoDB Live Operations",
    "dashboardUid": "mongodb-live-ops-01",
    "controllerUrl": "http://localhost:8010",
    "probeUrl": "http://localhost:8006",
    "renderProbeUrl": "http://localhost:8012",
    "grafanaSource": "MongoDB Live Operations",
    "grafanaSre": "[SRE] MongoDB Live Operations",
    "faultGroups": [
      {
        "key": "proxy",
        "label": "API proxy faults",
        "kind": "proxy",
        "enabled": true,
        "description": "Faults injected between the real Prometheus API and Grafana/probe-engine.",
        "disabledReason": null,
        "faults": [
          {
            "type": "no_data",
            "label": "No Data",
            "target": "mongodb_op_counters_total",
            "affected_layers": [
              "datasource_api",
              "grafana_panel_path",
              "browser_render"
            ],
            "expected_sre_signals": [
              "no_data",
              "render_no_data"
            ]
          },
          {
            "type": "stale_data",
            "label": "Stale Data",
            "target": "mongodb_op_counters_total",
            "affected_layers": [
              "stale_data"
            ],
            "expected_sre_signals": [
              "stale_data"
            ]
          },
          {
            "type": "slow_query",
            "label": "Slow Query",
            "target": "mongodb_op_counters_total",
            "affected_layers": [
              "datasource_api",
              "grafana_panel_path",
              "browser_render"
            ],
            "expected_sre_signals": [
              "slow_query",
              "query_timeout",
              "render_timeout"
            ]
          },
          {
            "type": "var_resolution_fail",
            "label": "Var Fail",
            "target": "instance",
            "affected_layers": [
              "variable_resolution",
              "variable_dependency",
              "browser_render"
            ],
            "expected_sre_signals": [
              "var_resolution_fail",
              "blocked_by_variable",
              "render_no_data"
            ]
          },
          {
            "type": "variable_query_error",
            "label": "Var Query Error",
            "target": "instance",
            "affected_layers": [
              "variable_resolution",
              "variable_dependency",
              "browser_render"
            ],
            "expected_sre_signals": [
              "variable_query_error",
              "blocked_by_variable",
              "render_panel_error"
            ]
          },
          {
            "type": "metric_rename",
            "label": "Metric Rename",
            "target": "mongodb_memory",
            "affected_layers": [
              "datasource_api",
              "grafana_panel_path",
              "browser_render"
            ],
            "expected_sre_signals": [
              "no_data",
              "metric_rename",
              "render_no_data"
            ]
          },
          {
            "type": "cardinality_spike",
            "label": "Cardinality Spike",
            "target": "mongodb_op_counters_total",
            "affected_layers": [
              "cardinality_spike"
            ],
            "expected_sre_signals": [
              "cardinality_spike"
            ]
          },
          {
            "type": "panel_query_http_500",
            "label": "Grafana Panel 500",
            "target": "mongodb_op_counters_total",
            "affected_layers": [
              "grafana_panel_path",
              "browser_render"
            ],
            "expected_sre_signals": [
              "panel_error",
              "render_panel_error"
            ]
          }
        ]
      },
      {
        "key": "infra",
        "label": "Infrastructure faults",
        "kind": "infra",
        "enabled": false,
        "description": "Whitelisted Docker infrastructure actions planned for the next slice.",
        "disabledReason": "Infra actions are modeled only in this MVP; no Docker-mutating controls are exposed yet.",
        "faults": [
          {
            "type": "stop_exporter",
            "label": "Stop Exporter",
            "target": "mongodb-exporter",
            "affected_layers": [],
            "expected_sre_signals": []
          },
          {
            "type": "restart_exporter",
            "label": "Restart Exporter",
            "target": "mongodb-exporter",
            "affected_layers": [],
            "expected_sre_signals": []
          },
          {
            "type": "workload_spike",
            "label": "Workload Spike",
            "target": "mongo-workload",
            "affected_layers": [],
            "expected_sre_signals": []
          }
        ]
      }
    ],
    "surfaces": {
      "mongodb_up": "Grafana panel: MongoDB Up",
      "mongodb_op_counters_total": "Grafana panel: Operation Rate",
      "mongodb_ss_connections": "Grafana panel: Current Connections",
      "mongodb_memory": "Grafana panel: Resident Memory",
      "mongodb_mongod_op_latencies_latency_total": "Grafana panel: Read Latency",
      "mongodb_extra_info_page_faults_total": "Grafana panel: Page Faults",
      "instance": "Grafana variable $instance",
      "mongodb-exporter": "Docker service: mongodb-exporter",
      "mongo-workload": "Docker service: mongo-workload"
    }
  }
};
