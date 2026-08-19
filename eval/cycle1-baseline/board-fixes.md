# Цикл 1 — правки совета (2026-08-19)

Диагноз совета (все пятеро, подтверждено проверкой):
- Baseline измерял галлюцинацию Whisper: все 8 сессий — «Продолжение следует»
  в цикле (275-366 повторов), ~39% базы с той же сигнатурой. Anti-hallucination
  флаги whisper включены и не спасают. Первопричина тихого микрофона — TCC.
- structured output пропускает мусорные имена ключей ("participants:[") —
  реальный контент теряется молча (judge=1).
- Таблица commitments + insert/get_open/counts живут в database.py с февраля,
  не вызываются ниоткуда.
- _ONE_SIDED_NOTICE гасит собственные обещания SPEAKER_ME — топливо комбайна.

Правки (порядок исполнения):
- [ ] B. Схема: required core-ключи + пост-парс whitelist по шаблону
- [ ] A. _is_degenerate() до Ollama → флаг transcript_quality, без LLM-вызова
- [ ] D. Односторонний промпт: слова SPEAKER_ME — законный материал
- [ ] E. Commitments: поле в default-шаблоне, аттестация в _finalize,
      insert_commitments в daemon, direction outgoing/incoming
- [ ] C. Эвал: pick_sessions фильтрует вырожденные, aggregate.degenerate_sessions,
      перепрогон на реальных звонках (cycle1-after)
- [ ] F. Swift: mic-only баннер с кнопкой x-apple.systempreferences Screen Capture
- [ ] G. Swift: пользовательский текст Action Items → Commitments

Отложено на следующие циклы: golden set с эталонным recall (Карпати),
citation-верификация [MM:SS] кодом (Карпати), brief.py по человеку (Черный),
группировка обязательств по людям в UI (Айв).
