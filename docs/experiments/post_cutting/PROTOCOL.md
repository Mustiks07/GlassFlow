# Предварительный протокол сравнений

База5648852. Зафиксирован до первого запуска кандидатов; независимый экзамен reviewer не читается.
Синтетические семейства нужны для переноса/границ и не предсказывают закрытый балл.

## N03

Нормальный endpoint кандидатов и его порядок сохраняются. Совет включается только при независимой
проверке полного совместного witness: текущие назначения заявки + все известные нераспределенные
детали одного заказа infeasible в точной ограниченной модели, альтернатива feasible и проходит C2 validator.
Timeout/UNKNOWN не означает impossible. Контроль: две формы склада с ограниченной большой деталью,
quantity1/2, два экземпляра большой детали, занятый кусок, измененные ID/порядок, достаточное совместное
место на выбранном куске. Требования:0 ложных объяснений/invalid; нормальный fallback при лимите;
latency p95<1с на машине разработки отдельно от эталонной машины. Глобальный порядок не продвигается
по одному удачному примеру; root может показать проверенный совет отдельно.

## N11/N12/N14

До запуска фиксируются JSON inputs двух семейств(dense64/18, mixed48/18), seeds7,19,41,
одинаковый solver budget20с, workers1, pool cap10000, minimum free5, memory ceiling1GiB,
все24 trials (6 baseline и18 парных candidate сравнений) с одинаковыми источниками.
Порядок4 вариантов циклически сдвигается по family/seed для контроля фазовой нагрузки.
Каждый trial — свежий процесс.
Windows PeakWorkingSet/Linux /proc VmHWM включает native память; не tracemalloc.
Все результаты, в том числе ухудшения, сохраняются. Baseline текущий CuttingSolver.

N11 кандидат: большая/редкая непокрытая деталь направляет destroy/repair, каждый четвертый ход
остается исходным случайным LNS. N12 кандидат: после area/full orders выбирается меньше фактических
мест выдачи из найденных вариантов. N14 кандидат: порядок создания pool по компонентам eligibility,
но master остается ОБЩИМ с ограничением свободных originals; компоненты не объединяются наивно.

Promotion N11/N14: invalid/missing0; ни одного area regression; median gain>=0,1п.п.; улучшение
минимум в2/3 seeds каждого семейства; p95 первого valid не хуже baseline+100мс;
native peak не более baseline+15% и не более1GiB. N12: все area/full orders не хуже baseline,
места не увеличиваются ни в одном trial и уменьшаются минимум в половине, те же guards.
При непрохождении — явный no-promotion, сильный baseline не заменяется. Временный optimum pool
не называется глобальным. Полная граница памяти/времени и машины записывается в отчете.

N13 включается только как read-only точная геометрическая подсказка: edge5/gap3 и tempered±2
не меняются; никакой вероятности брака/технологической гарантии. Исправление расхода N16 вне этой миссии.


## V2 freeze after priority0 defect, before new trials

Initial9s pilot at a400c2d is preserved unedited as pilot-9s-partial.json (11/24 observed).
It exposed an existing solver defect: no initial complete incumbent respecting requested minimum free;
not a candidate success/failure. Corrected runtime baseline a079a28 strictly checks minimum5, availability
and locks. Old pilot is not silently replaced; v2 reuses the same six mathematical inputs (hashes unchanged),
so this is a declared regression comparison, not an independent hidden exam.

All24 v2 trials use20s/1GiB and the same ONE OS CPU affinity (highest currently permitted core),
CP-SAT workers1 and OMP/BLAS/MKL threads1. CPU allocation applies to native libraries as well.
Memory is OS native process peak working set/RSS; parent samples every20ms and terminates if above1GiB.
Deadline is common20s; only complete independently validated incumbents emitted at elapsed<=20s count;
late solver return does not gain extra search time. Startup imports before solver budget are separate.
Results report both termination and actual solver reason if received. No global-optimum claim.
Existing promotion thresholds above are unchanged. Prototypes stay disabled in production even after study;
root/reviewer controls any future promotion. Every source/protocol SHA and every planned trial is saved.
