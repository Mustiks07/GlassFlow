"""Builds the editable pitch deck (PPTX, 6 slides, 16:9) from real-build screenshots.

Usage (repo root):
    python3 docs/presentation/build_deck.py          # → docs/presentation/GlassFlow_pitch.pptx
    soffice --headless --convert-to pdf --outdir docs/presentation docs/presentation/GlassFlow_pitch.pptx

Rules (mission C1-09): numbers that must come from the final run are amber
«[ФИНАЛЬНЫЙ RUN: …]» placeholders until GPT Pro publishes one run's evidence. Research
values (58,9523 %, R006, 1 017 742,15 ₸) are NOT shown as product results. Screenshots are
from the real backend E2E (tests/e2e/evidence/real), never from the fixture build.
"""
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Pt

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / 'tests' / 'e2e' / 'evidence' / 'real'
OUT = Path(__file__).resolve().parent / 'GlassFlow_pitch.pptx'

BRAND = RGBColor(0x12, 0x3D, 0x39)
BRAND2 = RGBColor(0x1D, 0x5A, 0x50)
TEXT = RGBColor(0x17, 0x30, 0x2C)
MUTED = RGBColor(0x55, 0x66, 0x5F)
SOFT = RGBColor(0xE3, 0xEE, 0xDF)
AMBER = RGBColor(0x8A, 0x5A, 0x00)
AMBER_BG = RGBColor(0xFD, 0xF3, 0xDC)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
FONT = 'Inter'

W, H = Emu(12192000), Emu(6858000)  # 13.333 × 7.5 in
IN = 914400


def box(slide, x, y, w, h, fill=None, line=None):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, int(x * IN), int(y * IN), int(w * IN), int(h * IN))
    if fill is None:
        shape.fill.background()
    else:
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
    shape.shadow.inherit = False
    return shape


def text(slide, x, y, w, h, runs, size=18, color=TEXT, bold=False, align=PP_ALIGN.LEFT, spacing=1.1):
    """runs: str or list of paragraphs; a paragraph is str or list of (text, overrides)."""
    tb = slide.shapes.add_textbox(int(x * IN), int(y * IN), int(w * IN), int(h * IN))
    frame = tb.text_frame
    frame.word_wrap = True
    paragraphs = runs if isinstance(runs, list) else [runs]
    for index, para in enumerate(paragraphs):
        p = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        parts = para if isinstance(para, list) else [(para, {})]
        for part, opts in parts:
            r = p.add_run()
            r.text = part
            r.font.name = FONT
            r.font.size = Pt(opts.get('size', size))
            r.font.bold = opts.get('bold', bold)
            r.font.color.rgb = opts.get('color', color)
    return tb


def placeholder(slide, x, y, w, h, label, size=14):
    shape = box(slide, x, y, w, h, fill=AMBER_BG, line=AMBER)
    frame = shape.text_frame
    frame.word_wrap = True
    p = frame.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = f'[ФИНАЛЬНЫЙ RUN: {label}]'
    r.font.name = FONT
    r.font.size = Pt(size)
    r.font.bold = True
    r.font.color.rgb = AMBER
    return shape


def header(slide, number, eyebrow, title):
    box(slide, 0, 0, 0.18, 7.5, fill=BRAND)
    text(slide, 0.55, 0.35, 9.5, 0.35, eyebrow.upper(), size=11, color=MUTED, bold=True)
    text(slide, 0.55, 0.65, 12.2, 1.0, title, size=30, color=TEXT, bold=True, spacing=1.0)
    text(slide, 12.3, 7.0, 0.8, 0.3, f'{number}/6', size=10, color=MUTED, align=PP_ALIGN.RIGHT)
    text(slide, 0.55, 7.0, 6, 0.3, 'GlassFlow · рабочее место менеджера KSM', size=10, color=MUTED)


def screenshot(slide, name, x, y, w, caption):
    path = SHOTS / name
    pic = slide.shapes.add_picture(str(path), int(x * IN), int(y * IN), width=int(w * IN))
    pic.line.color.rgb = RGBColor(0xC7, 0xD0, 0xC3)
    text(slide, x, y + pic.height / IN + 0.05, w, 0.3, caption, size=10, color=MUTED)
    return pic


def notes(slide, body):
    slide.notes_slide.notes_text_frame.text = body


def build():
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    blank = prs.slide_layouts[6]

    # 1 ── problem → one workplace
    s = prs.slides.add_slide(blank)
    box(s, 0, 0, 13.333, 7.5, fill=BRAND)
    text(s, 0.8, 0.9, 11.5, 0.5, 'КЕЙС KSM «СТЕКЛО → ДЕНЬГИ → КЛИЕНТ»', size=13, color=RGBColor(0xA9, 0xC7, 0xBC), bold=True)
    text(s, 0.8, 1.4, 11.8, 1.8, 'GlassFlow: от запроса клиента до проверенной цены, свободного куска и следующего действия — в одном окне', size=36, color=WHITE, bold=True, spacing=1.0)
    items = [
        ('Остатки', 'лежат на стеллажах: раскрой, место хранения и пять карточек на продажу'),
        ('Цена', 'считается по базе знаний, с источником и без выдуманных чисел'),
        ('Клиенты', '25 заявок для повторного контакта и локальное напоминание'),
        ('Руководитель', 'M1–M5: семь показателей со знаменателями и исходными строками'),
    ]
    for i, (head, body) in enumerate(items):
        x = 0.8 + i * 3.0
        box(s, x, 4.1, 2.8, 2.2, fill=RGBColor(0x1B, 0x4C, 0x46))
        text(s, x + 0.2, 4.25, 2.4, 0.5, head, size=20, color=WHITE, bold=True)
        text(s, x + 0.2, 4.8, 2.4, 1.4, body, size=13, color=RGBColor(0xC5, 0xD8, 0xCF))
    text(s, 0.8, 6.75, 11, 0.4, 'Локальное приложение для Windows · бесплатный Gemini по умолчанию · данные кейса учебные', size=12, color=RGBColor(0xA9, 0xC7, 0xBC))
    notes(s, '0:00–0:25. Проблема кейса и обещание продукта. Одно рабочее место вместо таблиц, калькулятора и мессенджера. Не называть результаты до слайда 3.')

    # 2 ── live route (25 s)
    s = prs.slides.add_slide(blank)
    header(s, 2, 'Живой показ · 25 секунд', 'Запрос → проверенная цена → доступный кусок → действие')
    steps = [
        ('1', 'Запрос', '«стекло 6 мм 450×370, евро-кромка по кругу» — свободный текст или форма; см/м пересчитываются с показом'),
        ('2', 'Цена', 'Сервер считает по KB: позиции с формулой и источником, итог — предварительный, подтверждает менеджер'),
        ('3', 'Остаток', 'Свободный целый кусок: размер, стеллаж/ячейка, схема с краем 5 мм; показ не резервирует'),
        ('4', 'Действие', 'Явное подтверждение с проверкой версии; конфликт — честный 409. CRM-задача: адресат ≠ заказчик'),
    ]
    for i, (num, head, body) in enumerate(steps):
        y = 1.85 + i * 1.18
        box(s, 0.55, y, 0.6, 0.6, fill=BRAND2)
        text(s, 0.55, y + 0.08, 0.6, 0.5, num, size=20, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
        text(s, 1.35, y - 0.02, 4.8, 0.4, head, size=18, bold=True)
        text(s, 1.35, y + 0.36, 4.9, 0.8, body, size=12, color=MUTED)
    placeholder(s, 6.6, 1.85, 6.2, 3.3, 'кадр рабочего места с расчетом и схемой куска из финальной сборки (сейчас C3/C2 не интегрированы — real-тест T28 FAIL)', size=14)
    text(s, 6.6, 5.3, 6.2, 1.2, [
        [('Пример из правил KB (ТЗ §40): ', {'bold': True}), ('450×370 clear-6 + кромка = 1 988,00 ₸; 451×370 = 1 991,76 ₸.', {})],
        [('Кусок для показа выбирается на финальном плане ', {}), ('[ФИНАЛЬНЫЙ RUN: ID и место]', {'color': AMBER, 'bold': True}), (' — R006 из исследования не обещаем.', {})],
    ], size=12, color=TEXT)
    notes(s, '0:25–0:50 LIVE (≤25 с). Режим «без перестройки» обозначен явно. Если сеть недоступна — показать, что расчет работает локально, а диалог помечен ограниченным. Изменение 450→451 — на вопросах.')

    # 3 ── cutting results
    s = prs.slides.add_slide(blank)
    header(s, 3, 'Раскрой · проверено официальным validate.py', 'Максимум площади из остатков, ноль ошибок, пять свободных кусков')
    metrics = [
        ('Покрытие площади', 'coverage из validator'),
        ('Площадь из остатков', 'м² и деталей'),
        ('Оценка материала', '₸ по ставкам materials.csv — не прибыль'),
        ('Ошибки / пропуски', 'invalid = 0, missing = 0'),
    ]
    for i, (head, label) in enumerate(metrics):
        x = 0.55 + i * 3.1
        box(s, x, 1.9, 2.9, 1.9, fill=SOFT)
        text(s, x + 0.15, 2.0, 2.6, 0.4, head, size=14, color=MUTED, bold=True)
        placeholder(s, x + 0.15, 2.5, 2.6, 1.1, label, size=12)
    text(s, 0.55, 4.15, 12.2, 2.4, [
        [('Как получено: ', {'bold': True}), ('допустимость по точным правилам → первый план за секунды → пул шаблонов → MILP (HiGHS) → улучшение CP-SAT → независимая проверка и официальный validate.py.', {})],
        [('Честность: ', {'bold': True}), ('«оптимум в пуле» не называем глобальным оптимумом; остановка по лимиту = «поиск ограничен»; NEW ≠ невозможность.', {})],
        [('Пять карточек: ', {'bold': True}), ('пять полностью свободных исходных кусков выбранного плана; если ограничение стоит площади — показываем точную разницу ', {}), ('[ФИНАЛЬНЫЙ RUN: Δ площади]', {'color': AMBER, 'bold': True}), ('.', {})],
    ], size=14)
    notes(s, '0:50–1:20. Только числа финального run (C2 solver metrics + Pro validator). Исследовательские 58,9523 % и сертификат 62,78 % — только на вопросах и только с подписью «открытый набор, исследование».')

    # 4 ── clients and managers (M1–M5 live 5 s)
    s = prs.slides.add_slide(blank)
    header(s, 4, 'Клиенты и руководитель · живой экран M1–M5 · 5 секунд', '25 заявок для повторного контакта и семь показателей с исходными строками')
    screenshot(s, 'M1-M5-table.png', 0.55, 1.75, 7.6, 'Реальная сборка, открытый пакет организаторов: M1–M5, числитель/знаменатель у каждой доли')
    text(s, 8.45, 1.75, 4.4, 4.9, [
        [('25 строк в picks.csv, ', {'bold': True}), ('очередь группирует их по клиентам: на открытом наборе 25 заявок = 15 клиентов.', {})],
        [('Precision@25 = 80 % (20 из 25) ', {'bold': True}), ('— baseline на открытых метках; закрытый результат неизвестен до жюри.', {})],
        [('Метка = новое обращение за 60 дней, ', {'bold': True}), ('не покупка и не выручка.', {})],
        [('Напоминание локальное: ', {'bold': True}), ('адресат и предмет отдельно от заказчика; ничего не отправляется наружу.', {})],
        [('M1–M5: ', {'bold': True}), ('«нет данных» ≠ 0; время ответа — ожидание клиента, не трудозатраты; прайс и раскрой историю не меняют.', {})],
    ], size=13, spacing=1.15)
    notes(s, '1:20–1:50. LIVE 5 с: открыть «Менеджеры», нажать одну долю → исходные строки. Цифры на слайде — из реального backend на открытом наборе (tests/e2e/evidence/real).')

    # 5 ── buyers and cards
    s = prs.slides.add_slide(blank)
    header(s, 5, 'Покупатели и карточки', '50 проверенных организаций и пять карточек свободных кусков')
    for i, (value, label) in enumerate([('50', 'уникальных публичных организаций'), ('49', 'в Астане (нужно ≥ 30)'), ('9', 'категорий (нужно ≥ 5)')]):
        x = 0.55 + i * 2.55
        box(s, x, 1.85, 2.35, 1.6, fill=SOFT)
        text(s, x + 0.15, 1.9, 2.1, 0.8, value, size=40, color=BRAND, bold=True)
        text(s, x + 0.15, 2.7, 2.1, 0.7, label, size=11, color=MUTED, spacing=1.0)
    text(s, 0.55, 3.75, 7.5, 2.8, [
        [('Каждая запись проверена загрузкой страницы-источника: ', {'bold': True}), ('город и профиль найдены в тексте, есть фрагмент-подтверждение и дата (data/buyers/evidence.json).', {})],
        [('why — конкретное применение: ', {'bold': True}), ('зеркала у кресел барбершопа, стеклянные вставки фасадов, полки витрин. Прошлых заказов не придумываем.', {})],
        [('score — релевантность профиля, ', {'bold': True}), ('не вероятность покупки. Частных контактов и рассылок нет.', {})],
    ], size=13, spacing=1.15)
    placeholder(s, 8.35, 1.85, 4.45, 4.7, 'пять карточек: кусок, точный размер, материал, цена = площадь × ставка × 0,30–0,70, три покупателя', size=13)
    notes(s, '1:50–2:15. Реестр — факт этой ветки (C1-07). Карточки — из финального плана и реестра Pro; при изменении плана карточка устаревает и экспорт блокируется (проверено fixture-тестом T48).')

    # 6 ── economics and first pilot week
    s = prs.slides.add_slide(blank)
    header(s, 6, 'Экономика и первая неделя', 'Сколько это дает KSM и как проверить на реальных данных')
    placeholder(s, 0.55, 1.85, 6.0, 1.3, 'оценка замещенного материала в месяц по финальному плану и прирост к baseline (economics.pdf, Pro)', size=12)
    placeholder(s, 0.55, 3.3, 6.0, 1.3, 'измеренное активное время: медиана ручной vs GlassFlow по 10 заданиям', size=12)
    placeholder(s, 0.55, 4.75, 6.0, 1.3, 'внедрение, сервисы/мес, чистый эффект, срок окупаемости', size=12)
    days = [
        ('День 1', 'Сверить материалы, каталог, ставки, места и неизвестные соответствия'),
        ('День 2', 'Проверить геометрию и технологию с цехом; конкурсные правила сохраняются'),
        ('День 3', 'Реальные расчеты рядом с текущим процессом: точность и время'),
        ('День 4', 'Очередь повторных обращений под контролем менеджера, без автоотправки'),
        ('День 5', 'Расходы, удобство, данные: решение о пилоте, бюджете API и сервере'),
    ]
    for i, (day, body) in enumerate(days):
        y = 1.85 + i * 0.86
        box(s, 6.95, y, 1.15, 0.7, fill=BRAND2)
        text(s, 6.95, y + 0.17, 1.15, 0.4, day, size=13, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
        text(s, 8.25, y + 0.05, 4.6, 0.7, body, size=12)
    text(s, 0.55, 6.3, 12.2, 0.5, 'Оценка материала, выручка и прибыль не складываются; рост Precision@25 — не измеренная выручка от напоминаний.', size=11, color=MUTED)
    notes(s, '2:15–3:00. Числа экономики — только из economics.pdf Pro одного финального run. Закрыть: что просим у KSM на пилот (данные, 1 менеджер, 5 дней).')
    prs.save(OUT)
    return OUT


if __name__ == '__main__':
    print(build())
