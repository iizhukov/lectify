# Gateway

HTTP-вход для композиции backend-вызовов через сгенерированные gRPC-клиенты.
Python 3.12+. Функции преобразования — доверенный код из репозитория, без песочницы.

## Запуск

Из корня репозитория:

```sh
export CODEGEN_ROOT="$PWD"
python3 utils/codegen/src/cli.py project
cd services/gateway
python3 -m pip install -r generated/requirements.txt
python3 main.py
```

Порт задаётся `GATEWAY_PORT` (по умолчанию 8080). Адреса backend задаются стандартными
переменными генератора: `API_FILE_ADDRESS`, `API_AUTH_ADDRESS`, `LECTIFY_TAS_ADDRESS`.
TLS использует `LECTIFY_GRPC_CLIENT_TLS_*` из generated transport; сервисные credentials
настраиваются существующим ticket-auth. Вызовы платных провайдеров для примеров не нужны.
Backend, TAS, сертификаты и OTLP Collector должны быть настроены отдельно.

`GET /docs`, `/openapi.json` — описание операций. `/health/live`, `/health/ready` —
проверка процесса и загрузки графов; readiness не гарантирует доступность всех backend.

```sh
curl -X POST http://localhost:8080/v1/files/compare \
  -H 'Authorization: Bearer YOUR_ACCESS_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"left_id":"file-1","right_id":"file-2"}'
```

`compare_files` читает два файла параллельно. `reload_file` повторно читает файл,
используя ID из результата первого узла: демонстрация зависимости и перекладывания
данных. Оба примера требуют существующих файлов, доступных пользователю. Для reload
тело запроса — `{"file_id":"file-1"}`.

## Графы

Каждая папка `graphs/<name>/` содержит `graph.yaml`, `schemas.py`, `mappings.py`.
В YAML задаются версия 1, ID, POST-маршрут, авторизация, ссылки `module:function`,
узлы с `parents`, RPC и timeout. Итоговый `response` перечисляет родителей и mapping.
Схемы — Pydantic BaseModel. Unknown YAML-поля, циклы, неизвестные родители, RPC,
повторяющиеся маршруты и узлы вне пути к ответу отклоняются при старте.
Streaming требует отдельного адаптера и в обычном графе запрещён.
Графы загружаются один раз при старте; обновление выполняется перезапуском образа.

Mapping — синхронная функция `ctx -> dict`. В ctx доступны копия проверенного input,
копии protobuf-результатов непосредственных родителей и неизменяемый principal.
Клиентов и токенов в ctx нет. Mapping должен выполнять только ограниченные по времени
преобразования без I/O и общего изменяемого состояния. Произвольный Python не имеет
принудительного CPU-таймаута: требования обеспечиваются ревью доверенного кода.

Клиенты определены в `service.yaml`; универсальный каталог RPC генерируется из
protobuf-дескрипторов и учитывает несколько protobuf-services и streaming.
`src/` и `graphs/` не являются результатом генерации.

## Исполнение и ошибки

Зависимости определяют порядок, независимые узлы выполняются параллельно.
Лимиты на процесс: 128 HTTP-запросов, 128 RPC, тело запроса 1 MiB, ответ 4 MiB.
В графе не более 128 узлов; параллельность и deadline задаются YAML.
Deadline включает авторизацию и обработку графа; загрузка тела ограничена 10 секундами.

Ошибка узла отменяет остальные задачи; HTTP-disconnect и deadline отменяют RPC.
Повторов и распределённой транзакции нет: отмена не откатывает backend-изменения.
Несколько реплик не требуют общего состояния gateway. Долгая работа хранится в backend;
для изменяющих операций гарантия повторного запроса зависит от идемпотентности backend.

Ошибка возвращает `code` и `request_id`; внутренние детали и токены не выдаются.
Ответ содержит `X-Request-ID` и `X-Trace-ID`. Backend повторно проверяет ACL;
пользовательский токен делегируется только как `x-user-authorization`.

## Трассировка

HTTP SERVER-span покрывает весь запрос, включая авторизацию и отправку ответа.
Внутри — spans валидации, графа, узлов, mappings, protobuf и формирования ответа.
Общий gRPC CLIENT-interceptor переносит W3C traceparent/tracestate; backend создаёт
SERVER-span и продолжает контекст во вложенных вызовах. Ticket-auth и config не
создают дубликатов CLIENT-span. Их прямые инфраструктурные каналы также трассируются.
Связи DAG с несколькими родителями представлены span links; узлы — дети graph-span.

По умолчанию gateway создаёт новую трассу на публичном входе. Для доверенного ingress,
который проверяет/заменяет входящие заголовки, можно включить
`GATEWAY_TRUST_TRACE_CONTEXT=true`, чтобы продолжать traceparent фронтенда.
Sampling gateway — 100%; доверенный remote parent сохраняет своё sampling-решение.
Для хранения всех трасс Collector также должен сохранять их без sampling и потерь.
При shutdown клиенты закрываются, trace exporter сбрасывает буфер.
Тела и токены не добавляются в spans, тексты исключений не экспортируются.

## Проверки

После генерации из корня:

```sh
python3 -m pytest services/gateway/tests -q
python3 -m pytest utils/codegen/tests/test_trace_propagation.py -q
python3 utils/codegen/src/cli.py test
```

Тесты используют локальные TCP-порты, реальные gRPC-серверы и in-memory exporter.
Проверяют последовательность, параллельность, metadata, ошибки, отмену, OpenAPI,
общий trace_id, реальные parent_span_id, вложенный RPC и изоляцию запросов.
Это не проверка запуска всей инфраструктуры Lectify с действующими credentials.
