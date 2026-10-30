# Запуск проверок

Из корня репозитория:

```sh
python3 utils/test.py
```

Команда сначала регенерирует активные сервисы и плагины, затем запускает обнаруженные наборы тестов в отдельных Python-процессах. Каждый процесс работает в каталоге своего сервиса/плагина, поэтому одноимённые `src` и `generated` не пересекаются. Код выхода ненулевой при ошибке генерации или любого набора. Это запуск тестов, а не подтверждение готовности кластера: фактическое покрытие определяется тестами каждого компонента.

```sh
python3 utils/test.py --list
python3 utils/test.py --no-generate --suite utils/codegen
python3 utils/test.py --no-generate --suite plugins/ai/llm_transform --suite plugins/format/text_to_md
```

`--no-generate` подходит для итераций, когда generated-зависимости уже подготовлены или выбранные тесты создают их во временных каталогах. Virtualenv, generated и node_modules исключены из обнаружения; old_monolit запускается отдельно и не подменяет проверки нового приложения. Новые наборы с каталогом `tests/` и файлами `test_*.py` обнаруживаются автоматически. Для локальных gRPC-тестов нужен доступ к loopback bind; Docker/MinIO/PostgreSQL проверки могут требовать отдельного доступного окружения.

Для сервисов, чьи тесты создают isolated generated-окружение в subprocess, задайте `service.testing.generated_fixtures: false`. Тогда новый tests/conftest.py не импортирует generated из checkout. По умолчанию сохраняется прежний TestKit contract. Существующий пользовательский conftest.py при генерации не перезаписывается.
