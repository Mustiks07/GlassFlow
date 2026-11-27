from pathlib import Path
import csv, importlib.util, sys
sys.stdout.reconfigure(encoding='utf-8')
base=Path(__file__).resolve().parents[2]/'inputs/PACK_for_teams/2_assistant_crm'
out=Path(__file__).parent
# Hand-reviewed reference responses, for testing the scoring contract only.
# This is not an implemented assistant and does not demonstrate generalization.
answers=[
'Большой уголок рамочного фасада: 450 тг за штуку в розницу, 350 тг при заказе от 100 штук.',
'Монтаж компания не выполняет. Мы продаём стекло, зеркала, фурнитуру и профили.',
'Предварительно: 1,2 × 1,8 = 2,16 м²; 2,16 × 8 000 = 17 280 тг. Окончательную стоимость подтверждает менеджер.',
'Предварительно: 1 × 1,2 = 1,2 м²; 1,2 × 20 000 = 24 000 тг. Окончательную стоимость подтверждает менеджер.',
'Рифлёное прозрачное стекло 5 мм стоит 40 000 тг за м².',
'Целый лист рифлёного серого стекла 8 мм стоит 200 000 тг.',
'Оплата на сайте не принимается. Оплату согласует менеджер.',
'Цена фацета в базе не указана, её уточнит менеджер.',
'Силикон для зеркал ZUNXIN 997: 1 500 тг в розницу, 1 300 тг при заказе от 100 штук.',
'Полкодержатель 19 × 15 × 16 мм: 150 тг в розницу, 100 тг при заказе от 100 штук.',
'Цена этой модели в базе не указана, её рассчитывает менеджер.',
'Целый лист стекла бронза 8 мм стоит 90 000 тг.',
'Скидку не обещаю: условия согласует менеджер.',
'Цена пескоструя в базе не указана, её уточнит менеджер.',
'Прозрачное стекло 4 мм стоит 4 500 тг за м².',
'Целый лист зеркала 4 мм формата 2750 × 1605 стоит 24 000 тг.',
'Стекло серое стоит 10 000 тг за м².',
'Предварительно: 0,7 × 1,5 = 1,05 м²; 1,05 × 11 500 = 12 075 тг. Окончательную стоимость подтверждает менеджер.'
]
with (out/'reviewed_answers.csv').open('w',encoding='utf-8',newline='') as f:
 w=csv.writer(f);w.writerow(['id','answer']);w.writerows((f'Q{i:02d}',a) for i,a in enumerate(answers,1))
with (out/'reviewed_verdicts.csv').open('w',encoding='utf-8',newline='') as f:
 w=csv.writer(f);w.writerow(['id','verdict','correct']);w.writerows([(f'D{i:02d}','OK','') for i in range(1,6)]+[('D06','ERROR',10000),('D07','ERROR',10000),('D08','ERROR',400)])
spec=importlib.util.spec_from_file_location('sc',base/'selfcheck.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
mod.assistant(out/'reviewed_answers.csv',base/'questions_open_KEY.csv')
mod.dialogs(out/'reviewed_verdicts.csv',base/'dialogs_open_KEY.csv')
