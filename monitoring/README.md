# 📊 Система мониторинга Lectify

Полноценный стек мониторинга с логами, метриками, алертами и дашбордами.

## 🚀 Быстрый старт

### 1. Запуск стека мониторинга

```bash
# Из корневой директории проекта
docker-compose up -d
```

### 2. Запуск приложения Lectify

```bash
# Установите зависимости (если ещё не установлены)
pip install -r requirements.txt

# Запустите приложение
python main.py
```

### 3. Доступ к сервисам

- **Grafana**: http://localhost:3000 (admin/admin)
- **Prometheus**: http://localhost:9090
- **Alertmanager**: http://localhost:9093
- **Loki**: http://localhost:3100
- **Приложение**: http://localhost:5001
- **Метрики приложения**: http://localhost:5001/metrics

## 📦 Компоненты

### Grafana
- **Порт**: 3000
- **Назначение**: Визуализация метрик и логов
- **Дашборды**: Автоматически загружаются из `monitoring/grafana/dashboards/`
- **Datasources**: Prometheus и Loki настроены автоматически

### Prometheus
- **Порт**: 9090
- **Назначение**: Сбор и хранение метрик
- **Конфигурация**: `monitoring/prometheus/prometheus.yml`
- **Алерты**: `monitoring/prometheus/alerts.yml`
- **Scrape интервал**: 15 секунд

### Loki
- **Порт**: 3100
- **Назначение**: Агрегация и хранение логов
- **Конфигурация**: `monitoring/loki/loki-config.yml`
- **Retention**: 30 дней

### Promtail
- **Назначение**: Отправка логов в Loki
- **Конфигурация**: `monitoring/promtail/promtail-config.yml`
- **Источники логов**:
  - `logs/lectify.log` - логи приложения
  - `/var/log/syslog` - системные логи

### Alertmanager
- **Порт**: 9093
- **Назначение**: Управление и маршрутизация алертов
- **Конфигурация**: `monitoring/alertmanager/alertmanager.yml`
- **Webhook**: Отправляет алерты на `/api/alerts/webhook`

### Node Exporter
- **Порт**: 9100
- **Назначение**: Системные метрики (CPU, память, диск)

## 📈 Метрики приложения

### Воркфлоу
- `lectify_workflows_total` - Общее количество воркфлоу
- `lectify_workflows_completed_total` - Завершённые воркфлоу
- `lectify_workflows_failed_total` - Неудачные воркфлоу
- `lectify_workflow_queue_size` - Размер очереди
- `lectify_workflow_active_count` - Активные воркфлоу
- `lectify_workflow_duration_seconds` - Длительность выполнения

### Ноды
- `lectify_node_execution_seconds` - Длительность выполнения ноды
- `lectify_node_failures_total` - Ошибки выполнения нод

### LLM API
- `lectify_llm_api_requests_total` - Запросы к LLM API
- `lectify_llm_api_duration_seconds` - Длительность запросов
- `lectify_llm_api_errors_total` - Ошибки API

### Файлы
- `lectify_files_uploaded_total` - Загруженные файлы
- `lectify_file_size_bytes` - Размер файлов

### База данных
- `lectify_db_operations_total` - Операции с БД
- `lectify_db_operation_duration_seconds` - Длительность операций

## 🚨 Алерты

### Критические
- **LectifyDown**: Приложение недоступно > 1 минуты
- **DiskSpaceLow**: Свободного места < 15%

### Предупреждения
- **HighCPUUsage**: CPU > 80% в течение 5 минут
- **HighMemoryUsage**: Память > 85% в течение 5 минут
- **HighErrorRate**: > 10 ошибок/сек в течение 2 минут
- **WorkflowQueueOverflow**: Очередь > 20 воркфлоу
- **HighWorkflowFailureRate**: > 20% неудачных воркфлоу
- **LLMAPIErrors**: > 5 ошибок API/сек

### Информационные
- **SlowWorkflowExecution**: Воркфлоу выполняется > 1 часа

## 📝 Логирование

### Формат логов
Все логи в JSON формате со следующими полями:
```json
{
  "timestamp": "2024-01-15T10:30:45.123456Z",
  "level": "info",
  "logger": "src.workflows.orchestrator",
  "event": "workflow_started",
  "workflow_id": "uuid-here",
  "file_id": "uuid-here",
  "active_count": 2,
  "max_concurrent": 3
}
```

### Уровни логирования
- **DEBUG**: Детальная отладочная информация
- **INFO**: Общая информация о работе
- **WARNING**: Предупреждения и алерты
- **ERROR**: Ошибки выполнения
- **CRITICAL**: Критические ошибки

### Просмотр логов

#### В Grafana
1. Откройте Grafana (http://localhost:3000)
2. Перейдите в Explore
3. Выберите datasource "Loki"
4. Используйте запросы:
   - `{job="lectify"}` - все логи приложения
   - `{job="lectify", level="error"}` - только ошибки
   - `{job="lectify"} |= "workflow_id"` - логи с workflow_id

#### В командной строке
```bash
# Просмотр логов приложения
tail -f logs/lectify.log

# Просмотр логов с форматированием
tail -f logs/lectify.log | jq '.'
```

## 🎨 Дашборды

### Lectify Overview
Главный дашборд с ключевыми метриками:
- Общая статистика воркфлоу
- Активные и в очереди
- Частота завершения и ошибок
- Длительность выполнения
- Загрузка CPU и памяти
- Логи в реальном времени

## ⚙️ Настройка

### Изменение retention логов
Отредактируйте `monitoring/loki/loki-config.yml`:
```yaml
table_manager:
  retention_period: 720h  # 30 дней (измените на нужное значение)
```

### Настройка email уведомлений
Отредактируйте `monitoring/alertmanager/alertmanager.yml`:
```yaml
global:
  smtp_smarthost: 'smtp.gmail.com:587'
  smtp_from: 'alerts@lectify.com'
  smtp_auth_username: 'your-email@gmail.com'
  smtp_auth_password: 'your-app-password'

receivers:
  - name: 'critical-alerts'
    email_configs:
      - to: 'admin@lectify.com'
```

### Изменение лимита параллельных воркфлоу
В `src/workflows/orchestrator.py`:
```python
self.max_concurrent_workflows = 3  # Измените на нужное значение
```

## 🔧 Управление

### Остановка мониторинга
```bash
docker-compose down
```

### Остановка с удалением данных
```bash
docker-compose down -v
```

### Перезапуск отдельного сервиса
```bash
docker-compose restart grafana
```

### Просмотр логов сервисов
```bash
docker-compose logs -f grafana
docker-compose logs -f prometheus
docker-compose logs -f loki
```

## 📊 Примеры запросов

### Prometheus (PromQL)
```promql
# Средняя длительность воркфлоу за последний час
rate(lectify_workflow_duration_seconds_sum[1h]) / rate(lectify_workflow_duration_seconds_count[1h])

# Процент неудачных воркфлоу
(rate(lectify_workflows_failed_total[5m]) / rate(lectify_workflows_total[5m])) * 100

# Топ-5 самых медленных нод
topk(5, rate(lectify_node_execution_seconds_sum[1h]) / rate(lectify_node_execution_seconds_count[1h]))
```

### Loki (LogQL)
```logql
# Все ошибки за последний час
{job="lectify", level="error"}

# Воркфлоу по конкретному file_id
{job="lectify"} |= "file_id" | json | file_id="your-file-id"

# Количество ошибок в минуту
rate({job="lectify", level="error"}[1m])
```

## 🐛 Troubleshooting

### Grafana не показывает данные
1. Проверьте, что Prometheus и Loki запущены: `docker-compose ps`
2. Проверьте datasources в Grafana: Settings → Data Sources
3. Убедитесь, что приложение отправляет метрики: `curl http://localhost:5001/metrics`

### Логи не появляются в Loki
1. Проверьте, что файл логов создаётся: `ls -la logs/lectify.log`
2. Проверьте Promtail: `docker-compose logs promtail`
3. Убедитесь, что путь в `promtail-config.yml` правильный

### Алерты не срабатывают
1. Проверьте правила в Prometheus: http://localhost:9090/alerts
2. Проверьте Alertmanager: http://localhost:9093
3. Проверьте логи Alertmanager: `docker-compose logs alertmanager`

## 📚 Дополнительные ресурсы

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [Loki Documentation](https://grafana.com/docs/loki/)
- [Alertmanager Documentation](https://prometheus.io/docs/alerting/latest/alertmanager/)
