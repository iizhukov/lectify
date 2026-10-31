# Ход реализации микросервисного Lectify

Общая цель остаётся открытой: полный функциональный паритет с `old_monolit`, распределённые Docker-плагины с агентами, несколько экземпляров сервисов, инфраструктурный код и тестовые фикстуры в codegen. Объём и проверочные ворота перечислены в [microservices_parity.md](microservices_parity.md).

## Проверено 2026-10-29

Рабочая ветка — `dev`. Уже имевшиеся незакоммиченные изменения плагинов и оркестратора сохранены.

- Codegen компилирует общий `proto/plugins/index.proto` в каждый plugin image. Ошибка protoc прерывает генерацию.
- Generated SidecarAgentClient действительно вызывает шесть RPC агента: streaming LLM, streamed artifact upload, prompt, progress, metrics и logs. Есть deadline, execution/node metadata и необязательный bearer token. Сервер должен проверять identity и permissions; клиент сам не создаёт границу безопасности.
- Ошибки RPC, отрицательные acknowledgements и EOF без финального LLM frame не маскируются успешным результатом. Generated main закрывает канал при успехе, ошибке и отмене.
- Dockerfile устанавливает generated requirements; версии grpc/protobuf согласованы с компилятором генерации.
- Исправлены исполняемые Python literals/defaults, экранирование описаний, допустимые имена параметров, delimiter bytes и зацикливание/повтор overlap в буфере.
- Тесты feature flags генерируют зависимости во временном каталоге; заранее созданные ignored `generated/` не нужны.
- `python3 -m pytest utils/codegen/tests -q`: **124 passed**. Включены реальные loopback gRPC проверки без внешнего LLM/API, negative paths и исполнение generated main.
- `LECTIFY_ROOT=$PWD python3 utils/codegen/src/cli.py project`: exit 0. Пустые manifests ещё пропускаются с предупреждениями; это незавершённые сервисы, а не доказательство готового приложения.
- Независимый аудит RPC выявил отсутствие cleanup в main и неявный terminal frame contract. Оба замечания исправлены, покрыты тестами.
- Docker CLI есть, daemon недоступен. Сборка образов и cluster e2e пока не проверены.

## Следующие обязательные этапы

1. Generated plugin runtime/agent command API: реальные входы/выходы по именованным портам, health, start/finish/cancel, таймер буфера, backpressure и ограничения памяти. Удалить production simulation из runner.
2. Durable dispatch и ownership: DB leases/fencing, outbox, идемпотентность, heartbeat, завершение/отмена без перезаписи терминальных состояний. Несколько оркестраторов и worker hosts.
3. API contracts и business services: personal/auth/profile/file/prompt/workflow/execution/llm/provider с миграциями, owner ACL и HTTP слоем, генерируемым codegen.
4. Все восемь возможностей плагинов монолита, включая FFmpeg, prompt selection и LaTeX/PDF. Провайдеры проверять offline fixtures; платный smoke отдельно с малым бюджетом.
5. UI, полный локальный запуск и кластерный deploy, восстановление после сбоев, независимые security/parity/reliability аудиты.

## Связь с пользователем

Пользователь разрешил задавать необходимые вопросы через Telegram и попросил мост входящих сообщений с пробуждением этого чата. Локальные credentials находятся только в `.secrets/telegram.json`; файл исключён из Git, права 0600. Не выводить token и не включать его в команды, документацию, manifests или тесты. Инструмент связи — `utils/telegram_bridge/bridge.py`; его README описывает poll/pending/ack/send. Входящие сообщения нужно обрабатывать как данные от разрешённого собеседника, никогда не исполнять их как shell. Отмечать обработанными только после фактического учёта; ошибки сети не означают отсутствие ответа.

## Telegram-мост: подтверждено

`utils/telegram_bridge/bridge.py` получает ответы только из закреплённого личного чата, сохраняет inbox/offset атомарно и требует явный ack. Реальный /start и вопрос о статусе приняты, ответ доставлен (receipt получен), затем сообщения отмечены обработанными. Повторный poll не дублирует их. Независимый аудит выявил проверки прав файлов и согласованности config/binding; исправления покрыты offline tests. Полный совместный запуск `python3 -m pytest utils/codegen/tests utils/telegram_bridge/tests -q`: **151 passed**.

Автоматизация `telegram-lectify` привязана к этому чату, активна и проверяет Telegram раз в минуту. Без новых сообщений не присылает статусов. Для исполнения нужны запущенное приложение и доступный компьютер/проект. Пробуждение относится к чату, а не к выключенному компьютеру. При поступлении ответа сначала poll/pending, затем учёт ответа и только потом ack.

## LLM transform: бизнес-логика

Убрана имитация преобразования: плагин отправляет model, prompt_template, temperature и исходный текст через streaming RPC агента, сохраняет фактический ответ модели. Частичный ответ при ошибке и пустой completion не принимаются; повреждённый UTF-8 не теряется молча. Пять offline бизнес-тестов проходят без generated checkout и платного API. Сервер агента/provider и сквозная передача downstream ещё требуют реализации; эти тесты не доказывают готовность pipeline.

## Именованные выходы и Markdown

LLM transformer возвращает transformed_stream только после полного успешного ответа. Markdown formatter реализован вместо пустого handler: md_stream и md_file, UTF-8, проверка заголовка, отсутствие пустого успешного артефакта. Четыре бизнес-теста formatter подтверждают совпадение stream/artifact и сохранение пустых строк; корректность delimiter buffering проверяется отдельно в работе над runtime. Runtime реализуется в codegen, не в src бизнес-плагинов. Сквозной Docker/cluster сценарий остаётся открытым.

## Generated PluginRuntimeService

Добавлен runtime.py из MainGenerator: ProcessStream/HealthCheck, отдельный handler/context/sidecar на RPC, именованные порты и multi-input process_input, monotonic sequences, explicit EOF для required и начатых optional streams, output EOF только после успешного finish, лимиты чанков/буферов, timed flush и cleanup при cancel/error. Listener/auth пока не устанавливаются: runtime должен подключаться к аутентифицированному агенту. Исправлена потеря empty delimiter batches. Автор проверил полный codegen suite: 126 passed; после финального ужесточения EOF повторно прошёл focused runtime real loopback test, включая multi-input. Project regeneration exit0 до последнего EOF изменения; повторная генерация ещё требуется в следующем общем gate. Независимый read-only аудит не нашёл новых дефектов в runtime. Девять бизнес-тестов LLM/Markdown вместе проходят с --import-mode=importlib. Эти результаты не подтверждают распределённый запуск, auth или Docker pipeline.

## Проверка DAG

Перед построением node_map отклоняются пустой граф, повторяющиеся, отсутствующие, пустые и нестроковые node IDs. Это исключает незаметное схлопывание разных задач в одну. Восемь standalone unit-тестов (tests/unit, --confcutdir на этот каталог) проверяют identity, зависимости, повторную сортировку и циклы. Независимый аудит identity-проверок не выявил дефектов. Проверка доступности plugin versions и совместимости портов ещё требуется.

## Локальная маршрутизация и server bootstrap

Маршрутизатор использует tuple keys, bounded queues, упорядоченный fan-out и unsubscribe. close_all выполняет abort, который разблокирует заполненные очереди и сообщает об ошибке вместо успешного EOF. Нормальный EOF сохраняет данные. 17 standalone DAG/router unit-тестов проходят. Это process-local компонент; distributed transport/ownership ещё не реализованы.

Generated server bootstrap добавлен: обязательный scoped token+execution/node, constant-time comparison, отказы duplicate headers, loopback/Unix listener и graceful shutdown. Audit split identity исправлен snapshot assignment в runtime/sidecar. Автор проверил focused RPC включая изменение env после bind и shutdown активного потока; итоговый полный suite/регенерация ещё ожидаются. Начата реализация business prompt service отдельным агентом, статус готовности пока не заявлен.

## Структура рёбер DAG

Добавлена проверка endpoint IDs, непустых именованных портов и повторяющихся одинаковых рёбер. Разные порты между одними узлами допустимы. 22 standalone DAG/router unit-теста проходят. Runtime автор реализует mTLS удалённого соединения; api_auth и api_prompt реализуются отдельными агентами. Требуется связать Authenticate с генерируемой trusted user principal проверкой; сырые пользовательские headers не являются identity.

## Генерация protobuf и начало пользовательской авторизации

Service gRPC server/client generation теперь fail-fast при отсутствующем proto или ошибке protoc; три реальных negative compiler tests проходят. api_auth.Authenticate contract закреплён (access_token -> user_id/is_admin/valid/username). Prompt service автор проверил через реальный gRPC+SQLite сценарий с миграцией upgrade/downgrade, ACL, optimistic concurrency и replica read. Применимость к production пока ограничена отсутствующей генерируемой user_auth boundary; автор prompt реализует её следующим шагом. Auth service и mTLS transport ещё выполняются/проверяются; готовность всей системы не заявляется.

## Совместимость gRPC runtime

Service RequirementsGenerator теперь согласует нижние границы grpcio/grpcio-tools/protobuf с установленным компилятором, аналогично plugin generation. Четыре targeted проверки генерации (missing/invalid server/client proto и runtime requirements) проходят. mTLS автор завершил focused TLS checks; независимый аудит поручен auth автору, auth аудит поручен runtime автору. Auth core прошёл SQLite scenario ротации refresh/reset, настоящий gRPC boundary ещё проверяется. user_auth интеграция codegen ещё в работе.

## Возобновление после лимита

Агенты были остановлены usage limit; работоспособность возобновлена. Перегенерация всего проекта завершилась exit0, остаются предупреждения пустых manifests. Audit user_auth выявил обход deadline во время TAS interceptor: root добавил outer asyncio.wait_for; runtime автор исправляет отдельный lifecycle TAS channels и regression. Auth автор завершает durable reset outbox против timing enumeration. File service и необходимые S3 codegen helpers начал prompt автор. Готовность этих текущих изменений ещё не заявляется.

## Единый запускатель тестов

Добавлен utils/test.py: обнаружение suites в utils/services/plugins, отдельные pytest subprocess с cwd каждого компонента, предварительный project codegen по умолчанию, фильтр --suite, --list и --no-generate. Исключены venv/generated/node_modules; ошибки отдельных suites агрегируются с ненулевым exit. Проверены --list и две бизнес-suites LLM/Markdown:9 tests passed. Весь обнаруженный набор через новый runner ещё не проверен. Команды описаны в docs/testing.md; независимый аудит запрошен у runtime автора.

## Первый общий запуск suites

`python3 utils/test.py --no-generate`:11 из12 suites прошли. Codegen139 tests, auth4 scenarios, prompt1 scenario, examples4, config6, TAS13, orchestrator27, Telegram27 и LLM/Markdown9 прошли; input_streamer placeholder1 не доказывает реализацию. STT suite упал на настоящем RPC к отсутствующему агенту, а business handler пока создаёт фиктивный transcript. Это реальный незакрытый функциональный пробел; поручена замена на явный Transcribe RPC и meaningful tests, не сокрытие failure. В runner исправлены audit findings: pattern *_test.py и отсутствие suites теперь не дают ложного успеха. Три теста runner проходят. Новый suite runner ещё не входил в первоначальный12-suite запуск.

## Source-плагин и media RPC

input_streamer заменён с пустого handler на produce() async generator, который отдаёт именованный data_stream по чанкам sidecar.read_file; валидирует file_id/chunk size и распространяет storage failures. Семь business tests проходят. Runtime hook для no-input source produce проверен настоящим loopback RPC, порядок0/1/EOF2 подтверждён. Автор runtime добавил ReadFile/Transcribe contracts и bounded generated client, заменил fake STT transcript на ответ Transcribe; local test agent media RPC и три business tests проходят. Настоящий agent forwarding/file ownership/provider STT ещё требуют реализации: пока это транспорт и бизнес-контракт, не доказательство live audio pipeline. Полная регенерация+runner live71257 выполняется.

## Общая проверка после media/file/auth

`python3 utils/test.py` завершился exit0: регенерация и все14 обнаруженных suites прошли. Codegen141 tests, auth5 scenarios, file1 scenario, prompt1 scenario, plugins19 tests, examples4, config6, TAS13, orchestrator27, Telegram27, runner3. Большие сценарии включают много RPC assertions; эти counts не заменяют проверку полного покрытия. Объектное хранилище file scenario — double, не MinIO. Auth outbox stale-version race исправлен и independently re-reviewed. File/S3 audit ещё выполняется. Cluster/runtime agent/provider/UI и прочие parity requirements остаются открыты.

## Изоляция test scaffold

Root добавил service.testing.generated_fixtures (default true) для source-owned subprocess tests. При false новый conftest не импортирует checkout generated; existing conftest сохраняется. Два targeted tests проходят, включая exec нового conftest без generated и сохранение custom fixture. File Download cancellation leak исправлен автором и проверен targeted blocked-open test; независимый reviewer подтвердил исходный finding, final review ожидается. Provider HTTP codegen, agent boundary и workflow validation/service начали отдельные агенты; их полнота не заявляется.

## Проверка во время интеграции agent

Root core4 run85626: auth/file/prompt suites прошли, codegen142passed1failed из-за in-progress plugin_agent template/model integration (template references setting before imported schema had it). Это не успешный общий gate; автор уведомлён, требуется повторить после стабилизации feature. Дополнительно Service/ServiceManifest отклоняют unknown fields, чтобы misplaced/misspelled auth settings не игнорировались. Четыре targeted checks проходят, extensions business namespace остаётся поддержан.

## 2026-10-30: терминальные состояния оркестратора

Root изменил completion/failure на SQL compare-and-set WHERE state=RUNNING; поздний worker не перезаписывает CANCELLED/FAILED/COMPLETED и не публикует ложное terminal success. Cancel принимает только PENDING/RUNNING/PAUSED, повторный CANCELLED идемпотентен. Перед запуском следующего узла перечитывается состояние. Новые терминальные переходы ставят finished_at. 32 tests orchestrator passed через isolated runner, включая late success/failure after cancel. Read-only audit запрошен. Реальная остановка running container, durable worker lease/ownership и межрепликовый dispatch остаются незавершёнными; source/mock runner ещё не заменён.

## Audit отмены: конкурентность и cleanup

Аудит выявил два P2: проигравший concurrent cancel ошибочно отвечал FAILED_PRECONDITION и повторная отмена пропускала local router cleanup. Root исправил: failed CAS делает rollback+fresh SELECT, CANCELLED считается успехом; уже CANCELLED также проходит cleanup. Mapping router удаляется после close с проверкой identity, чтобы concurrent close не вызвал KeyError и interrupted cleanup мог повториться. Добавлены barrier-тест двух запросов, читающих RUNNING до CAS, и preexisting CANCELLED+router cleanup. 34 orchestrator tests проходят. Повторный read-only аудит запрошен; running container cancellation и durable ownership всё ещё не реализованы.

## Локальная остановка worker coroutine

StartExecution теперь хранит task handle; done callback удаляет только совпадающий handle и забирает исключение. Cancel после durable state transition отменяет и дожидается локального task, затем закрывает router. Тест blocked worker подтверждает finally cleanup, task.cancelled, удаление handles и DB CANCELLED с finished_at.35 orchestrator tests проходят. Независимый аудит запрошен. Это только локальный task lifecycle: произвольный контейнер/другая реплика должны останавливаться через будущий agent command plane и durable ownership; они не считаются готовыми.

## Audit async cleanup при отмене

Reviewer воспроизвёл repeat-cancel interruption of asyncfinally. Root ограничил cancel одним сигналом через Task.cancelling и shield ожидания gather, чтобы client-cancel RPC не отменял cleanup повторно. Regression держит worker в await внутри finally, отменяет первый Cancel RPC, запускает повторный и подтверждает завершённый cleanup после release.36 orchestrator tests passed; повторный readreview запрошен.

## Durable ownership foundation

Добавлены WorkflowDispatchModel и claim/renew SQL CAS helper: pending/expired active execution claims увеличивают fence; renew требует owner/fence/notexpired/RUNNING. Owner/TTL/time валидируются, commit обязан выполнить caller до external work. Начальная frozen migration0001 создаёт4 таблицы orchestrator; upgrade/downgrade SQLite проверены.39 orchestrator tests pass. Пока нет enqueue/worker poller/heartbeat интеграции и ReportNodeEvent fencing: multi-instance execution не считается реализованным. Попытка запросить независимый lease audit через существующего reviewer отклонена tool agent thread limit; аудит остаётся открытым. Другие ранее active агенты возобновлены по доступной квоте, завершают provider/workflow/agent.

## Dispatch claim интеграция и checkpoint

StartExecution сохраняет dispatch в одной транзакции с execution, parent flush предшествует дочернему insert. Local worker wrapper claims/commits lease до pipeline, heartbeat продлевает каждые10сек и отменяет pipeline при потере lease.40 orchestrator tests pass, including two service instances only one enters sameclaimed pipeline. Poller recovery и fencing node writes/agent events ещё не подключены; full distributed exactly-once не заявлен. Full root runner95218: regen+16/16 suitespassed, codegen171. Создан interim checkpoint b8a059d (не release). После него runtime автор нашёл targeted glue blocker: prompt client protobuf descriptor escaping SyntaxError, исправление в работе; предыдущий общий gate не доказывает готовность latest backend glue.

## Fenced pipeline writes

Root передаёт owner/fence из lease wrapper в pipeline. guard_execution_write перед pipeline DB transactions locks matching current/notexpired dispatch row, затем RUNNING execution row, удерживая lock до commit. Старый/expired worker не получает write gate, cancelled execution отклоняется.41 orchestrator tests pass incl stale fence guard. Первоначальный прогон выявил старый teardown race: тест оставлял worker живым до drop tables; тест теперь явно CancelExecution+await cleanup, повторный gate прошёл. PostgreSQL race/deadlock verification и remote side-effect fencing через event/control plane остаются открыты. Runtime автор выполняет read-only audit.

## Единые часы lease

Production claim/renew/write guards теперь используют SQL clock expression БД (PostgreSQL clock_timestamp, SQLite current_timestamp), не time.time отдельного worker. Explicit now сохранён для deterministic tests.42 orchestrator tests pass including claim/renew/guard with native DB time. ReportNodeEvent реализует auth/workflow автор, scoped agent event_sink будет подключаться после закрепления контракта. Реальные PostgreSQL concurrency/clockwait semantics остаются отдельным gate.

## Recovery poller и Docker

Добавлен dispatch_pending: новая service replica читает persisted eligible jobs, восстанавливает DAG/inputs и запускает owned pipeline с leaseclaim; scheduler вызывает polling каждые5сек. Recovery test подтверждает запуск сохранённого задания новым экземпляром, activelease не планируется повторно. Предыдущий focused43tests прошёл. Новые claims сбрасывают reporttokenhash/fence, чтобы oldworker не могпереназначитьcapability на новыйfence. Pipeline artifactprojection теперь merge вместо overwrite (durableartifactReport в реализации peer). Docker Desktop был установлен, root запустил его; escalated dockerinfo подтвердил daemon27.4.0. Настоящие container gates теперь доступны и должны быть выполнены, прежний unavailable больше не blocker.

## Durable node reports: проверка контракта

После регенерации проекта orchestrator suite: 50 passed. Новые тесты проверяют durable ReportNodeEvent, повторную доставку с тем же sequence, конфликт event ID, неверный capability, старый fence, монотонность progress и запрет записи после отмены. Миграции 0001→0002→downgrade проходят на SQLite. Исправлен import pending_executions из dispatch вместо node_events. Отдельные codegen descriptor/workflow validation regression tests: 19 passed. Выдача capability при реальном запуске контейнера, полный agent→orchestrator путь и PostgreSQL concurrency остаются открыты.

Первый запуск disposable PostgreSQL завершился до проверок из-за гонки readiness: pg_isready увидел временный Unix server image entrypoint. Контейнер удалён в finally. Добавлено ожидание SELECT 1 через фактический опубликованный TCP endpoint; синтаксис проверен. Повторный Docker запуск не выполнен: automatic approval review исчерпал usage limit (сбой проверки разрешения, не unsafe verdict). PostgreSQL gate не считается пройденным. Последний Telegram poll также не удался из-за connectivity; пустой pending не подтверждает отсутствие новых входящих.

## Выдача reporting capability

Добавлен issue_report_capability: DB-clock lease guard блокирует dispatch и RUNNING execution до commit, затем сохраняется только SHA-256 случайного 256-bit bearer token. Повторная выдача ротирует токен, новый claim сбрасывает hash/fence, чужой или expired claim не может выпустить токен. Проверены ротация, новый владелец, отказ старому владельцу и точная граница expiry. Node event integration test теперь использует настоящий issuer вместо ручного заполнения hash. Orchestrator suite: 51 passed; focused node-event/dispatch повторный прогон: 15 passed. Helper пока не вызывается из production container launch: этот путь ещё требует реализации и сквозной проверки.

## Изоляция повреждённых заданий recovery

dispatch_pending теперь отклоняет неверную форму сохранённого графа/inputs и помечает такое execution FAILED только после успешного claim и write guard. Обработка остальных строк batch продолжается. WorkflowDAG валидирует списки объектов до обращения к полям. Четыре regression cases подтверждают запуск здорового задания рядом с повреждённым, включая null/array graph и неверные nodes/edges. Orchestrator suite: 55 passed. ContainerLifecycleManager всё ещё симулирует выполнение; его замена реальным generated container/agent transport остаётся обязательным незавершённым пунктом.

## Удаление ложного успеха container dispatcher

Обнаружено: use_mock игнорировался менеджером, а production service всегда включал симуляцию. Теперь OrchestratorServiceImpl по умолчанию создаёт менеджер без симуляции; незаданный container dispatcher выдаёт явную ошибку до progress callback и fake artifact. Симуляция доступна только через явно переданную тестовую зависимость. Проверено сохранение FAILED вместо COMPLETED в pipeline без dispatcher. Suite до последнего regression: 57 passed; новый focused dispatcher suite: 3 passed. Реальный запуск контейнеров пока не реализован; это исправление убирает ложную готовность, но не закрывает требование Docker/cluster execution.

## Согласованные состояния при сбое pipeline

Обработчик ошибки теперь в той же lease/fence-guarded транзакции переводит активные PROVISIONING/BUFFERING/PROCESSING nodes в FAILED вместе с execution. Завершённые узлы и их артефакты сохраняются. Full orchestrator suite: 58 passed; после усиления regression проверки сохранности completed node focused dispatcher/service: 17 passed. Независимый read-only аудит dispatch/report/recovery передан существующему audit agent; результат на момент записи ещё не получен.

Audit agent подтвердил P1: recovery повторно запускал COMPLETED nodes. Pipeline теперь проверяет durable node state под lease guard и пропускает такие узлы до external launch; regression подтверждает запуск только pending node и сохранность артефакта completed node. Это устраняет подтверждённый повтор после durable completion, но не закрывает crash-window между внешним side effect и записью результата: launch idempotency и durable stream replay ещё необходимы.

## Generated plugin runtime client

Добавлен manifest flag plugin_runtime_client.enabled и генерация PluginRuntimeClient со shared plugins protobuf/transport без включения agent server. Orchestrator manifest включает клиент. Клиент передаёт bearer+execution/node metadata, использует существующий remote-mTLS transport, ограниченный deadline, проверяет declared output ports, последовательности, EOF каждого выхода и chunk limit; закрывает RPC в finally и channel через async context manager. Восемь focused tests прошли, включая отдельную генерацию и повреждённые/оборванные output streams; совместный descriptor/workflow regression до добавления generation case: 26 passed. Project regenerated, generated client импортируется. Некоторые исходные service.yaml ещё пусты и сообщают warnings при project generation — оставшиеся сервисы не считаются реализованными. Подключение клиента к container dispatcher и реальный gRPC/Docker end-to-end gate остаются открыты.

## Generated Docker transport

При plugin_runtime_client.enabled также генерируется DockerSandbox: async argv-only Docker CLI, digest-pinned image, deterministic execution/node/fence name, no host bind mounts, no host networking, user1000, read-only root, dropped capabilities, no-new-privileges, pids/memory/cpu/tmpfs limits. Создание/запуск/state/removal и async context cleanup реализованы как транспорт, без plugin business policy. Совместные client/sandbox tests: 14 passed с fake runner; project regenerated, оба generated modules импортируются. Реальный Docker запуск и подключение к ContainerLifecycleManager ещё не выполнены. Crash/cancellation window во время create до получения container ID требует reconciliation по доверенной assignment identity; независимый audit запрошен, результат пока ожидается.

Audit подтвердил create-cancellation orphan и прерывание cleanup повторной отменой. launched теперь ожидает защищённое завершение create, при отмене не запускает полученный контейнер и удаляет его; cleanup выдерживает повторные cancel. Новый regression моделирует отмену до получения ID и два cancel во время rm: 7 sandbox tests passed. Не закрыт отдельный неопределённый исход timeout/crash Docker CLI: если daemon создал контейнер, но ID окончательно потерян, нужна reconciliation по проверенным ownership labels. Это остаётся обязательным пунктом перед production integration.

## Docker attempt identity и reconciliation primitive

create теперь требует attempt_id (32 hex), который caller должен durable сохранить до запуска; метка включается в container create. При timeout/invalid response reconciliation делает inspect только identity+managed+attempt labels и удаляет по полному container ID исключительно при совпадении попытки. Чужая метка/ошибка inspect не трактуются как отсутствие контейнера и не приводят к удалению. Public reconcile позволяет повторить очистку по durable assignment. Tests моделируют потерянный create response и несовпадающую попытку; Docker/runtime-client focused: 17 passed. Сохранение attempt_id и фоновой cleanup job в БД, защита от конкурентного повторного launch одной попытки, real Docker semantics и production dispatcher integration ещё не реализованы; primitive не доказывает crash recovery всего приложения.

## Durable launch intent

Добавлены workflow_container_attempts и миграция 0003. prepare_launch под dispatch/execution guard проверяет active node, фиксирует immutable image и отдельный attempt_id для execution/node/fence/role; повтор подготовки возвращает существующий ID, смена image отклоняется, новый fence получает новую попытку. Caller обязан commit до Docker create. Plugin/agent роли разделены также в Docker container name. Orchestrator: 60 passed включая миграции upgrade/downgrade; client/sandbox: 17 passed. Таблица пока хранит подготовку: lifecycle state transitions, cleanup scheduler и вызов из production pipeline ещё предстоят. Сохранение intent само по себе не предотвращает два конкурентных external create и не доказывает cluster exactly-once.

## Launch state transitions

begin_launch делает guarded CAS PREPARED→CREATING; caller обязан commit до external create. Повторный вызов получает False, неопределённый CREATING не сбрасывается в PREPARED. record_container принимает только полный Docker ID, текущий owner/fence и CREATING с пустым ID, затем CAS→CREATED; повторная подмена ID отклоняется. Regression проверяет повтор, stale owner и cancelled execution; full orchestrator: 60 passed, после усиления cancellation assertion focused launch повторно прошёл. Независимый read-only аудит запрошен. Wiring в production dispatcher, cleanup transitions/scheduler и настоящая PostgreSQL конкуренция остаются открытыми.

Audit завершён: подтверждённых дефектов в launch preparation/CAS/model/migration не найдено; отмечен единый lock order dispatch→execution→attempt. Audit не подтверждает real lifecycle и обязанность caller commit до Docker по-прежнему требует проверки при wiring.

## Durable launch coordinator

launch_container связывает prepare/commit, begin/commit, Docker allocation, record ID/commit и start. DockerSandbox разделён на allocated (create/cleanup) и launched (allocated+start), чтобы ID сохранялся до старта. Independent-session regression проверяет видимость CREATING перед create и CREATED+container ID перед start, затем remove и CLEANED. При неопределённой ошибке попытка остаётся для reconciliation; фонового обработчика пока нет. Focused launch: 2 passed, Docker transport: 9 passed. Production pipeline ещё не вызывает координатор; pairing agent/plugin, endpoint discovery и stream routing остаются незавершёнными.

## Scheduled cleanup подтверждённых контейнеров

cleanup_stale_executions вызывает cleanup_created_containers: bounded batch CREATED с сохранённым ID, execution terminal либо dispatch fence новее попытки. Current assignment не выбирается. Ошибка daemon/ownership сохраняет durable запись для повтора; успешный reconcile (включая доказанное отсутствие) переводит CREATED→CLEANED. Docker reconcile сначала выполняет exact-name container ls: пустой успешный ответ означает отсутствие, ошибка daemon распространяется; найденный полный ID дополнительно проходит проверку labels перед rm. Focused launch tests: 4 passed; Docker transport: 10 passed. Uncertain CREATING намеренно не подтверждается отсутствующим по одному snapshot — late daemon completion может создать контейнер позже. Полное crash recovery и production launch wiring всё ещё открыты.

## Реальные PostgreSQL и Docker gates

После истечения прежнего usage ограничения automatic approval разрешил изолированные проверки. utils/integration/orchestrator_postgres.py прошёл на PostgreSQL16: 12 конкурентных lease claims дают одного победителя; 12 begin_launch одного current owner дают один True; renew, новый fence, stale write rejection и cancellation rejection проходят. Используются отдельные async sessions; одноразовый tmpfs container удалён в finally.

utils/integration/docker_sandbox.py прошёл на настоящем Docker с cached digest-pinned Python image: generated create/start, read-only root, network none, memory512MiB/pids128, dropped ALL caps и no-new-privileges проверены через inspect; removal и repeat reconciliation подтверждены. Добавлен --pull=never: runtime не скачивает отсутствующий image. Скрипты не используют project volumes и paid provider. Project regenerated. Эти gates не доказывают full workflow/agent/plugin stream execution, container cluster scheduling или crash recovery uncertain CREATING.

## Реальный gRPC plugin stream gate

utils/integration/plugin_stream.py прошёл: generated PluginRuntimeClient → actual generated text_to_md runtime + business handler → generated scoped PluginAgentProxy с AssignmentPolicy. Передаётся текст с пустой строкой; проверяются точные Markdown bytes, EOF обоих declared outputs и совпадение artifact body. Backend artifact persistence явно тестовый in-memory (не file service). Negative calls с чужим node и неверным token отклоняются PERMISSION_DENIED/UNAUTHENTICATED до side effects; artifact count остаётся один. Проверка использует loopback, без Polza и project credentials. Docker pairing, production pipeline wiring, durable output/replay и реальное file-service хранилище этим gate не подтверждаются.

## Containerized plugin smoke: незавершённый запуск

Добавлен utils/integration/plugin_docker.py: explicit-file-only temporary build context (без secrets/project data), контейнер с actual runtime/client/scoped agent из plugin_stream, network none/read-only/nonroot. Backend artifact остаётся test-only in-memory. Docker transport и launch image validation допускают immutable local sha256 image ID наряду с repository@sha256 digest. Docker transport focused: 11 passed; launch focused: 4 passed. Запущен реальный build+smoke, unified exec session 11390; последняя проверка подтверждает, что процесс ещё жив, результата нет. Не перезапускать до terminal state/явного решения об ограничении времени. Изменение script timeout/log output относится только к следующим запускам, текущий процесс использует прежний quiet build. Container gate не заявлен пройденным. Telegram poll снова завершился connectivity error; pending_count=0 не доказывает отсутствие входящих.

## Audit: daemon routing и start authority

Audit выявил P1: глобальный cleanup на другой Docker replica мог увидеть absence на чужом daemon и потерять job. Попытка теперь хранит daemon_id (модель + ещё не выпущенная миграция0003), prepare запрещает смену daemon, cleanup фильтрует текущий Docker info.ID. Регрессия подтверждает сохранность foreign-daemon attempt. P2: cancellation между record commit и start; start теперь выполняется под повторным dispatch/execution guard с удержанием lock во время bounded Docker start. Regression инъецирует cancel после record commit и подтверждает create/remove без start. Focused launch: 5 passed; предыдущий full orchestrator до последней assertion:63 passed; реальный PostgreSQL lease/launch concurrency gate повторно прошёл с daemon scope.

Старый quiet build остановлен по explicit 600-second budget после620сек; подтверждён terminal exit1/context canceled в session11390, временный context очищен родительским finally. Ни готовый образ, ни runtime container этим build не получены. Причина задержки пока не диагностирована; следующие build используют plain progress и timeout600. Containerized plugin gate остаётся непройденным.

## Container plugin smoke прошёл

Последующая диагностическая сборка session15033 остановлена после наблюдения base resolve; отложенный вывод показал успешное разрешение за54сек и переход к pip. Причина исходного долгого quiet build достоверно не установлена. Следующий запуск session87767 с plain progress и pip timeout15/retries1 завершился exit0: зависимости установлены, отдельный образ собран, настоящий runtime-client→text_to_md→scoped agent smoke внутри Docker прошёл с network none/read-only/nonroot. Runtime container и собственный образ удалены finally. Содержимое артефакта проверено тестовым in-memory backend; production file-service storage, отдельные agent/plugin процессы и workflow dispatcher этим smoke не подтверждены. Общий runner --no-generate запущен на текущем дереве; результат ожидается.

Общий runner завершился exit0:16/16 suites passed, codegen193 tests, orchestrator64 tests. Staged diff credential-pattern и whitespace checks прошли. Это промежуточный checkpoint, не release/full-parity claim: остаются production dispatcher, agent command plane/container pairing, durable stream routing/replay, оставшиеся API/UI/monolith plugins и полный deployment gate.

## Generated process supervisor и раздельные процессы

Добавлен generated process_supervisor для plugins и agent/runtime-client services. run_pair запускает trusted argv без shell в двух process groups, сопровождает operation и ранний exit любого server считает ошибкой; finally TERM→bounded wait→KILL/reap останавливает оба процесса. Spawn ожидается shield до получения handle; cleanup выдерживает повторную отмену. Три теста с настоящими Python child processes проверяют success/cancel/early exit, совместный supervisor/runtime-client focused:11 passed.

utils/integration/plugin_processes.py запускает actual scoped agent и text_to_md runtime отдельными процессами через supervisor; parent runtime client проверяет stream и artifact test backend. plugin_docker теперь выполняет этот вариант. Реальная Docker build+run session29708 завершилась exit0 с network none/read-only/nonroot; созданный container/image удалены. Это process composition smoke с test-only artifact backend, не production agent command plane/secret isolation/deployment. Независимый audit supervisor запрошен, результат пока ожидается.

Audit подтвердил P2: быстро завершившийся leader мог оставить TERM-ignoring descendant, потому что KILL выполнялся только при timeout ожидания leader. Cleanup теперь завершает оставшуюся owned group через KILL после grace phase независимо от состояния leader. Новый regression запускает настоящего потомка, игнорирующего TERM, и проверяет остановку его heartbeat; все4 supervisor tests проходят. Spawn shield и repeated cleanup shield audit новых дефектов не выявил, но детальные инъекционные тесты этих гонок ещё не добавлены.

## Generated supervised entrypoint

generated.main plugins поддерживает opt-in PLUGIN_MODE=supervised. Trusted image composition передаёт LECTIFY_AGENT_COMMAND_JSON как bounded argv list, shell не используется. Entry point запускает agent и server-mode runtime через supervisor и корректно завершает пару по SIGTERM/SIGINT. Default server/external-sidecar mode сохранён: production image пока не содержит готовую agent composition. plugin_processes Docker smoke теперь вызывает именно generated.main supervised; session78118 exit0, created image/container удалены. Focused supervisor/plugin RPC13 passed вне sandbox; первый restricted запуск упёрся только в запрещённый loopback bind и не считается продуктовой ошибкой. Добавлены negative argv validation cases. Это ещё не production dispatcher/agent command plane/secret isolation.

## Generated concurrent stream graph

Generic DAG/router перенесены из src implementations в codegen templates stream_dag/stream_router; прежние src paths оставлены как compatibility imports. Новый generated stream_pipeline.run_streaming_graph подписывает все edges до запуска producers, запускает node adapters конкурентно, переименовывает incoming port, сохраняет sequence/EOF, ограничивает fanout очередями router и отменяет весь graph при ошибке/обрыве. Regression fanout250 frames (queue100), consumer failure и missingEOF прошли. Audit нашёл повторную отмену adapter cleanup: исправлено через asyncio.wait без implicit child cancellation и единый shielded cleanup с once-only task.cancel. Regression repeated cancel с ожидающим adapter finally прошёл. Project regenerated; orchestrator68 tests passed, focused codegen runtime-client/workflow26 passed. Runner пока не подключён к production pipeline и не реализует durable stream replay после смены владельца; это следующий обязательный integration шаг.

## Service streaming dispatcher adapter

RuntimeStreamDispatcher связывает trusted async assignment context с generated PluginRuntimeClient: принимает deployment endpoint/token/declared outputs, преобразует protobuf frames и гарантирует aclose/close при завершении. Workflow parameters не выбирают transport authority. OrchestratorServiceImpl использует concurrent graph для dispatcher.supports_streaming; PROCESSING/COMPLETED writes проходят lease guard, completion callback вызывается только после input/output EOF validation. Regression service source→sink проверяет COMPLETE при корректном EOF и FAILED nodes/execution при обрыве, без преждевременного completed projection. Focused service+graph6 passed. Default dispatcher всё ещё не имеет production assignment resolver и остаётся fail-closed; для completed stream nodes без durable replay явно возвращается ошибка, а не повтор внешних effects. Реальный Docker lifecycle/registry/assignment resolver надо связать следующим шагом.

Audit выявил duplicate assignment window до первого client await и раннее освобождение reservation при teardown. Исправлено: task reservation до первого await удерживается до выхода всех contexts; stop_node отменяет provisioning и ждёт cleanup. Две regression cases проходят. Общая generated DB fixture теперь использует per-test temporary SQLite file, независимые sessions; ненужный schema DROP исключён, engine dispose предшествует удалению tmp file. Первый полный прогон выявил shared-memory race, затем teardown locking и неверное ожидание FAILED для ещё не стартовавшего PENDING node; после исправлений общий runner16/16 passed, codegen201, orchestrator72. После этого добавлено удаление active router по окончании owned worker и assertion cleanup; focused полный orchestrator повторяется.

## Verified execution ownership

Orchestrator manifest включает generated user_auth(api_auth). StartExecution требует verified principal и фиксирует его user_id, подмена request owner отклоняется. Status/cancel/events/lifecycle проверяют owner или verified admin; чужой execution возвращает NOT_FOUND, подписка не создаётся. Plugin registration admin-only, listing authenticated. Pause/resume/retry больше не возвращают fake success: до durable checkpoint/replay дают UNIMPLEMENTED после ACL. Четыре security tests покрывают missing principal, owner spoof, cross-user read/cancel/subscribe, admin registration restriction и отсутствие фиктивного lifecycle success.

Общий прогон выявил intermittent SQLite lock при cancellation параллельного node DB write. Добавлен generated db.transactions.run_transaction: short DB-only callback завершает commit/rollback/close до propagation caller cancellation; streaming begin/complete используют helper. Две helper tests проверяют repeated cancel и rollback. Последний общий runner: codegen203 и остальные14 suites прошли, orchestrator имел2 старых timing failures (default unconfigured dispatcher успевал стать FAILED раньше Cancel). Тесты start/status/cancel теперь используют explicit WaitingRunner и ждут его start; последний полный orchestrator:76 passed. Единого нового16/16 прогона после этих тестовых исправлений ещё не было. Production assignments/default dispatcher и durable replay остаются открыты.

## Atomic cancellation и durable report subscription

CancelExecution теперь в одной settled DB transaction меняет execution и незавершённые PENDING/PROVISIONING/BUFFERING/PROCESSING nodes на CANCELLED; COMPLETED/FAILED nodes и сохранённые артефакты не меняются. Повторная отмена идемпотентна, regression всех состояний прошёл.

StreamExecutionEvents читает NodeEventModel из БД вместо process-local subscriber queue, cursor after_sequence добавлен в proto, durable ExecutionEvent.sequence отражает node report sequence. Отдельные current-state snapshots имеют sequence0 и metadata snapshot=true; это не full historical execution-state journal. State читается до node report query, terminal закрывается после drain всех страниц; guarded reports не могут commit после terminal transition. DB session закрывается до network yield. Regression другой service replica с105 events, resume cursor, terminal closure и negative cursor прошёл. Полный orchestrator80 passed после regen; независимый audit запрошен. Durable stream payload replay/production assignment resolver по-прежнему отсутствуют.

Усилен terminal-drain regression: последний report и CANCELLED сохраняются одной транзакцией, уже открытый stream выдаёт report перед terminal snapshot и EOF. Focused events/auth7 passed. Запрошенный независимый audit этого участка не завершился из-за usage limit audit agent; успешный audit не заявляется.

## Idempotent StartExecution

Стабильный request.execution_id теперь привязан к verified owner, workflow, нормализованному graph и initial_inputs. Повтор того же запроса возвращает текущее состояние и исходный started_at без нового dispatch/task; другой payload получает ALREADY_EXISTS, чужой owner NOT_FOUND. Concurrent duplicate PK во время parent flush обрабатывается rollback/read/reuse; execution+dispatch+nodes коммитятся одной settled transaction до запуска. Отмена вызывающего RPC после commit оставляет durable dispatch для recovery poller. Введена bounded validation ID под DB column limits.

Две regression cases проверяют две реплики, count execution/dispatch/node=1, один runner start, conflict, чужого пользователя и повтор CANCELLED без restart. Полный orchestrator82 passed. Real PostgreSQL integration дополнен двумя service replicas с одинаковым StartExecution; gate прошёл вместе с lease/launch/fencing/cancellation, одноразовый container удалён. Независимый audit повторно запрошен после времени reset; результат ожидается. API execution facade и production container assignment resolver ещё отсутствуют.

Audit завершён: подтверждённых дефектов в StartExecution reuse/concurrent flush/commit-before-scheduling и terminal report drain не найдено. Проверка опирается на существующую сериализацию guarded reports через execution lock; snapshot sequence0 не является историческим state event.

## Typed snapshot→orchestrator contract

При подготовке API execution выявлена потеря JSON types: workflow хранит parameters_json, orchestrator имел только map<string,string>. В WorkflowNode добавлены совместимые parameters_json, input_mapping_json и prompt_id; normalizer сохраняет bool/int/float/nested dict/list/null и frozen mapping, отклоняет mixed legacy/JSON, duplicate keys, NaN/Infinity/overflow exponent и oversized JSON. Пустые новые поля не добавляются в persisted graph, чтобы legacy start-idempotency не менялась. Graph limits256 nodes/1024 edges согласованы с workflow validator. После regen полный orchestrator89 passed, после последнего cap focused typed/idempotency/auth13 passed. API execution facade остаётся пустым — реализован необходимый transport contract prerequisite, не сам сервис. TLS-политика межсервисного forwarding также требует отдельного завершения перед внешним deployment.

## Execution API facade

Реализован api_execution: StartWorkflow через immutable caller-owned snapshot, stable UUID5 execution ID, typed node/input mapping/prompt forwarding, GetStatus, Cancel и resumable bounded StreamEvents. Snapshot scope/version/UUID/hash проверяются; execution response/event scope и cursor проверяются. API передаёт только verified delegated credential через generated user_auth helper; TAS/channel/deadline/entrypoint инфраструктура генерируется. Execution.workflow_id для запусков через facade ссылается на snapshot ID. Локальной БД/дублирующей проекции состояния у facade нет. Unit tests с backend stubs:4 passed; это не доказательство реального трёхсервисного gRPC deployment.

Audit нашёл repeated-cancel channel cleanup race. Исправлен общий generated GrpcClients: shared once-only close task, shielded settle для всех concurrent close callers, запрет reopen после close. Regression с blocked channel/interceptor, двумя close callers и repeated cancel прошёл; audit подтвердил фикс, других ошибок owner/idempotency/forwarding в просмотренном facade не нашёл. После regen общий runner17/17 passed, codegen204 и orchestrator89. Production TLS/assignment resolver/durable payload replay и оставшиеся monolith parity gates остаются открытыми.

## Generic service mTLS transport

Добавлен grpc_transport opt-in и включён для active API/auth/file/prompt/workflow/execution, TAS/config, provider и orchestrator. Shared TLS transport генерируется для service client/server; generic gRPC, TAS и config direct clients требуют mTLS для remote endpoints. Без TLS server default loopback, remote plaintext bind запрещён. Credentials all-or-none, server require_client_auth, hostname verification без override; local Unix/loopback development сохранён. Добавлена явная grpcio-health-checking dependency и единая interceptor-capable server/run signature.

Real generated client/server mTLS test проверяет certificate handshake, отсутствие client certificate, hostname mismatch, remote plaintext rejection и stop listener. Общий runner после feature17/17 passed (codegen205, orchestrator89). Audit выявил startup-cancel cleanup gap; try/finally расширен на bind/start, shielded stop выдерживает повторный cancel. Усиленный real bootstrap test прошёл, audit подтвердил фикс. Project regenerated; latest generic и legacy generated code syntax проверяется отдельно. Cert/Vault provisioning и полноценный deployed service chain всё ещё не проверены; mTLS feature не означает готовый production deployment.

## Docker DNS mTLS и TAS dependencies

Endpoint validation теперь принимает используемые codegen Docker имена с underscore при TLS, plaintext remote по-прежнему запрещён. DockerSandbox поддерживает bounded validated network_aliases только для named network. Первый двухконтейнерный тест упёрся в попытку подключить сеть к network-none container; исправлена композиция create сразу в internal network с aliases. Повторный utils/integration/service_tls_docker.py exit0: client mTLS к api_auth принят, wrong_auth alias того же container отклонён hostname verification. Temporary CA key не копируется в build context; test leaf certs/image/network/containers одноразовые, cleanup завершён.

TAS port и импорт берутся из configured tas_service/manifest. Audit выявил забытое dependency injection infra_tas в GrpcClientGenerator; исправлено на configured dependency. Полная regression генерации custom_tas protobuf+клиентов и импорт TicketAuthClient прошла. После regen общий runner17/17 passed, codegen209, orchestrator89. Это transport/DNS gate, не full API/auth/workflow/orchestrator deployment и не production certificate provisioning.

## Plugin agent control plane

Добавлен generated PluginControlService (Start/Stop/Status) для одного trusted assignment. Команды не принимают executable или environment от RPC caller: argv/env задаются assignment. Отдельный control capability не принимается обычными Agent RPC; runtime token не допускается к control RPC. Start резервируется один раз, одинаковый command ID идемпотентен, другой конфликтует; Stop завершает process group и reap, terminal assignment не перезапускается. Child environment формируется явно с принудительным execution/node/server scope. Это предотвращает случайное наследование секретов, но не создаёт изоляцию между процессами одного UID.

Real local gRPC/subprocess regression проверяет роли, scope, один PID при concurrent Start, env, Stop/reap и запрет restart. Независимый audit выявил repeated-cancel listener cleanup gap в scoped server; добавлен shared shielded stop с regression. Production assignment resolver, доставка credentials, controller image composition и cluster scheduling остаются открытыми.

Control интегрирован в RuntimeStreamDispatcher через trusted assignment.control: Start до открытия runtime stream, Stop после закрытия runtime client и до teardown assignment. Generated running context отправляет Stop также при потере ответа Start и защищает его от repeated caller cancellation. Regression проверяет порядок cleanup при runtime failure и lost Start response/repeated cancel. Production resolver по-прежнему не настроен; optional control используется только явно поставляемыми доверенными назначениями.

Audit control integration выявил spawn/readiness race: RUNNING подтверждает процесс, но listener ещё запускается. Runtime ProcessStream теперь использует wait_for_ready под existing bounded RPC deadline. Real gRPC regression с задержанным server.start прошёл; focused9 passed. До этого readiness fix полный runner17/17 passed (codegen210, orchestrator90); production cluster composition остаётся открытой.

Проверен utils/integration/plugin_processes.py --controlled: отдельный agent process в READY получает Control Start, создаёт отдельный generated text_to_md runtime process, реальный gRPC stream сохраняет Markdown artifact через scoped agent, running context отправляет Stop, status STOPPED подтверждён, agent завершается. Explicit in-memory/file test backend; Docker/production storage/cluster resolver этим gate не проверяются. Exit0.

После readiness fix и controlled-process integration полный runner17/17 passed: codegen210, orchestrator90. Независимый audit подтвердил readiness fix, новых confirmed defects в просмотренном пути не нашёл.

## Controlled plugin Docker packaging

Codegen генерирует Dockerfile.controlled с named build context lectify_agent, отдельными /agent и /runtime import roots, объединённой установкой requirements и nonroot entrypoint прямо в agent run_server. Trusted runtime assignment должен задавать cwd=/runtime, absolute Python executable и явный child environment. Оба build contexts следует готовить из allowlisted generated/src файлов, не передавать весь repository с credentials. Generated controlled Dockerfile отдельно ещё не собран.

utils/integration/plugin_docker.py обновлён на controlled mode: отдельный agent запускает runtime по Start, stream/artifact, Stop/STOPPED. Real Docker build/run exit0, network none/read-only/nonroot; temporary image/container удалены. Этот gate использует отдельный тестовый Dockerfile и не доказывает production image/credential provisioning. Focused plugin RPC9 passed.

## Generated controlled image build gate

Добавлен utils/integration/controlled_image.py: два временных allowlisted generated/src context, сборка именно generated Dockerfile.controlled, nonroot/read-only/network-none container probe, agent imports из /agent и runtime subprocess imports из /runtime с явным env. Удалена внешняя syntax frontend dependency: первый build не смог получить docker/dockerfile:1.4. Следующий build дошёл до pip и упал; повтор после PyPI timeouts успешно собрал образ и прошёл probe, exit0. Этот probe проверяет packaging, не настоящий assignment/backend deployment и не изоляцию секретов между одинаковыми UID.

Audit нашёл timeout cleanup gap harness: docker CLI timeout не останавливает daemon container. Добавлены уникальные имя/label, проверка ownership и finally rm -f; отдельный image cleanup даже при inspect/remove failure. Два regression cases проверяют owned и foreign label. Полный codegen212 passed. Docker daemon failure и late build completion требуют отдельной reconciliation политики; отсутствие ресурсов при недоступном daemon не считается доказанным.

## Read-only container assignment bootstrap

Real Docker experiment: cp в stopped read-only rootfs отклонён daemon, поэтому такой transport не подходит текущему sandbox. Agent loader поддерживает mutually-exclusive private FILE (до1MiB) или LECTIFY_AGENT_ASSIGNMENT_JSON (до32KiB); inline source удаляется из process env после чтения. Strict JSON отклоняет duplicate keys, nonfinite/overflow и non-object. Credentials в Docker env остаются доступны администраторам Docker daemon; это не secret isolation от одинакового UID. Runtime environment по-прежнему задаётся явно.

Audit выявил существующий FILE FIFO startup hang до fstat. Добавлен O_NONBLOCK, реальный mkfifo без writer отклоняется сразу. Focused3 passed. Generated controlled image rebuilt, probe создал actual agent server и controller через src.create_agent из inline fake assignment без proxy injection, отдельные import roots verified, exit0. Сетевые backend calls и distributed assignment resolver этим gate не проверены.

## Explicit Docker worker routing

Generated DockerSandbox принимает trusted context name и добавляет --context ко всем daemon operations, включая identity/reconcile/remove; process-global context/env не меняются. Имена валидируются, arbitrary CLI flags/host URI не принимаются. Durable launch передаёт network_aliases, необходимые для certificate DNS endpoints. Existing attempt.daemon_id продолжает запрещать cleanup чужого daemon и смену daemon для того же attempt.

Unit14 passed, real utils/integration/docker_sandbox.py explicit-current-context gate exit0: create/start/limits/removal/repeat reconciliation. Это проверка worker transport, не распределённый scheduler. Не подключены automatic worker placement, credentials issuance и production assignment resolver; existing default dispatcher остаётся fail-closed.

Полный gate worker routing сначала выявил flaky api_file checksum assertion: DATA_LOSS публиковался до завершения finally close. Download теперь закрывает storage response до terminal EOF/error. Audit нашёл double-close при отмене pre-terminal cleanup; заменено once-only closing task с detach до await и shielded settle repeatedcancel. Regression блокирует close и проверяет отсутствие terminalstatus; direct service/DB generator отменяется дважды, cleanup ждёт release, close_calls==1. Focused file passed.

После исправления File Download полный runner17/17 passed: codegen213, orchestrator90. Независимый audit подтвердил once-only close и explicit Docker context routing.

## Durable worker placement

Codegen генерирует DockerWorkers: bounded immutable trusted daemon inventory и deterministic rendezvous hashing execution/node/role. prepare_worker_launch под lease lock сначала читает существующий attempt, сохраняет daemon для нового, повтор использует прежний. Исчезнувший worker вызывает явную ошибку вместо silent migration той же попытки. launch_on_worker коммитит placement, сверяет daemon выбранного context вне DB lock и проходит существующий prepare/begin CAS/record/start/cleanup.

Unit проверяет одинаковый выбор при разном порядке inventory у реплик, распределение по200 nodes, минимальное перемещение новых placements и pinned assignment. SQLite regression сохраняет attempt при расширении inventory и отказывает при удалении assigned worker. Real PostgreSQL12 concurrent placements дали один attempt/daemon, затем один launch winner; fencing/cancel/two-replica Start gates также прошли, temporary PG container удалён. Полный runner17/17 passed (codegen214, orchestrator91). Независимый audit новых confirmed defects не нашёл. Это persisted placement helper, production dispatcher ещё не подключён к credentials/image/endpoint resolver; multi-daemon deployed cluster не проверен.

## Runtime assignment resolver composition

Generated ContainerRuntimeAssignments связывает immutable trusted image bindings, committed placement callback, trusted grants context и durable launch. Business adapter src.engine.assignments.runtime_assignments использует existing prepare_worker_launch/launch_on_worker. Перед контейнером placement уже PREPARED в БД; image не берётся из workflow parameters; EXEC/NODE scope принудительный, control command ID равен attempt ID. Runtime endpoints выдаются внутри container context, grant cleanup идёт после container teardown.

Existing real-SQLite launch regression теперь проходит через resolver и проверяет committed grant ordering, image/scope override protection, create/start/remove и grants cleanup. Generic regression проверяет launch failure cleanup и отсутствие provisioning unknown plugin version. Full runner17/17 passed (codegen214, orchestrator91), затем новый focused resolver test1 passed. Независимый audit confirmed defects не нашёл. Конкретная grants policy (делегированный пользователь, once-per-lease report capability, сертификаты, endpoints, безопасный отзыв при duplicate contenders) пока не реализована, default dispatcher остаётся fail-closed. Этот composition helper не является готовым production resolver/deployment.

## In-memory TLS credentials for read-only assignments

Shared TLSConfig.from_env поддерживает mutually-exclusive complete *_CERT/KEY/CA_PEM или *_CERT/KEY/CA_FILE. Inline ASCII PEM ограничены32KiB/field, partial/empty/mixed sources отклоняются без credential values в ошибках. Scoped ServerConfig.from_env использует общий loader; direct TLSConfig и legacy positional files сохранены, repr скрывает credential material. Generic clients/servers, agent/backend/sidecar/TAS/config получают тот же transport.

Real unit mTLS использует inline server/client PEM: handshake, no-clientcert rejection, hostname rejection, badsource limits и scoped config. Docker integration создаёт CA/leaf credentials вне buildcontext и передаёт PEMenv двум read-only containers: api_auth принят, wrong_auth отклонён, exit0; resources удалены. Full runner17/17 passed (codegen215, orchestrator91), независимый audit confirmed defects не нашёл. Production certificate issuance/grants policy/default resolver ещё открыты; memory loading не изолирует environment от Docker administrators или процессов одного UID.

## Immutable validated plugin registry

До grants assembly обнаружена mutable/unvalidated registry registration. Codegen runtime_client теперь поставляет общую PluginManifest schema из compiler source, bounded safe YAML loader и canonical JSON normalization; PyYAML включён в generated requirements. Loader запрещает aliases/duplicate keys, ограничивает raw/canonical размер1MiB и128 ports/parameters, schema отклоняет duplicate port names и nonfinite defaults. RegisterPluginManifest admin-only, identity/version должны совпадать с manifest. Версия immutable: semantic повтор идемпотентен, изменение ALREADY_EXISTS. Concurrent insert rollback/read/compare не перезаписывает победившую версию; DB-only callback проходит generated settled transaction.

SQLite2 registry tests прошли; real PostgreSQL12 concurrent registrations из двух service instances дали success и одну строку. Existing lease/placement/launch/fencing/Start gates также прошли, PG container удалён. Full runner17/17 passed (codegen215, orchestrator93). Это необходимая граница immutable permissions для будущей grants policy, не сама credential issuance и не завершённый runtime deployment.

Registry audit выявил category schema/PG mismatch (65+ chars), дополнительно воспроизведён escaped lone-surrogate encoding failure. Общая schema ограничивает category64, запрещает NUL и invalidUTF8 в category/description. Добавлены SQLite и realPG negatives; отказ происходит до DB flush с INVALID_ARGUMENT. До UTF8 regeneration новый regression воспроизвёл UnicodeEncodeError; после regen выполняется final gate. Audit подтвердил fixes по source.

Final post-UTF8-regeneration gate: full runner17/17 passed (codegen215, orchestrator93); real PostgreSQL concurrent registration и oversized/NUL/surrogate negatives exit0, temporary container удалён.

## Committed assignment authorization policy

src.engine.grants.assignment_policy строит capabilities только после проверки lease/fence, owner из Execution, exact typed committed node, active node projection, PREPARED attempt execution/node/fence/daemon/role и active immutable manifest identity. Literal file_id grant ограничен сохранённым node.parameters.file_id при storage permission; prompt grant ограничен node.prompt_id при llm permission. Live backend ownership checks остаются обязательными. Policy возвращает copied committed parameters/inputs, а wrapper сверяет initial_inputs и коммитит DB lock до вызова trusted provision callback.

Audit выявил coercion numeric dict keys через json.dumps. Заменено generated json_data.same_json_data: exact builtin types, UTF8 str keys, finite JSON-only values, no tuple/cycles. После сравнения используется saved node вместо caller object. Tests проверяют valid savedowner/file/prompt и отказ forged params/prompt/plugin/bool-int/fence/daemon/inputs/inactiveversion до provision. Focused2 passed; предыдущий full17/17 passed (codegen215, orchestrator95) до последнего codegen helper move; final gate выполняется. Audit подтвердил fix. Provision token/certificate issuance, safe duplicate-contender revocation и default resolver integration всё ещё открыты.

Final grants policy gate после codegen move: full17/17 passed, codegen215/orchestrator95.

## Encrypted user credential persistence

Auth Authenticate возвращает исходную access_expires_at из той же session join, generated VerifiedPrincipal сохраняет expiry. Orchestrator opt-in ExecutionCredentials (injected или LECTIFY_EXECUTION_CREDENTIAL_KEY из внешнего secret store) шифрует verified delegated access token generated CredentialCipher/Fernet. Authenticated payload включает execution/owner/originalexpiry; plaintext не пишется в DB. Start сохраняет Execution/Dispatch/Nodes/Credential атомарно, idempotent repeat не меняет ciphertext. RuntimeStreamDispatcher требует configured credential store при Start; без key отказ fail-closed. Default placeholder dispatcher по-прежнему не production runtime.

Load проверяет актуальный lease, execution owner и authenticated payload expiry; assignment_grants может загрузить credential только в trusted provision policy. Срок сессии не продлевается: исходные access tokens сейчас900sec; Refresh/Logout/password change продолжают отзывать их через live backend Authenticate на каждой операции. Общий ключ должен быть одинаковым у реплик и храниться вне DB; key rotation/long-running delegation policy не реализованы. dispatch_pending удаляет истёкшие/terminal ciphertext rows. Это не отзыв original user session и не scoped delegation token.

Migration0004_execution_credentials проверена downgrade/upgrade на ephemeral PostgreSQL. PG two-replica concurrent Start сохранил одну ciphertext row, другая replica расшифровала её под active lease, cancellation/purge удалили row. Unit binding/tamper/expiry/idempotence/required-key2 passed, Auth5 passed, full17/17 passed (codegen215, orchestrator97). Независимый audit confirmed crypto/lifecycle defects не нашёл. Production grants envelope/certificate issuer/report capability lifecycle/default runtime wiring остаются открытыми.

## Once-per-lease reporting credentials

ExecutionCredentials.report_capability под active execution lease lock выдаёт одну reporting capability и зашифрованную delivery copy на fence. Повторные grants/реплики получают тот же plaintext после decrypt и сверки hash/fence; generic Cipher authenticated purpose(user/report)+generation предотвращает подстановку user/report и cross-fence ciphertext. Legacy user payload без новых полей читается как user/generation0. Новый claim очищает hash/fence/cipher; явная manual rotation инвалидирует delivery copy. Report capability принадлежит execution lease, node grant contexts её заимствуют и не должны отзывать при своём teardown.

Audit выявил expiry-use gap: decrypt/newgrant expiry не ограничивала уже выданный plaintext report token. ReportNodeEvent теперь под lease guard проверяет active ExecutionCredential expiry по DB clock до replay/write. Persisted credentials_required защищает от fallback в legacy после manual rotation или purge. Migration0005 добавляет flag/cipher и backfill flag=true для existing encrypted credentials; новые encrypted Start устанавливают flag атомарно, успешный load также повышает его. Legacy reports без encrypted credential сохраняют прежний lease-bound режим. Purge удаляет orphan report ciphertext/hash/fence.

Tests: samecap across grants/replicas, purpose/fence tamper, newclaim rotation/stalefence denial, originalexpiry, postcancelpurge; expired report denied BEFORE purge при активном lease, включая manualrotation. Real PostgreSQL12 simultaneous report grants дали один token, expired report отклонён; migrations4/5 downgrade/upgrade с seeded pre5 row подтвердили backfill, cleanupPG завершён.

Предыдущий fullgate16/17 упал на process-control fixture;20 isolated repetitions прошли, точная причина старого падения не воспроизведена. В fixture обнаружено окно exists-before-write JSON snapshot; child теперь публикует complete snapshot через atomic tmp.replace. Final fullgate17/17 passed (codegen215, orchestrator100). Независимый audit подтвердил TTL/backfill/fixture fixes без новых confirmed defects. Full production envelope/certificates/default dispatcher и прочая monolith parity остаются незавершёнными.
