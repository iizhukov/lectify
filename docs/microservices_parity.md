# Функциональный паритет Lectify: монолит → микросервисы

Снимок исходного состояния на 2026-10-29. Документ фиксирует объём реализации и критерии проверки; наличие файла, манифеста или protobuf само по себе не означает готовность функции. Статусы ниже основаны на чтении исходников, без запуска кластера или внешнего LLM API. Они должны обновляться после реализации и проверки.

## Границы готовности

Цель — сохранить пользовательские возможности `old_monolit` в микросервисной архитектуре и дополнительно обеспечить распределённые плагины, агента каждого плагина и несколько экземпляров сервисов. Исправления авторизации и изоляции обязательны: уязвимые соглашения монолита (например, произвольный `user_id` в query и общие списки приватных файлов) не являются частью требуемой совместимости.

В сервисных `src/` остаются бизнес-модели и обработчики. HTTP/gRPC серверы и клиенты, настройки, подключение БД/S3/Kafka, трассировка, проверка identity, транспорт агента, тестовые фикстуры и инфраструктурные манифесты должны порождаться codegen. Перегенерация не должна уничтожать пользовательскую логику и тесты.

## Проверенное исходное состояние

- `services/api/{auth,profile,file,prompt,workflow,execution,llm}/service.yaml` пусты. У существующих API protobuf в `proto/api/` размер 0 байт; отдельного protobuf LLM в этом каталоге нет.
- `services/orchestrator/agent/service.yaml`, `proto/orchestrator/agent/index.proto`, `services/plugins/provider/service.yaml`, `services/infra/personal/service.yaml` пусты.
- `apps/` не содержит пользовательского интерфейса. Интерфейс монолита расположен в `old_monolit/resources/`.
- `infra_config` и `infra_tas` имеют бизнес-обработчики, модели, миграции и тесты. Это свидетельство реализации отдельных компонентов, а не проверки полного приложения.
- У оркестратора есть protobuf, модели исполнения, DAG, обработчики и тесты. `src/engine/docker_runner.py` имитирует выполнение и возвращает вымышленный артефакт. Сам pipeline последовательно проходит узлы, но не маршрутизирует фактические входы и выходы.
- `StreamRouter` использует локальные очереди процесса и не обеспечивает распределённый транспорт. Регистрация/подписки исполнения также локальны процессу.
- В новых `plugins/` четыре плагина: `input_streamer`, `speech_to_text`, `llm_transform`, `text_to_md`. Их наличие не означает паритет с восемью плагинами монолита.
- `services/{api,infra,orchestrator,plugins}/docker-compose.yml` пусты. Корневой Compose подключает эти категории и инфраструктуру; готового запуска бизнес-приложения это пока не даёт. Nginx по умолчанию направляет на документацию.

## Матрица пользовательских функций

Пути HTTP в таблице — исходный публичный контракт. Для нового приложения нужен либо совместимый HTTP-слой, либо явно проверенная миграция UI на новый контракт. Владелец обозначает целевую ответственность, а не уже реализованную маршрутизацию.

| Функция и исходный контракт | Источник монолита | Целевой владелец | Исходное состояние | Что доказывает готовность |
| --- | --- | --- | --- | --- |
| Регистрация, login, logout, refresh: `POST /api/auth/{register,login,logout,refresh}` | `src/api/auth.py`, `src/db/repository/auth.py` | `api/auth`, данные пользователя — `infra/personal` | Нет реализации | HTTP→RPC→БД; уникальные username/email; пароль хранится хешем; expiry/revocation; истёкшая/отозванная сессия отвергается всеми репликами |
| Восстановление пароля: `POST /api/auth/{forgot-password,reset-password}` | `src/api/auth.py`, auth repository | `api/auth` + адаптер доставки уведомлений | Нет реализации | Одноразовый ограниченный по времени reset token, повторное использование запрещено; отсутствие раскрытия существования аккаунта; проверенная доставка через тестовый адаптер |
| Профиль: `GET/PUT /api/profile`, `PUT /api/profile/password` | `src/api/profile.py` | `api/profile`, `infra/personal`; смена секрета — `api/auth` | Нет реализации | Владение берётся из проверенной identity; смена пароля требует текущего; обновления видны на другой реплике |
| Загрузка, список, метаданные, скачивание: `POST/GET /api/files`, `GET /api/files/{id}`, `GET /download/files/{id}` | `src/api/routes.py`, `src/utils/storage.py` | `api/file` | Нет реализации; S3-обёртки есть в codegen | Реальная потоковая загрузка/скачивание в S3, ограничения размера, owner ACL, безопасное имя, метаданные в БД, повтор и частичный сбой не создают доступный чужой/битый файл |
| Промпты: `GET/POST /api/prompts`, `GET/PUT/DELETE /api/prompts/{id}`, `GET /api/prompts/{id}/render` | `src/api/prompts.py` | `api/prompt` | Нет реализации | Глобальные и пользовательские промпты; шаблон/переменные; CRUD и безопасный render; проверка доступа к чтению/изменению |
| Каталог плагинов: `GET /api/nodes/plugins`, `GET /api/nodes/plugins/{plugin_id}` | `src/api/nodes.py`, `src/plugins/registry.py` | Оркестратор — реестр; `api/workflow` — публичный каталог | Есть сырой registry RPC, нет полноценного публичного каталога | Версии, категории, параметры/порты, разрешения, UI-метаданные; валидация манифеста и фильтры; недопустимые образы/манифесты отвергаются |
| Шаблоны узлов: `GET/POST /api/nodes`, `GET/PUT/DELETE /api/nodes/{id}` | `src/api/nodes.py`, `src/db/repository/node_template.py` | `api/workflow` | Нет реализации | CRUD шаблонов и параметров, пользовательские/общие записи, ACL; ссылка только на доступную версию плагина |
| Шаблоны workflow: `GET/POST /api/workflows`, `GET/PUT/DELETE /api/workflows/{id}` | `src/api/workflows.py`, `src/db/repository/workflow_template.py` | `api/workflow` | Нет реализации | Граф, имя, описание, видимость, привязки параметров; CRUD; запрет циклов/неизвестных портов; версии workflow и snapshot при запуске |
| Запуск: `POST /api/workflows/{id}/execute` с language и `input_files` | `src/api/workflows.py` | `api/execution` → оркестратор | Есть только стартовый внутренний RPC оркестратора | Загруженный файл и промпт доходят до плагина; сохраняется immutable snapshot; idempotency запроса; реально создаются результаты |
| История и детали: `GET /api/workflows/executions`, `GET /api/workflows/executions/{id}`, `.../{id}/nodes`, `.../{id}/nodes/{node_id}` | `src/api/workflows.py` | `api/execution` | Внутренний RPC статуса оркестратора частично реализован | Фильтры, пагинация, права, состояния/тайминги/прогресс, фактические параметры/входы/выходы; чтение через любую реплику |
| Старые history endpoints: `GET /api/workflows/history`, `GET /api/workflows/history/{id}` | `src/api/routes.py` | `api/execution` compatibility layer | Нет реализации | Решение о совместимости основано на потребителях и тестах; нельзя незаметно потерять историю существующих данных |
| Cancel/restart: `POST /api/workflows/executions/{id}/{cancel,restart}` | `src/api/workflows.py`, `src/orchestrator/service.py` | `api/execution` → оркестратор → агент | Cancel меняет строку БД; не останавливает pipeline; pause/resume/retry RPC — заглушки | Отмена останавливает работу агента и потомков; терминальное состояние не перезаписывается; restart пропускает успешные узлы; pause/resume/retry имеют настоящую семантику, если доступны через API |
| Артефакты: `GET /api/workflows/executions/{id}/artifacts`, `GET /api/artifacts/{id}`, `GET /download/artifacts/{id}` | `src/api/workflows.py`, `src/api/routes.py` | `api/file` — хранение; `api/execution` — привязки к запуску | Нет реализации; runner возвращает фиктивные пути | Оригиналы и промежуточные/финальные результаты доступны по ACL; presigned URL с TTL или streaming; S3 paths не дают обходить tenant boundary |
| Логи узлов: `GET /api/workflows/executions/{id}/nodes/{node_id}/logs` | `src/api/workflows.py`, `src/orchestrator/logs.py` | Оркестратор/агент + `api/execution` | Нет рабочей цепочки сбора/выдачи | Логи по конкретному execution/node/attempt, безопасный доступ, сохранение после удаления контейнера, отсутствие токенов в логах |
| Алерты: `POST /api/alerts/webhook` и Telegram | `src/api/routes.py`, `src/utils/telegram.py` | Инфраструктурный notification adapter/endpoint | Alertmanager есть, публичный обработчик не перенесён | Подписанный/защищённый webhook, тест доставки, контролируемые повторы и отсутствие секрета в логах |
| UI: вход/регистрация/восстановление/профиль, список/редактор графа, executions и детали, prompts, files | `src/web/routes.py`, `resources/templates`, `resources/static/js` | `apps/` + generated gateway/routing | Нет нового UI | Браузерный сценарий: создать пользователя, загрузить файл, собрать/сохранить DAG, запустить, наблюдать, скачать результат; не обращаться к старому монолиту |

Исходные web routes также ссылаются на страницы `/`, `/reset-password`, `/files/{id}`; наличие route не доказывает наличие корректного HTML: соответствующие шаблоны нужно проверить при переносе. README не считается доказательством работы recovery или media pipeline без теста/исполнения.

## Паритет плагинов и провайдеров

| Плагин монолита | Реальная бизнес-функция | Новый эквивалент и пробел | Критерий проверки |
| --- | --- | --- | --- |
| `input` | Исходный файл и его тип | `io/input_streamer` — заготовка | Агент получает назначенный файл/stream, выдаёт байты и метаданные, не читает произвольный host path |
| `media_converter` | FFmpeg: audio/video → нужный аудиоформат, длительность | Отсутствует | Малый audio/video fixture реально конвертируется в Docker; timeout, неверный формат и слишком большой input контролируются |
| `speech_to_text` | Сегментация длинного аудио, STT, язык и transcript artifact | `media/speech_to_text` — имитация текста | Проверяется сегментация, склейка, язык, retries и настоящий STT provider adapter; бесплатные тесты с HTTP fixture, отдельный бюджетный live smoke |
| `prompt_selector` | Выбор промпта, system/user templates, подстановка переменных | Отсутствует | Чтение разрешённого промпта через provider, правильное разрешение переменных, запрет чужого prompt ID |
| `llm_request` | Произвольный LLM-запрос, модель/temperature/token limit/timeout, результат | `ai/llm_transform` — заглушка | Реальный provider adapter с ограничениями и timeout; параметры действительно влияют на запрос; поток/ошибки/usage обрабатываются |
| `text_to_md` | LLM создаёт структурированный Markdown из transcript с выбранным/default prompt | `format/text_to_md` — заготовка | Результат содержит ответ адаптера и сохраняется как `.md`; ограничение входа и выбранный prompt проверяются |
| `text_to_latex` | Классификация предмета, генерация полного `.tex`, очистка code fences | Отсутствует | Фикстуры для предметов/fallback, валидный результат, сохранение `.tex`, downstream связь с PDF |
| `latex_to_pdf` | Компиляция PDF и ограниченное исправление ошибок через LLM | Отсутствует | Настоящий PDF в ограниченном контейнере, shell escape запрещён, нет доступа к host/секретам/сети, timeout; ограниченные попытки repair и логи ошибок |

LLM/STT credentials доступны только сервису провайдера и секретному хранилищу. Плагины работают через разрешённый API агента, не получают общий API key. `api/llm` может отвечать за политику запроса/лимиты, `plugins/provider` — за вызовы внешних адаптеров; границу нужно закрепить протоколом, не дублировать клиентов. URL, модели и ограничения Polza требуют проверки официального API перед live интеграцией. Ключи нельзя записывать в этот документ, манифесты или тесты. Названия старых моделей — исторический контракт, а не обязательный выбор провайдера.

## Дополнительные требования распределённой архитектуры

| Требование | Исходное состояние | Необходимое доказательство |
| --- | --- | --- |
| Самостоятельный Docker image каждого плагина с агентом команд | Есть шаблон Dockerfile и main с чтением локального input pipe, нет действующего агентного протокола | Собрать два разных плагина; агент принимает start/input/finish/cancel/status, проверяет команду и изоляцию assignment, возвращает поток/прогресс/артефакты |
| Оркестратор поставляет данные по DAG | Есть topological sort и отдельные локальные очереди | Fan-out/fan-in, именованные порты, порядок chunk/EOF, backpressure и ошибки; разные узлы на разных worker hosts |
| Несколько оркестраторов/агентов | Исполнения запускаются detached asyncio task; владение и подписки в памяти процесса | Durable queue/lease, heartbeat, fencing token, дедупликация команд/результатов; убийство владельца не теряет работу и не запускает узел дважды без контроля |
| Несколько экземпляров API/infra сервисов | RPC codegen есть; кластерные манифесты и проверки отсутствуют | Discovery/load balancing, shared persistent state, graceful shutdown, deadlines/retries; запросы переключаются между репликами без потери сессий/задач |
| Обновления конфигов и авторизация сервисов | Config/TAS реализованы, config polling генерируется | RPC policy tests + интеграционные проверки, timeout/cancellation, bootstrap unavailable, ротация, согласованность кэша; не полагаться на process contextvars как shared state |
| Бойлерплейт и тестовая инфраструктура в codegen | Есть grpc/db/s3/kafka/config/TAS/scheduler/observability и testing generators | Чистый checkout → одна документированная команда генерации/тестов; отсутствие ручных generated patches и внешних секретов для unit tests |
| Запуск/миграции/seed/observability | Инфраструктурный Compose есть, категории сервисов пусты | Полный локальный startup с health/readiness, миграциями/seed; cluster deploy; metrics/logs/traces с корреляцией execution/node/attempt и alerts |

## Порядок реализации и проверочные ворота

1. **Основание runtime и контрактов.** Зафиксировать версии контрактов, protobuf API/agent/provider, identity и ошибки; расширить schema/codegen для HTTP gateway и агентного runtime. Добавить полезные тесты с выполнением сгенерированного кода: ввод/вывод, cancel, deadlines, небезопасные manifests, неоднократная генерация. Здесь же — startup/shutdown и тестовые зависимости, чтобы следующий сервис не требовал собственного boilerplate.
2. **Данные и пользовательский API.** Реализовать personal/auth/profile, file, prompt, workflow с миграциями, ACL и HTTP compatibility. Тесты должны ходить через публичную границу, проверять чужого пользователя и фактическую персистентность. Добавить seed стандартных промптов и workflow без импорта монолитных modules.
3. **Рабочий execution/agent/provider вертикальный сценарий.** Upload → input → transcript fixture/provider → Markdown → artifact download. Удалить production mocks из runner/provider, подключить именованные входы/выходы, фактические агентные команды и безопасные контейнеры. Пройти Docker integration без платных вызовов; live API smoke — отдельно, с минимальным бюджетом.
4. **Полный plugin parity.** Media converter, prompt selector, generic LLM request, LaTeX и PDF с repair. Проверить реальные FFmpeg/TeX исполняемые файлы в изоляции, output schema и промежуточные артефакты. При одинаковом пользовательском сценарии не требуется копировать ошибки старых реализаций.
5. **Распределённая надёжность.** Durable dispatch, leases/fencing, idempotency/outbox, worker capabilities/placement, cancel/retry/recovery, ограничение ресурсов и сетевых разрешений. Проверить минимум две реплики оркестратора и worker на двух узлах, crash/restart, duplicate delivery, network timeout и недоступность зависимостей. Локальная asyncio очередь не может закрыть эти ворота.
6. **UI и эксплуатация.** Перенести страницы и graph editor на новый API, добавить e2e браузерный сценарий, deploy manifests, документированные команды, миграционный/backup/restore путь для старых данных, monitoring/alerts. Запускать весь пользовательский pipeline без `old_monolit` runtime.
7. **Независимый аудит и release gate.** Другие агенты проверяют security, parity и multi-instance semantics, замечания исправляются. Свежая генерация + весь test suite + настоящий Docker/cluster сценарий + бюджетный live smoke + browser e2e дают доказательства по каждой строке матрицы. Непроверенные строки остаются открытыми.

## Что ещё потребуется от окружения

Разработка и автоматические бесплатные тесты не требуют дополнительных ответов пользователя. Для заключительной проверки понадобятся доступный Docker daemon, тестовый cluster context/worker hosts и registry, способ доставки писем/reset notification и внешний URL/TLS/domain production. До предоставления этих данных реализацию контрактов, бизнес-логики, изолированных tests и локального deployment следует продолжать. Production доступ и секреты не должны быть обязательной зависимостью unit/contract tests.

## Источники проверки

- Публичные возможности: `old_monolit/src/api/{auth,profile,prompts,nodes,workflows,routes}.py`, `old_monolit/src/web/routes.py`.
- Данные/переходы состояний: `old_monolit/src/db/{entity,models,repository}/`, `old_monolit/src/orchestrator/{service,input_resolver,container_runner,logs}.py`.
- Плагины и LLM: `old_monolit/src/plugins/plugins/*/{plugin,models}.py`, `old_monolit/src/plugins/{base,datasource,registry,runner}.py`, `old_monolit/src/llm/`.
- UI: `old_monolit/resources/templates/`, `old_monolit/resources/static/js/`.
- Новое состояние: `services/`, `proto/`, `plugins/`, `utils/codegen/src/{config,generators,templates}/`, `infra/`, корневой `docker-compose.yml`.

Тесты монолита полезны как примеры бизнес-сценариев, но не служат доказательством работы нового приложения. Синтаксическая компиляция шаблонов и существование generated files также не доказывают RPC connectivity, Docker execution, ACL или cluster recovery.
