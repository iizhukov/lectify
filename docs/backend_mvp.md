# Backend платформы ETL

Название пока сохраняется. Продукт — распределённое исполнение DAG из плагинов.
Фронтенд в эту работу не входит. Старый монолит используется только как эталон функций.

## Локальный запуск с одним агентом

Из корня репозитория:

```sh
python3 infra/local/backend.py up
python3 infra/local/backend.py smoke
python3 infra/local/backend.py status
python3 infra/local/backend.py down
```

Нужны запущенный Docker Desktop и зависимости Python для codegen.
Первый запуск собирает образы и загружает зависимости; следующие используют кэш.
PostgreSQL, MinIO, сервисы и один агент работают в локальной Docker-сети.
К Docker socket подключён только агент. Миграции применяются перед запуском сервисов.
Команда down сохраняет данные PostgreSQL и MinIO в Docker volumes.
Локальные пароли и сертификаты создаются в `.local/backend/config`, исключённой из Git.
Учётная запись локального администратора — `admin`; пароль находится в приватном
`secrets.json` этого стенда. Скрипты его не печатают.
Сертификаты локального CA действуют 30 дней.

Опубликованные gRPC-порты: Auth 19021, Workflow 19024, Execution 19025,
File 19026, Orchestrator 19040. Они слушают только loopback и используют mTLS.
Пример работы с авторизацией и сгенерированными клиентами — `infra/local/smoke.py`.
Манифест `services/tools/client/service.yaml` задаёт разрешённые вызовы клиентской утилиты.

## Метрики

Полный перенос плагинов и дополнительные сценарии монолита отслеживаются в
[monolith_scenarios.md](monolith_scenarios.md). Для них используется отдельная команда:

```sh
python3 infra/local/backend.py up --test-provider
python3 infra/local/backend.py scenarios
```

`--test-provider` явно включает локальную HTTP-имитацию провайдера без пересылки
запросов наружу. Реальная конвертация медиа и компиляция PDF выполняются нативными
FFmpeg/TeX в контейнерах. Этот режим не проверяет качество платных моделей.

Сервисы используют только сгенерированные `generated.observability`:

- gRPC: количество запросов, длительность, активные вызовы и коды завершения;
- workflow: завершения, ошибки и длительность;
- плагины: активные исполнения, завершения/ошибки/отмены, длительность, входящие
  и исходящие байты и количество чанков;
- агент: операции с контейнерами, их длительность и исход;
- принятые отчёты плагинов: gauges и counters с ограничением числа наборов меток.

Отдельные execution_id, node_id и user_id не используются как метки метрик.
В статусе узла отдельно сохраняются байты, чанки и длительность исполнения.
Sampling трасс применяется из настройки codegen; при остановке сервисы выгружают telemetry.

Доставка: сервис → OTLP gRPC → Collector → Prometheus.
Prometheus доступен по `http://localhost:19090`.
Примеры запросов: `application_operation_completed_total`,
`application_operation_duration_seconds_bucket`, `application_operation_bytes_total`,
`grpc_server_calls_total`. Логи TAS и Config поступают в локальный Loki через
сгенерированный logger; трассы принимает Collector.

## Контракты

- Workflow API создаёт, изменяет, копирует и версионирует графы. Исполнение получает неизменяемый снимок.
- Узел ссылается на точную версию плагина. Схема содержит именованные inputs, outputs и параметры.
- Ребро связывает конкретный output с конкретным input. Поддерживается разветвление потока.
- `input_mapping` связывает порт с `input.<имя>` из `StartWorkflow.initial_inputs`.
- `text_input` передаёт внешний текст в граф; `text_output` сохраняет результат через файловый сервис.
- `file_input` получает внешний ID файла через mapping порта `file_id` и читает его потоком.
  Право чтения связывается с сохранённым входом исполнения; файловый сервис проверяет владельца.
- `file_output` сохраняет бинарный поток как файл без изменения байтов.
- Execution API запускает снимок, возвращает состояния и артефакты, передаёт события и отменяет исполнение.
- `ListExecutions` возвращает историю текущего пользователя с пагинацией.

Пример графа без внешних моделей:

```json
{
  "nodes": [
    {"id":"input","plugin_id":"text_input","plugin_version":"0.1.0",
     "parameters_json":"{}",
     "input_mapping":[{"target_field":"value","source":"input.text","transform":"passthrough"}]},
    {"id":"format","plugin_id":"text_to_md","plugin_version":"0.1.0",
     "parameters_json":"{\"title\":\"ETL result\"}"},
    {"id":"output","plugin_id":"text_output","plugin_version":"0.1.0",
     "parameters_json":"{\"filename\":\"result.txt\"}"}
  ],
  "edges": [
    {"from_node_id":"input","from_output":"text","to_node_id":"format","to_input":"text_stream"},
    {"from_node_id":"format","from_output":"md_stream","to_node_id":"output","to_input":"text"}
  ]
}
```

Сначала администратор регистрирует манифесты через `RegisterPluginManifest`.
Сервис workflow получает схемы через `GetPluginManifest`. Затем пользователь создаёт граф,
запускает его через `StartWorkflow` с версией workflow, уникальным request_key
и `initial_inputs={"text":"Данные"}`. После завершения `GetStatus` возвращает
идентификаторы файлов в `nodes.output_artifacts`; содержимое скачивается через File API.

## Агенты и несколько реплик

На каждом Docker-хосте запускается один `orchestrator_worker`:

```sh
cd services/orchestrator/worker
python3 -m generated.main
```

Установить зависимости из `generated/requirements.txt`; на хосте нужен Docker CLI.
У процесса агента должен быть доступ к локальному Docker daemon.
Оркестратору Docker socket не нужен: операции выполняются по WorkerService gRPC.
Worker принимает только проверенный TAS ticket сервиса orchestrator.
Для удалённых соединений обязательны сертификаты mTLS.

Внутри контейнера остаётся прокси доступа к провайдеру, файлам и отчётам.
Он обслуживает одно назначение; управление контейнерами принадлежит агенту хоста.
Исполняемая программа получает параметры и scoped gRPC API. Команда программы
задаётся оператором в привязке образа, а не пользователем в workflow.
Готовая генерация runtime сейчас рассчитана на Python; другая программа должна
реализовать `PluginRuntimeService` из proto/plugins/index.proto.

На всех репликах оркестратора задать одинаковые:

- `LECTIFY_DEPLOYMENT_FILE` — путь к JSON-конфигурации размещения;
- `LECTIFY_EXECUTION_CREDENTIAL_KEY` — ключ шифрования credentials;
- `ORCHESTRATOR_DB_URL` — подключение к одной базе оркестратора в отдельном PostgreSQL-кластере.

Другие сервисы используют `<SERVICE_NAME>_DB_URL`, например `API_WORKFLOW_DB_URL`.
DSN и S3 secret key поступают через окружение; кодогенерация не встраивает их в defaults.
Миграции применяются отдельно до запуска реплик; сервисы не создают кластер БД.
Адрес каждого gRPC backend можно переопределить через `<SERVICE_NAME>_ADDRESS`.
TLS транспорта настраивается через `LECTIFY_GRPC_CLIENT_TLS_*` / `LECTIFY_GRPC_SERVER_TLS_*`.

Структура deployment JSON:

```text
workers: { Docker-daemon-ID: {
  endpoint: адрес WorkerService,
  network: имя Docker-сети,
  agent_endpoint: "{name}:50055",
  runtime_endpoint: "{name}:50056",
  network_aliases: ["{name}"]
}}
plugins: [{id, version, image: "sha256:...", command: ["/absolute/program"], cwd: "/runtime"}]
backends: {auth, file, prompt, provider, orchestrator, tas}
tls: {
  agent_server, runtime_server, control_client,
  runtime_client, sidecar_client, backend_client
}
```

Каждый объект tls содержит пути `certificate`, `private_key`, `roots`.
Ключи runtime и привилегированных ролей должны различаться.
Образы должны быть заранее доступны агентам и закреплены по SHA-256.
Для нескольких хостов нужна сеть, в которой оркестратор видит адреса контейнеров
по указанным endpoint-шаблонам, например attachable overlay с корректным DNS.
Обычная локальная bridge-сеть сама по себе несколько хостов не объединяет.
Endpoint и SAN сертификата должны совпадать. Для wildcard SAN можно задать
endpoint вида `{name}.plugins.internal:50055` и соответствующий `network_aliases`.
Реплики TAS должны использовать один заданный `INFRA_TAS_JWT_PRIVATE_KEY`;
автоматически созданный ключ отдельного процесса для нескольких реплик не подходит.

Владение исполнением, номер поколения и размещение контейнеров сохраняются в БД.
Планировщики реплик конкурируют за аренду; запоздалые записи отклоняются.
Очистка подтверждённых контейнеров обращается к назначенным агентам хостов.

## Подтверждённые проверки и ограничения

Локальный сквозной smoke проверяет штатную авторизацию, создание и изменение DAG,
идемпотентный запуск, реальные контейнеры плагинов на одном агенте, PostgreSQL,
сохранение и скачивание результата из MinIO, текстовые и бинарные входы/выходы,
историю, отмену, отказ при отсутствии входов и изоляцию данных пользователей.
Он также проверяет наличие метрик плагинов в Prometheus после доставки через Collector.
Повторный smoke проверяет чтение предыдущих сохранённых результатов.

Область локального MVP — эти backend-сценарии. Проверки нескольких машин отложены.
Сервисы по-прежнему общаются через gRPC; фронтенд и клиентский HTTP API в MVP не входят.

Потоки завершённых узлов хранятся в БД и воспроизводятся после потери владельца.
Pause/resume, ограниченные автоматические попытки и ручной retry проверены через gRPC.
Неопределённые Create остаются под наблюдением очистки до подтверждённого удаления;
отсутствие контейнера во время Create не считается окончательным результатом.
Промышленная выдача сертификатов остаётся отдельной работой.
Восемь плагинов монолита и пять готовых графов перенесены;
аудио/видео → STT → Markdown/PDF проверены на одном агенте с локальным HTTP-fixture
провайдера и настоящими FFmpeg/TeX. Проверены разбиение аудио и вход 19,2 МБ.
Библиотека загружается командой `python3 infra/local/backend.py seed`.
Проверки восстановления: `python3 infra/local/backend.py recovery`.
Две реплики на одном компьютере с одним агентом: `python3 infra/local/backend.py replicas`.
Гонка миграций в отдельной временной БД: `python3 infra/local/backend.py migration-race`.
Полный перезапуск и подробности/логи попыток: `python3 infra/local/backend.py execution-details`.
API Restart создаёт новое исполнение с parent_execution_id из сохранённых графа и входов;
GetDetails/GetNodeDetails/GetNodeLogs/DownloadNodeLog раскрывают историю владельцу.
Подробности и ограничения: [execution_details.md](execution_details.md).
