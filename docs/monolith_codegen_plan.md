# Архитектурный план: Monolith / Local Bundle Generator

## Цель
Создать режим кодогенерации `codegen monolith` (или `codegen local`), позволяющий собирать все активные микросервисы Lectify в единый легковесный монолитный проект в изолированной директории `monolith/` в корне репозитория для быстрого локального запуска, разработки и отладки всего стека.

---

## Архитектура монолита

```
lectify/
├── services/               # Исходные микросервисы (read-only, не изменяются)
├── utils/codegen/          # Движок кодогенерации
│   └── src/generators/monolith/   # Модули генератора монолита
└── monolith/               # Генерируемая изолированная папка монолита
    ├── main.py             # Единый entrypoint запуска всех сервисов
    ├── inprocess_grpc.py   # In-process роутер gRPC (вызовы в памяти)
    ├── settings.py         # Единая конфигурация и .env
    ├── docker-compose.yml  # Единая инфраструктура (Postgres, Kafka, MinIO, Vault)
    ├── requirements.txt    # Объединенные зависимости
    ├── Makefile            # make infra-up, make run, make test
    └── infra/              # Скрипты инициализации БД, топиков, бакетов и Vault
```

---

## 1. In-Process gRPC роутинг (вызов реализации без сети)

В обычном микросервисном режиме сервисы обращаются друг к другу по сети (`grpc.aio.insecure_channel("localhost:50051")`).
В монолитном режиме межсервисные вызовы идут **напрямую в Python-объект Servicer** в памяти текущего процесса:

```
[Service A (client)] ──> InProcessStub ──> [Direct call: ServicerB.Method(request, ctx)] ──> [Service B]
```

### Принцип работы:
1. Для каждого сервиса создается `InProcessStub`, повторяющий интерфейс gRPC Stub:
   ```python
   class InProcessExampleServerStub:
       def __init__(self, servicer: ExampleServiceImpl):
           self._servicer = servicer

       async def Ping(self, request, metadata=None, timeout=None):
           context = MockServicerContext(metadata=metadata)
           return await self._servicer.Ping(request, context)
   ```
2. **Преимущества**:
   - **Нулевой сетевой оверхед** и отсутствие сериализации/десериализации в сокеты.
   - **Отсутствие конфликтов портов** (не нужно выделять 15 разных портов для локального запуска).
   - Единый стек-трейс при ошибках и исключениях между сервисами (удобно отлаживать в IDE с точками останова).
3. **Внешний доступ**:
   - Monolith дополнительно запускает **один общий gRPC сервер на одном порту** (например, `50051`), куда регистрирует все сервисеры сразу, чтобы фронтенд или внешние клиенты могли обращаться ко всем API через один порт.

---

## 2. Единый `monolith/main.py` и жизненный цикл

Единый entrypoint монолита управляет всеми компонентами:

```python
async def main():
    log.info("Starting Lectify Monolith...")

    # 1. Инициализация всех баз данных и подключений
    await init_databases()

    # 2. Инстанцирование сервисеров
    config_servicer = ConfigServiceImpl()
    tas_servicer = TicketServiceImpl()
    example_servicer = ExampleServiceImpl()

    # 3. Регистрация сервисеров в глобальном in-process роутере
    registry = InProcessRegistry()
    registry.register("infra_config", config_servicer)
    registry.register("infra_tas", tas_servicer)
    registry.register("example_server", example_servicer)

    # 4. Запуск фоновых задач и потребителей
    tasks = [
        run_unified_grpc_server(registry, port=50051),  # Внешний gRPC сервер
        run_unified_kafka_consumers(),                  # Консьюмеры всех сервисов
        run_unified_scheduler(),                        # Единый фоновый планировщик
        run_metrics_server(port=9090),                  # Метрики Prometheus
    ]

    await asyncio.gather(*tasks)
```

---

## 3. Оптимизация под локальный запуск (Lightweight)

| Компонент | Микросервисный режим | Монолитный локальный режим |
|---|---|---|
| **Сеть gRPC** | TCP сокеты на N портах | Прямой вызов в памяти (`in-process`) |
| **Логирование** | Файловая ротация + агент Loki | Цветной человекочитаемый вывод в `stdout` |
| **Трассировка** | Экспорт спанов в OTLP gRPC | Отключена / in-memory no-op |
| **Метрики** | Экспорт через OTLP | Легковесный единый эндпоинт `/metrics` |
| **Vault** | N HCL-конфигов Vault Agent | **1 общий Vault** + переменные окружения в `.env` |
| **Базы данных** | N отдельных инстансов Postgres | 1 Postgres с отдельными базами/схемами |
| **Kafka** | Кластер брокеров | 1 брокер Kafka с автосозданием всех топиков |

---

## 4. Единый `monolith/docker-compose.yml`

Все инфраструктурные зависимости монолита поднимаются одной командой:

```yaml
version: "3.8"

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: lectify
      POSTGRES_PASSWORD: password
    ports:
      - "5432:5432"
    volumes:
      - ./infra/init-postgres.sh:/docker-entrypoint-initdb.d/init-postgres.sh:ro

  kafka:
    image: apache/kafka:latest
    ports:
      - "9092:9092"
    volumes:
      - ./infra/init-kafka.sh:/init-kafka.sh:ro

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    ports:
      - "9000:9000"
      - "9001:9001"

  vault:
    image: hashicorp/vault:latest
    environment:
      VAULT_DEV_ROOT_TOKEN_ID: "root"
    ports:
      - "8200:8200"
    volumes:
      - ./infra/init-vault.sh:/init-vault.sh:ro
```

---

## 5. Структура генераторов в `utils/codegen`

```
utils/codegen/src/generators/monolith/
├── __init__.py
├── runner.py               # Главный раннер генерации монолита
├── main_gen.py             # Генератор monolith/main.py
├── inprocess_grpc_gen.py   # Генератор inprocess_grpc.py и стабов
├── compose_gen.py          # Генератор docker-compose.yml и init-скриптов
├── settings_gen.py         # Генератор settings.py и .env.example
└── requirements_gen.py     # Слияние requirements всех активных сервисов
```

### CLI команда:
- `codegen monolith` (или `python3 utils/codegen/src/cli.py monolith`) — генерирует проект в `monolith/`.

---

## 6. Пользовательский опыт (DX)

```bash
# 1. Сгенерировать локальный монолит
codegen monolith

# 2. Поднять инфраструктуру и запустить всё приложение
cd monolith
docker compose up -d
python main.py
```
