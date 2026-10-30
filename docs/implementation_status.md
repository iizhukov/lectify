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
