# codegen — генератор кода для Python-микросервисов

`codegen` читает декларативный `service.yaml` и генерирует: gRPC-серверы и клиенты, async-пул к БД, S3-клиент.

---

## Установка

```bash
pip install -e utils/codegen
```

CLI: `codegen init | validate | generate [--watch]`

---

## Быстрый старт

```bash
# 1. Инициализировать новый сервис в текущей директории
codegen init my-service

# 2. Перейти в директорию и сгенерировать код
cd my-service
codegen generate

# 3. Проверить service.yaml
codegen validate
```

После генерации код лежит в `generated/`.

---

## service.yaml

Корень документа — объект `service`. Каждый вложенный блок включается флагом `enabled` и генерирует отдельный набор файлов.

```yaml
service:
  name: my-service
  version: 0.1.0
  description: ""

  # Python runtime
  python:
    major: 3
    minor: 12

  # gRPC-сервер
  grpc:
    enabled: false

  # gRPC-клиент
  grpc_client:
    enabled: false
    services: []

  # # Kafka
  # kafka_producer:
  #   enabled: false
  #   topics: []

  # kafka_consumer:
  #   enabled: false
  #   topics: []
  #   group_id: null

  # База данных
  postgres:
    enabled: false
    schemas: ["public"]
    tables: []          # список таблиц для генерации CREATE TABLE
    pool_size: 10

  # S3 / MinIO
  minio:
    enabled: false
    buckets: []

  # # Secrets
  # vault:
  #   enabled: true
  #   mount_point: "secret"

  # # Межсервисная авторизация
  # auth:
  #   enabled: true

  # # Feature flags
  # config_client:
  #   enabled: false
  #   flags: []

  # # Трейсы, логи, метрики
  # observability:
  #   enabled: true
  #   log_level: INFO
  #   trace_sampling_rate: 1.0
  #   metrics_enabled: true
  #   metrics_path: /metrics
  #   metrics_port: 9090
```

---
