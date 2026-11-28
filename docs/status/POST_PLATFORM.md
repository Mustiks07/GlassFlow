# POST_PLATFORM — N02/N05/N06

База5648852, worktree GlassFlow-post-platform, branch codex/post-platform. Новые функции не переписывают R/T.

## DTO freeze N05/N06

`contracts/labor.py`: LaborStudyCreate/View/Export, MeasurementStart/Action/Finish/Attest, WorkflowQueue/Item.
Все mutations workspace, expected_version исследования и Idempotency-Key; отдельные методы finish и attest.
POST /labor-studies; GET list/get; POST /{study_id}/measurements start; POST /measurements/{id}/pause,resume,finish,attest;
GET /labor-studies/{id}/export. Цепочка событий с hashes, неизменяемое human attestation, elapsed/running/active отдельно.
Рестарт обнаруживается по process epoch, требует явного acknowledge+note; прошедший интервал не становится активным.
Парность task/input/operator/order проверяется, повтор одного способа не перезаписывает данные. U07 export требует10 полных
разных human-attested пар, отрицательное saved время сохраняется. Запись человека не является независимой проверкой истины.

GET /workflow/queue?dataset_id возвращает current canonical blockers, роль и одно следующее действие; read-only проекция.
Смена C2/C3 источника определяется capture/facts_hash, без записи новой бизнес-state или мутации заказа на GET.

Проверено `uv sync --locked --all-groups`; `uv run pytest tests/platform/test_post_labor_workflow.py -o addopts='' -q`:
4 PASS; `uv run ruff check` измененных файлов PASS. Данные времени в тестах synthetic, это не реальные10 замеров.
Реальные трудозамеры требуют человека и пока NOT RUN. Новых таблиц/миграций нет.

## Следующий шаг

N02 общий бюджет, accepted rows через parent coordinator, identity/attempt fencing и restart-safe deadline;
N15 parent audit timeline по запросу интегратора. Затем полный platform suite и handoff.
