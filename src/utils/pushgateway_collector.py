"""
Pushgateway metrics collector for orchestrator

Collects LLM metrics from Pushgateway after plugin execution
and re-records them in the main application's metrics.
"""

import requests
from typing import Dict, List
from src.utils.logging import get_logger

logger = get_logger(__name__)


def parse_prometheus_text(text: str) -> Dict[str, List[Dict]]:
    """
    Parse Prometheus text format into structured data.
    
    Returns: {metric_name: [{'labels': {...}, 'value': float}, ...]}
    """
    metrics = {}
    for line in text.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        # Parse metric line: metric_name{label1="value1",label2="value2"} value
        try:
            if '{' in line:
                metric_part, value_part = line.rsplit(' ', 1)
                metric_name, labels_str = metric_part.split('{', 1)
                labels_str = labels_str.rstrip('}')
                
                # Parse labels
                labels = {}
                for label_pair in labels_str.split(','):
                    if '=' in label_pair:
                        key, val = label_pair.split('=', 1)
                        labels[key.strip()] = val.strip('"')
                
                if metric_name not in metrics:
                    metrics[metric_name] = []
                
                metrics[metric_name].append({
                    'labels': labels,
                    'value': float(value_part)
                })
        except Exception as e:
            logger.warning("failed_to_parse_prometheus_line", line=line, error=str(e))
            continue
    
    return metrics


def collect_plugin_metrics(
    plugin_id: str,
    execution_id: str,
    pushgateway_url: str = "localhost:9091"
) -> Dict[str, List[Dict]]:
    """
    Fetch metrics for a specific plugin execution from Pushgateway.
    
    Returns parsed metrics dict.
    """
    try:
        # Pushgateway groups metrics by job and grouping keys
        url = f"http://{pushgateway_url}/metrics"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        
        all_metrics = parse_prometheus_text(response.text)
        
        # Filter metrics for this plugin/execution
        filtered = {}
        for metric_name, entries in all_metrics.items():
            filtered_entries = [
                e for e in entries
                if e['labels'].get('plugin_id') == plugin_id
                and e['labels'].get('execution_id') == execution_id
            ]
            if filtered_entries:
                filtered[metric_name] = filtered_entries
        
        return filtered
        
    except Exception as e:
        logger.warning(
            "failed_to_collect_pushgateway_metrics",
            plugin_id=plugin_id,
            execution_id=execution_id,
            error=str(e)
        )
        return {}


def replay_llm_metrics(
    plugin_id: str,
    execution_id: str,
    pushgateway_url: str = "localhost:9091"
):
    """
    Fetch LLM metrics from Pushgateway and replay them into main app metrics.
    
    Called by orchestrator after plugin execution completes.
    """
    from src.utils.metrics import metrics
    
    plugin_metrics = collect_plugin_metrics(plugin_id, execution_id, pushgateway_url)
    
    if not plugin_metrics:
        return
    
    # Replay LLM request counters
    for entry in plugin_metrics.get('lectify_llm_api_requests_total', []):
        purpose = entry['labels'].get('purpose', 'unknown')
        status = entry['labels'].get('status', 'unknown')
        count = int(entry['value'])
        
        # Increment main app counter by the same amount
        metrics.llm_api_requests.labels(purpose=purpose, status=status).inc(count)
        logger.info(
            "replayed_llm_request_metric",
            plugin_id=plugin_id,
            purpose=purpose,
            status=status,
            count=count
        )
    
    # Replay LLM duration histograms
    for entry in plugin_metrics.get('lectify_llm_api_duration_seconds', []):
        purpose = entry['labels'].get('purpose', 'unknown')
        duration = entry['value']
        
        # Observe in main app histogram
        metrics.llm_api_duration.labels(purpose=purpose).observe(duration)
        logger.info(
            "replayed_llm_duration_metric",
            plugin_id=plugin_id,
            purpose=purpose,
            duration=duration
        )
    
    # Replay LLM error counters
    for entry in plugin_metrics.get('lectify_llm_api_errors_total', []):
        purpose = entry['labels'].get('purpose', 'unknown')
        error_type = entry['labels'].get('error_type', 'unknown')
        count = int(entry['value'])
        
        metrics.llm_api_errors.labels(purpose=purpose, error_type=error_type).inc(count)
        logger.info(
            "replayed_llm_error_metric",
            plugin_id=plugin_id,
            purpose=purpose,
            error_type=error_type,
            count=count
        )
