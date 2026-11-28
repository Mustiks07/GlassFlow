# Визуальные материалы защиты (C1-09)

| Файл | Назначение | Статус |
|---|---|---|
| `GlassFlow_pitch.pptx` | Редактируемая дека, 6 слайдов 16:9 | READY FOR INTEGRATION — есть `[ФИНАЛЬНЫЙ RUN]` |
| `GlassFlow_pitch.pdf` | Резервная копия (LibreOffice из PPTX) | то же |
| `build_deck.py` | Генератор деки из реальных кадров `tests/e2e/evidence/real` | — |
| `PITCH_SCRIPT.md` | Сценарий 3:00, live 25 + 5 с, ответы на вопросы, чек-лист T60/T65 | репетиция NOT RUN |
| `TIME_MEASUREMENT_PLAN.md` | Протокол 10 заданий вручную vs GlassFlow для экономики | измерения NOT RUN |

Пересборка после финального run: заменить плейсхолдеры в `build_deck.py` (или прямо в PPTX), затем

```bash
python3 docs/presentation/build_deck.py
```

```bash
soffice --headless --convert-to pdf --outdir docs/presentation docs/presentation/GlassFlow_pitch.pptx
```

Кадры на слайдах — только реальная сборка (сейчас: GPT Pro 6512eae + Claude 3 4616645, открытый пакет). Кадры fixture-сборки
(`tests/e2e/evidence/fixture`, фиолетовый баннер) — только доказательства UI-тестов, не материалы для жюри.
