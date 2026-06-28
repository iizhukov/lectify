import requests
from typing import Dict, List
from src.utils.logging import get_logger

logger = get_logger(__name__)


def parse_prometheus_text(text: str) -> Dict[str, List[Dict]]:
    metrics = {}
    for line in text.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        try:
            if '{' in line:
                metric_part, value_part = line.rsplit(' ', 1)
                metric_name, labels_str = metric_part.split('{', 1)
                labels_str = labels_str.rstrip('}')
                
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
    try:
        url = f"http://{pushgateway_url}/metrics"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        
        all_metrics = parse_prometheus_text(response.text)
        
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
    from src.utils.metrics import metrics
    
    plugin_metrics = collect_plugin_metrics(plugin_id, execution_id, pushgateway_url)
    
    if not plugin_metrics:
        return
    
    for entry in plugin_metrics.get('lectify_llm_api_requests_total', []):
        purpose = entry['labels'].get('purpose', 'unknown')
        status = entry['labels'].get('status', 'unknown')
        count = int(entry['value'])
        
        metrics.llm_api_requests.labels(purpose=purpose, status=status).inc(count)
        logger.info(
            "replayed_llm_request_metric",
            plugin_id=plugin_id,
            purpose=purpose,
            status=status,
            count=count
        )
    
    for entry in plugin_metrics.get('lectify_llm_api_duration_seconds', []):
        purpose = entry['labels'].get('purpose', 'unknown')
        duration = entry['value']
        
        metrics.llm_api_duration.labels(purpose=purpose).observe(duration)
        logger.info(
            "replayed_llm_duration_metric",
            plugin_id=plugin_id,
            purpose=purpose,
            duration=duration
        )
    
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
