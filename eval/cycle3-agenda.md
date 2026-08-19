# Повестка цикла 3 (заготовка)

Директива владельца (2026-08-19): эксперимент think:false — приоритет.
Наблюдение: на каждый чанк qwen3:14b тратит 2-2.5К знаков thinking;
для структурной JSON-экстракции глубокий CoT сомнителен, а времени стоит
до половины прогона. Протокол Черного: прогнать golden set с "think": false,
сравнить avg_seconds и judge_scores; просадка качества → откат.

Отложено с циклов 1-2 (кандидаты):
- scripts/brief.py — брифинг по человеку (Черный): get_calls_by_entity +
  get_open_commitments, markdown-вывод. Прямой шаг к комбайну.
- Swift: брифинг-заголовок при выборе человека (Айв): последний контакт +
  открытые обязательства incoming/outgoing; приложение начинает читать
  таблицу commitments.
- Chunk-прогресс в status.json + DaemonStatusCard («Summarizing part 2 of 4»).
- Citation-guardrail в _finalize (Карпати): дроп пунктов с несуществующими
  таймкодами; eval-метрика citation_grounded (overlap в окне ±45с).
- Golden-set recall: ручная разметка обещаний в 2-3 golden-звонках,
  метрика «сколько известных обещаний долетело до commitments».
