# Бэклог совета директоров — 2026-08-19

Источники: 5 директоров (Мурати, Суцкевер, Черный, Карпати, Айв) + 2 ресерча
(облачные митинг-ассистенты; local-first инструменты и macOS-паттерны 2026).
Исполняется автономным лупом: TDD, коммит после каждого пункта, без push.
Ручные шаги владельца луп не выполняет — ведёт списком внизу.

## Кодовые пункты (порядок исполнения)

- [x] 1. Детектор: пережить SystemError/PermissionError из psutil.process_iter
  (падения демона 10.06, 11.07, 13.07). Коммит e8cc78f.
- [x] 2. [475ed7a] Гигиена данных: колонка `source` в calls (migration), пометить 37
  синтетических строк (`import_seed`) — это строки без папки в recordings/
  (Zoom 13, Meet 11, Telegram 8, FaceTime 5); НЕ удалять. Пересчитать и
  поправить цифры в landing.html; README: свести три расходящихся числа
  тестов к реальному (355). Проверка: `select count(*) from calls where
  source='live'` совпадает с числом папок в recordings/.
- [x] 3. coverage → пользователю: coverage уже лежал в summary_json — миграция
  не потребовалась; типизирован в CallSummary + бейджи (коммит выше).
  Исходная формулировка: сохранять coverage (mic_only/full) в БД,
  прокинуть в Call.swift, бейдж «Собеседник не записан» в CallRowView +
  CallDetailView + явный placeholder в AudioPlayerView вместо молча
  пропавшей дорожки System Audio. Проверка: открыть звонок после 10.06 и
  увидеть статус без чтения лога.
- [x] 4. [884ce9c] Эскалация тихой деградации: счётчик подряд идущих mic_only-звонков в
  status.json; DaemonStatusCard показывает warning-состояние «пишется только
  твой микрофон, N звонков подряд» вместо часового throttled-notify.
- [x] 5. Canary по платформам: недельный счётчик звонков по приложениям против
  исторической базовой линии; ноль при ненулевой базе → notify + флаг в
  status.json. Ловит повтор «тихой смерти Meet» автоматически.
- [x] 6. [7e9792d] Consent-диалог: убран default button «Записать» (Enter не
  соглашается рефлекторно) — рекомендация Айва и Мурати.
- [x] 7. [60080f4] WelcomeView: переписать тексты в честном регистре лендинга («records
  transparently» противоречит consent-модели) + строка живой проверки
  Screen Recording права.
- [x] 8. [45e8d36] Ollama structured output (format: json schema) как основной путь;
  _try_repair_json/_mechanical_merge остаются fallback'ом.
- [x] 9. Валидация owner в action items: сверка с participants вместо substring
  по всему транскрипту («Максим» ≠ «максимум»).
- [ ] 10. Detection v2 (сначала design doc): Swift-хелпер `call-signal` —
  CoreAudio per-process API (kAudioHardwarePropertyProcessObjectList +
  kAudioProcessPropertyIsRunningInput, push-листенеры; на Tahoe 26 —
  подписка на общий IsRunning + ручная перечитка IsRunningInput) + камера
  (kCMIODevicePropertyDeviceIsRunningSomewhere) как приоритет-0 + WebRTC
  power assertion («WebRTC has active PeerConnections» у Chrome) для
  браузерных звонков. Python-детектор берёт этот сигнал основным,
  UDP-эвристики — fallback. Consent-диалог остаётся гейтом. Sticky
  keep-alive на mute. Закрывает Meet и лечит детекцию всех платформ одним
  принципом.
- [ ] 11. audio-capture как .app-бандл с CFBundleIdentifier (standalone-бинарь
  не может стабильно держать Screen Recording TCC) — подготовка кода;
  подпись сертификатом — ручной шаг.

## Ручные шаги владельца

- [ ] Apple Development сертификат ($99/год) → стабильная подпись, право
  перестанет слетать при пересборках. setup.sh уже умеет подхватывать.
- [ ] System Settings → Privacy & Security → Screen & System Audio Recording →
  включить audio-capture → `bash restart-daemon.sh`.
- [ ] Решение: consent второй стороны. Совет единогласно считает блокером
  публичности; Granola и Otter сейчас под коллективными исками ровно за
  «тихий» захват. Варианты: видимый локальный индикатор записи /
  TTS-объявление в начале / письменная позиция «только personal use».
- [ ] Живая проверка Detection v2 на реальном звонке Meet и Zoom.

## Вопросы совета владельцу (топ-3)

1. Consent второй стороны — какую механику выбираем? (все пятеро)
2. Личный инструмент или публичный продукт? Определяет приоритет Settings UI,
   сертификата, юридики. (Мурати, Черный)
3. Судьба 37 синтетических строк: луп пометит и исключит из витрины;
   удалять или нет — решение владельца. (Черный)

## Ключевые факты ресерча (для контекста решений)

- Botless-захват стал мейнстримом (Otter 10.25, Fireflies 11.25, Fathom 04.26,
  Circleback, Granola) — архитектура продукта подтверждена рынком.
- Table stakes 2026: календарный автоджойн, диаризация с именами, шаблоны
  саммари, action items с владельцами, cross-meeting память/чат, MCP-сервер.
- Дифференциаторы: voice fingerprinting между встречами (Circleback),
  hard-stop consent (tl;dv), локальная кросс-встречная память — ниша пуста.
- Live-коучинг и emotion-скоринг — сознательно не строить (юридические мины,
  противоречат privacy-first; Read.ai банят университеты, EU AI Act).
- ScreenCaptureKit для system audio — правильный выбор (устойчив к HFP и
  перемаршрутизации), CATap нужен только для real-time задач.
- AVAudioEngine нельзя перенаправить на конкретное устройство — пин Shure
  требует AudioDeviceCreateIOProcIDWithBlock напрямую.
- Ollama 0.19+ имеет MLX-бэкенд (32ГБ+) — отдельная миграция на mlx-lm
  теряет смысл.
- Дальний горизонт (после бэклога): локальная кросс-встречная память
  (векторный индекс на устройстве), MCP-сервер поверх calls.db, voice
  fingerprinting локально.
