# Проверки

Сквозной локальный backend с одним агентом:

```sh
python3 infra/local/backend.py up
python3 infra/local/backend.py smoke
python3 infra/local/backend.py down
```

Smoke использует настоящие gRPC, PostgreSQL, MinIO и Docker-контейнеры плагинов.
Проверяет текстовый и бинарный DAG, отмену, приватность и доставку метрик в Prometheus.
Платные провайдеры не вызываются. Данные сохраняются в volumes после down.

Плагины и готовые сценарии монолита:

```sh
python3 infra/local/backend.py up --test-provider
python3 infra/local/backend.py seed
python3 infra/local/backend.py scenarios
python3 infra/local/backend.py recovery
python3 infra/local/backend.py migration-race
python3 infra/local/backend.py replicas
python3 infra/local/backend.py execution-details
```

`seed` создаёт пять общих графов и два промпта через gRPC, сохраняя существующие записи.
`scenarios` использует явный локальный HTTP-fixture провайдера; FFmpeg и TeX настоящие.
Проверяются ветвление DAG, части аудио, большие входы и запуск пользовательских копий
общих графов. Качество и доступность внешних моделей этот режим не проверяет.
`recovery` намеренно перезапускает только локальный оркестратор через SIGKILL;
проверяет бюджет попыток, ручной retry, pause/resume и восстановление без повторного
запуска завершённого источника. `replicas` временно запускает две реплики оркестратора
на этом компьютере с одним агентом и возвращает обычную конфигурацию.
`migration-race` создаёт и удаляет отдельную временную БД для двух конкурентных миграторов.
`execution-details` проверяет полный перезапуск завершённого, неудачного и отменённого
исполнения, неизменность сохранённого графа после удаления workflow, подробности попыток
и скачивание настоящих TeX-логов через gRPC. Контракты и ограничения: execution_details.md.

Сначала сгенерировать код, затем запустить тесты сервисов и плагинов:

```sh
export CODEGEN_ROOT="$PWD"
python3 utils/codegen/src/cli.py project
python3 utils/codegen/src/cli.py test
```

Тесты самого кодогенератора:

```sh
python3 -m pytest utils/codegen/tests -q
```

Проверки приложения находятся в `tests/integration`.
Скрипты запускаются отдельно: часть требует Docker или PostgreSQL.
Они не вызывают платные модели без отдельного разрешения.
