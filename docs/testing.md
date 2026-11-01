# Проверки

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
