"""Build an additive human semantic audit; never replace runtime buyer inputs."""

import copy
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/buyers/buyers.platform.csv"

# Individually read public page content, 2026-11-28. Paraphrases, not page copies.
# Identity/profile support is deliberately separate from verified procurement demand.
NOTES = {
    1: (
        "primary_profile",
        "Furniture group, bespoke/corporate/modular furniture; Tashenova19, Astana supported by group member addresses.",
        "Group brand, not one established procurement legal entity; glass furniture additionally appears in public directory, not a current purchase order.",
    ),
    2: (
        "primary_profile",
        "Astana Mebel Group; Astana Orlykol10B; own production of custom furniture and wardrobes.",
        "Main page does not establish the profile's stronger claims about glass showcases, mirror doors or glass shelving.",
    ),
    3: (
        "primary_profile",
        "DalaSK; custom cabinet/upholstered furniture and own production in Astana.",
        "Main page does not establish glass shelves, coffee tables or hallway mirrors as its actual products.",
    ),
    4: (
        "primary_profile",
        "IDEAL; Astana own furniture production; official content explicitly offers glass, mirror and combined facades.",
        "Direct open timed out; indexed official content was readable. Exact thickness, dimensions, volume and acceptance of remnants unknown.",
    ),
    5: (
        "primary_profile",
        "Clever Design; Astana residential/commercial interior design studio.",
        "A designer can specify materials; direct purchase authority or glass procurement is unproven.",
    ),
    6: (
        "primary_profile",
        "Biar; Astana Syganak54A; design and renovation of residential/commercial premises.",
        "Glass applications are project hypotheses; it is not demonstrated as a glass processor or current remnant buyer.",
    ),
    7: (
        "primary_profile",
        "DreamArt official catalogue is principally bespoke furniture, kitchens, wardrobes and retail equipment; official showroom address is in Astana.",
        "Recommend furniture-manufacturer category rather than unqualified design-studio classification; directory addresses differ, use official showroom. No proven purchase demand.",
    ),
    8: (
        "primary_profile",
        "Sensata Group; housing developer with named Astana projects.",
        "Construction demand does not prove suitability of small untempered remnants for glazing; safety/project specifications remain unknown.",
    ),
    9: (
        "primary_profile",
        "SG Holding official contact page identifies construction group and Astana AnetBaba11/3.",
        "Homepage timed out; official contact page supplies identity/city. No confirmed small-glass order.",
    ),
    10: (
        "primary_profile",
        "Alcon+ official site describes window/metal-plastic manufacture; official B2B brochure gives Astana Republic58/1.",
        "Do not confuse Alcon+ window firm with Alcon ophthalmology. Insulating-glass specification and minimum stock dimensions unproven.",
    ),
    11: (
        "hold_entity",
        "VEKA site supports a window-profile brand and Astana partner-sales page, not a named individual local fabricator.",
        "Cannot count an unspecified partner network as one verified independent local buyer. Identify one named operator and public local manufacturing address before eligibility.",
    ),
    12: (
        "primary_profile",
        "Megastroy official contacts show Astana Sembinov19/1; home/decor catalogue includes mirrors and official supplier-cooperation page.",
        "Retailer, not automatically glass processor; supplier acceptance and purchases of unprocessed remnants are unknown.",
    ),
    13: (
        "directory_profile",
        "kn.kz identifies AstanaStroyDom construction company, Astana AitekeBi9 and residential projects.",
        "Third-party company profile; identity supported, current procurement and technical suitability unverified.",
    ),
    14: (
        "directory_profile",
        "Sxodim names Khan Shatyr shopping centre, Astana Turan37 and links its official website.",
        "Facility/tenants are not one demonstrated glass purchaser; procurement operator and intended fit-out unknown.",
    ),
    15: (
        "directory_profile",
        "Sxodim identifies Keruen shopping centre, Astana Dostyk9.",
        "Centre versus tenant purchase authority unknown; small-glass use is a fit-out hypothesis.",
    ),
    16: (
        "primary_profile",
        "Asia Park official site gives Astana KabanbayBatyr21; operator REM.KZ and shopping/entertainment profile.",
        "Explicit facility identity but no glass-remnant procurement requirement; tenants may purchase independently.",
    ),
    17: (
        "directory_profile",
        "Sxodim identifies MEGA Silk Way shopping centre, Astana KabanbayBatyr62.",
        "Centre and its tenants must not be treated as confirmed common purchaser; specification and demand unknown.",
    ),
    18: (
        "primary_profile",
        "Abu Dhabi Plaza official site identifies Astana multifunctional offices, mall, apartments and hotel.",
        "Name is a complex, not a single established buyer; building safety glazing cannot be assumed from available remnant thickness.",
    ),
    19: (
        "directory_profile",
        "Talan Towers public profile identifies offices, EMPORIUM retail and Ritz-Carlton hotel, Astana Dostyk16.",
        "Shared complex with B38; not necessarily duplicate but independent purchasing operators are unproven. Keep shared-complex flag.",
    ),
    20: (
        "directory_profile",
        "Sxodim identifies Saryarqa shopping centre, Astana Turan24.",
        "Public venue listing does not establish current glass demand or tenant/centre buying authority.",
    ),
    21: (
        "directory_profile",
        "Sxodim identifies Astana Mall shopping centre, Astana Tauelsizdik34.",
        "2021 publication; present operating status and procurement requirements need fresh operator confirmation.",
    ),
    22: (
        "directory_profile",
        "Sxodim identifies KeruenCity shopping centre, Astana Korgalzhyn1.",
        "Separate named centre from B15; common brand/ownership or shared purchasing not resolved.",
    ),
    23: (
        "directory_profile",
        "Sxodim identifies Arujan shopping centre, Astana IlyasZhansugurov8k1.",
        "2021 publication; current operation and exact fit-out/glass requirements unverified.",
    ),
    24: (
        "directory_profile",
        "Sxodim identifies Green Mall shopping centre, Astana Syganak17P, commercial/food-hall spaces.",
        "Shares address complex with B41; distinct venue names do not prove independent purchasing operators.",
    ),
    25: (
        "primary_profile",
        "Qazaq Gourmet official restaurant site gives Astana MangilikEl29 and Kazakh dining profile.",
        "Decorative glass/mirror use is an engineering proposal, not sourced demand.",
    ),
    26: (
        "directory_profile",
        "Sxodim identifies Navat restaurant, Astana Dostyk13.",
        "Public dining profile, no exact dimensions, glass spec or procurement demand.",
    ),
    27: (
        "directory_profile",
        "Coffee Boom public profile establishes an Astana coffee-shop network and links its official site.",
        "A chain counted once; no individually identified procurement operator or confirmed small-glass demand.",
    ),
    28: (
        "directory_profile",
        "Sxodim identifies Nudu noodle restaurant, Dostyk16B on the Astana page.",
        "City is supported by page context/address; primary site link alone not independently accepted as proof. Glass application remains hypothesis.",
    ),
    29: (
        "directory_profile",
        "Starbucks public profile lists named Astana branches and national website.",
        "Brand counted once; franchise procurement, approved materials and supplier policy unknown.",
    ),
    30: (
        "directory_profile",
        "Sxodim identifies MANNA restaurant, Astana MangilikEl47, dining/VIP areas.",
        "2021 publication and panoramic windows are not evidence of current remnant demand or suitable safety glazing.",
    ),
    31: (
        "directory_profile",
        "Line Brew Reserve public profile gives Astana KadyrgaliZhalayiri4 and explicitly describes decorative mirrors in its interior.",
        "Existing mirrors establish an application precedent, not replacement need, new purchase or proposed dimensions.",
    ),
    32: (
        "directory_profile",
        "Sxodim identifies Shafran restaurant, Astana KereyZhanibek12B.",
        "2021 publication; identity/profile only, current procurement and intended glass application unverified.",
    ),
    33: (
        "directory_profile",
        "Gastro-Ploshchad Centre public profile gives Astana Dostyk16P and multi-corner food hall.",
        "Food hall and independent corners have unresolved procurement identity; no confirmed remnant demand.",
    ),
    34: (
        "directory_profile",
        "Marrone Rosso public profile gives Astana Republic10 and several city coffee shops.",
        "Chain is one lead, exact buying operator/approved interior material unknown.",
    ),
    35: (
        "primary_profile",
        "Bahandi official site identifies burger/fast-food network with Astana listed among service cities.",
        "City presence supported, not one named branch procurement contact or glass requirement.",
    ),
    36: (
        "directory_profile",
        "La Bottega public profile identifies Italian restaurant in Astana Keruen, Dostyk9.",
        "Tenant of B15; may have separate procurement, not established. Existing furniture/decor does not prove glass demand.",
    ),
    37: (
        "primary_profile",
        "OldBoy official Astana page lists barber branches at Amman2 and Kunayev10.",
        "Salon category supported; mirrors are plausible professional equipment, but replacements/dimensions/purchase authority unknown.",
    ),
    38: (
        "primary_profile",
        "Official Marriott/Ritz-Carlton page establishes Astana hotel, rooms, spa and meetings.",
        "Shares Talan Towers complex with B19; hotel may be separate operator but independent procurement not confirmed. Hotel safety specs unknown.",
    ),
    39: (
        "primary_profile",
        "Official Accor hotel page identifies Rixos President Astana, Kunayev7, hotel/spa/restaurants.",
        "No confirmed glass order or thickness/dimensions. Correct official Accor source resolves the former inaccessible URL.",
    ),
    40: (
        "primary_profile",
        "World Class official site identifies Astana fitness club, gym/group training/pool/spa.",
        "Training mirrors are plausible but no actual requirement for remnants or proposed dimensions is published.",
    ),
    41: (
        "directory_profile",
        "Invictus public profile identifies fitness club in Astana Syganak17P.",
        "Shares Green Mall address complex with B24; procurement independence and mirror specification unknown.",
    ),
    42: (
        "directory_profile",
        "Fitness Palace public profile identifies Astana Turan30 and fitness/pool/group-training facilities.",
        "Current procurement and acceptable mirror sizes/thickness are unconfirmed.",
    ),
    43: (
        "directory_profile",
        "Fitness First public profile identifies gym in Astana Asia Park, KabanbayBatyr21.",
        "Source published2018; current operation particularly uncertain. Tenant of B16; distinct purchasing operator unproven.",
    ),
    44: (
        "directory_profile",
        "PilatesPro public profile identifies Astana AitekeBi14 and pilates studio; describes stained-glass windows.",
        "2021 publication; window mention does not substantiate mirror purchasing or fit of ordinary clear remnants.",
    ),
    45: (
        "primary_profile",
        "Astana Opera official site identifies national opera/ballet theatre and public procurement section.",
        "Public institution; theatre set/display glass is a proposal, not a confirmed procurement item or safety approval.",
    ),
    46: (
        "primary_profile",
        "QazExpoCongress official site identifies Astana MangilikEl55/13, EXPO exhibition/congress/business facilities and procurement section.",
        "EXPO is a facility group; small exhibition components are plausible but current orders and specifications unknown.",
    ),
    47: (
        "directory_profile",
        "KHS Hub public profile identifies Astana UlyDala5/2 and IT community bar/meetup venue.",
        "Primary-domain outage avoided with public profile; no established glass or mirror demand.",
    ),
    48: (
        "directory_profile",
        "Tamaq public profile identifies Astana Kazhymukan20 and cafeteria/bakery profile.",
        "More precisely cafeteria than restaurant;2022 publication/current operation uncertain. No procurement evidence.",
    ),
    49: (
        "directory_profile",
        "Saf public profile identifies Astana KasymAmanzholov24, restaurant and VIP/children spaces.",
        "2023 publication; no glass/mirror purchase requirement is documented.",
    ),
    50: (
        "primary_profile",
        "Hani official site identifies Karaganda cakes/desserts/brunch delivery business.",
        "Karaganda matches CSV; website proves food activity, not that it operates the proposed glass display or needs its replacement.",
    ),
}

EXTRA_URLS = {
    4: ["https://mebel-ideal.kz/"],
    6: ["https://biar.kz/"],
    7: ["https://dreamart.kz/kontakty/vystavochnyy-salon-v-mfc-moskva/"],
    9: ["https://sgholding.kz/kz/kontakty/"],
    10: [
        "https://alcon.kz/i/src/Preza%20for%20Alcon/%D0%91%D1%80%D0%BE%D1%88%D1%8E%D1%80%D0%B0%20B2B%20%D1%8F%D0%BD%D0%B2%D0%B0%D1%80%D1%8C%202019%20small.pdf"
    ],
    11: ["https://www.veka.kz/where-buy"],
    12: ["https://megastroy.kz/contacts/", "https://megastroy.kz/company/kak-stat-postavshchikom/"],
}


def main():
    rows = list(csv.DictReader(SOURCE.open(encoding="utf-8-sig")))
    assert len(rows) == len(NOTES) == 50
    result = {
        "schema_version": 1,
        "reviewed_at": "2026-11-28",
        "reviewer": "Mustiks07 / independent post-review",
        "source_csv_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "method": "Individually read public web page content and explicit identity/city/activity; HTTP status alone never accepted. No contact with organizations.",
        "scope": "Public profile evidence only. No organization has confirmed demand or consent to purchase. Re-crawl date is not proof a historic venue remains operational.",
        "application_policy": "All inherited 100x100..2000x1500 dimensions, thickness/material lists and proposed uses remain engineering hypotheses requiring design/safety/purchasing confirmation, not a sourced order. Do not label them confirmed customer requirements.",
        "records": [],
    }
    for index, row in enumerate(rows, 1):
        status, support, uncertainty = NOTES[index]
        result["records"].append(
            {
                "entity_id": f"B{index:02}",
                "name": row["name"],
                "city": row["city"],
                "category_as_supplied": row["category"],
                "public_profile_status": status,
                "public_sources": list(dict.fromkeys([row["source_url"], *EXTRA_URLS.get(index, [])])),
                "supported_paraphrase": support,
                "record_uncertainties": [uncertainty],
                "confirmed_buyer_demand": False,
                "application_status": "engineering_hypothesis",
                "eligible_as_distinct_organization": None if index == 11 else "public_profile_lead_only",
            }
        )
    path = ROOT / "data/buyers/independent_semantic_review_2026-11-28.json"
    path.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf8"))
    build_validated_registry(rows, result)


def build_validated_registry(rows, audit):
    """Proposal for root integration; additive files, original row identities preserved."""
    original = json.loads((ROOT / "data/buyers/evidence.platform.json").read_text(encoding="utf8"))
    evidence = {k: copy.deepcopy(v) for k, v in original.items() if k != "records"}
    evidence.update(
        {
            "records": [],
            "transform_version": "independent-semantic-v2-2026-11-28",
            "replaced_entity_ids": ["B11", "B19"],
            "new_entity_ids": ["B51", "B52"],
            "reviewer_scope": "Public identity/city/activity only; actual demand and purchasing independence not asserted.",
            "source_csv_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        }
    )
    validated = []
    for index, (row, record, reviewed) in enumerate(
        zip(rows, original["records"], audit["records"], strict=True), 1
    ):
        if index in (11, 19):
            continue
        row, record = copy.deepcopy(row), copy.deepcopy(record)
        if index == 7:
            row["category"] = "мебельная фабрика"
            row["source_url"] = "https://dreamart.kz/kontakty/vystavochnyy-salon-v-mfc-moskva/"
        if index == 9:
            row["source_url"] = "https://sgholding.kz/kz/kontakty/"
        if index == 12:
            row["source_url"] = "https://megastroy.kz/contacts/"
        fact = f"Публичный профиль: {row['name']}; город {row['city']}; деятельность — {row['category']}. Источник подтверждает профиль, а не спрос на стекло."
        if index == 2:
            fact = "Astana Mebel Group: собственное изготовление мебели на заказ, в том числе шкафов; Астана, Орлыкол 10Б. Наличие стеклянных полок и зеркальных фасадов на просмотренной странице не установлено."
        if index == 3:
            fact = "DalaSK: собственное производство корпусной и мягкой мебели в Астане. Стеклянные полки, журнальные столики и зеркала для прихожей на просмотренной странице не установлены."
        row["why"] = "Предложение применения, требующее согласования с организацией: " + row["why"]
        record.update(
            {
                "profile": fact,
                "confirmation": fact,
                "source_url": row["source_url"],
                "checked_at": "2026-11-28",
                "reviewer": "Mustiks07 / independent post-review",
                "verification_scope": "public_identity_city_activity_not_procurement",
                "uncertainties": reviewed["record_uncertainties"],
                "confirmed_buyer_demand": False,
            }
        )
        for application in record["applications"]:
            application.update(
                {
                    "activity": fact,
                    "source_url": row["source_url"],
                    "checked_at": "2026-11-28",
                }
            )
        evidence["records"].append(record)
        validated.append(row)
    additions = [
        (
            "B51",
            "ТОО «Комфорт Строй Плюс СК»",
            "окна и двери",
            "https://ksplus.kz/index.htm",
            "Астана, Бейсекбаева 32/2. Производство алюминиевых и ПВХ окон, дверей, витражей и перегородок в собственном цеху; название ТОО и адрес опубликованы на официальном сайте.",
            [],
            "Потенциальный производственный партнер; размеры, состав стеклопакета и безопасное стекло требуют проектного согласования. Готовность покупать обрезки не подтверждена.",
        ),
        (
            "B52",
            "INTERWOOD — мебель на заказ",
            "мебельная фабрика",
            "https://interwood.kz/",
            "Астана, Тауелсиздик 34/2, офис 44. Официальный сайт описывает изготовление мебели; портфолио явно показывает шкафы со стеклянными дверцами, витрины и мебель с зеркалами.",
            copy.deepcopy(original["records"][0]["applications"]),
            "Предложение применения: мебельные стеклянные вставки и зеркала, по аналогии с опубликованным портфолио. Конкретные размеры, толщины и текущая закупка не подтверждены.",
        ),
    ]
    for entity_id, name, category, url, fact, applications, why in additions:
        for application in applications:
            application.update(
                {
                    "activity": fact,
                    "source_url": url,
                    "checked_at": "2026-11-28",
                }
            )
        record = {
            "entity_id": entity_id,
            "name": name,
            "city": "Астана",
            "profile": fact,
            "confirmation": fact,
            "source_url": url,
            "checked_at": "2026-11-28",
            "reviewer": "Mustiks07 / independent post-review",
            "applications": applications,
            "verification_scope": "public_identity_city_activity_not_procurement",
            "confirmed_buyer_demand": False,
            "uncertainties": [why],
        }
        evidence["records"].append(record)
        validated.append(
            dict(name=name, city="Астана", category=category, url=url, why=why, source_url=url, score="80")
        )
    csv_path = ROOT / "data/buyers/buyers.independent-v2.csv"
    with csv_path.open("w", encoding="utf8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(validated)
    evidence["validated_csv_sha256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    evidence["source_evidence_sha256"] = hashlib.sha256(
        (ROOT / "data/buyers/evidence.platform.json").read_bytes()
    ).hexdigest()
    evidence["integration_reviewed_ids"] = [r["entity_id"] for r in evidence["records"]]
    assert len(validated) == len(evidence["records"]) == len({r["name"] for r in validated}) == 50
    assert len({r["category"] for r in validated}) == 9
    (ROOT / "data/buyers/evidence.independent-v2.json").write_bytes(
        (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode("utf8")
    )


if __name__ == "__main__":
    main()
