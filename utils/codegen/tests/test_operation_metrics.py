import os
from pathlib import Path
import subprocess
import sys
from templates import env


def test_generated_metrics_record_outcomes_bytes_and_plugin_reports(tmp_path: Path):
    (tmp_path/'operations.py').write_text(env.get_template('services/observability/operations.py.j2').render())
    script = '''
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
reader = InMemoryMetricReader()
provider = MeterProvider(metric_readers=[reader])
metrics.set_meter_provider(provider)
from operations import operation, transfer, report
with operation('plugin','example'):
    transfer('plugin','example','input',123)
try:
    with operation('plugin','example'): raise ValueError('private detail')
except ValueError: pass
report('example',{'progress':50},{'records':3})
data = {metric.name:metric.data.data_points for resource in reader.get_metrics_data().resource_metrics
        for scope in resource.scope_metrics for metric in scope.metrics}
assert sum(point.value for point in data['application.operation.active']) == 0
assert {point.attributes['outcome']:point.value for point in data['application.operation.completed']} == {'completed':1,'failed':1}
assert sum(point.value for point in data['application.operation.bytes']) == 123
assert data['application.reported.gauge'][0].value == 50
assert data['application.reported.counter'][0].value == 3
assert all('execution_id' not in point.attributes and 'user_id' not in point.attributes
           for points in data.values() for point in points)
provider.shutdown()
'''
    result = subprocess.run([sys.executable,'-c',script],cwd=tmp_path,
        env=dict(os.environ,PYTHONPATH=str(tmp_path)),text=True,capture_output=True,timeout=15)
    assert result.returncode == 0,result.stdout+result.stderr
