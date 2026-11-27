"""U07 pure shared decimal calculation; source references are supplied evidence, not audited facts."""

from decimal import Decimal
from itertools import product
from statistics import median

from glassflow.contracts.economics import EconomicInputs

FORMULA_VERSION = "economics-v2"


def economic_scenario(data):
    if len(data.get("labor_studies", [])) < 10:
        raise ValueError("At least ten distinct paired manual/app tasks required")
    inputs = EconomicInputs.model_validate(data)
    studies = inputs.labor_studies
    manual = [Decimal(s.manual_active_seconds) for s in studies]
    application = [Decimal(s.app_active_seconds) for s in studies]
    differences = [m - a for m, a in zip(manual, application, strict=True)]
    saved = median(differences)
    final, baseline = Decimal(inputs.final_material_value_tg), Decimal(inputs.baseline_material_value_tg)
    delta = (final - baseline) * Decimal(inputs.monthly_dataset_multiplier)
    material = delta * Decimal(inputs.material_use_fraction)
    labor = saved / Decimal(3600) * Decimal(inputs.monthly_operations) * Decimal(inputs.hourly_rate_tg)
    costs = sum((Decimal(getattr(inputs, k)) for k in (
        "ai_monthly_tg", "hosting_monthly_tg", "support_monthly_tg")), Decimal(0))
    net = material + labor - costs
    fields = ("monthly_operations", "monthly_dataset_multiplier", "hourly_rate_tg", "material_use_fraction")
    bounds = []
    for field in fields:
        interval = getattr(inputs.sensitivity, field)
        bounds.append((Decimal(interval.low), Decimal(interval.high)) if interval
                      else (Decimal(getattr(inputs, field)),))
    outcomes = [(final - baseline) * multiplier * fraction + seconds / Decimal(3600) * operations * rate - costs
                for operations, multiplier, rate, fraction in product(*bounds)
                for seconds in (min(differences), max(differences))]
    return {
        "planned_material_value_tg": final,
        "baseline_material_value_tg": baseline,
        "planned_material_delta_tg": delta,
        "material_delta_tg": material,
        "labor_effect_tg": labor,
        "monthly_costs_tg": costs,
        "scenario_net_effect_tg": net,
        "payback_months": Decimal(inputs.implementation_tg) / net if net > 0 else None,
        "manual_median_seconds": median(manual),
        "app_median_seconds": median(application),
        "paired_saved_median_seconds": saved,
        "paired_saved_min_seconds": min(differences),
        "paired_saved_max_seconds": max(differences),
        "study_count": len(studies),
        "manual_error_count": sum(s.manual_error_count for s in studies),
        "app_error_count": sum(s.app_error_count for s in studies),
        "confirmed_material_use_value_tg": (Decimal(inputs.confirmed_material_use_value_tg)
                                             if inputs.confirmed_material_use_value_tg is not None else None),
        "potential_remnant_sale_tg": Decimal(inputs.potential_remnant_sale_tg),
        "actual_sale_revenue_tg": Decimal(inputs.actual_sale_revenue_tg) if inputs.actual_sale_revenue_tg is not None else None,
        "net_range_low_tg": min(outcomes),
        "net_range_high_tg": max(outcomes),
    }


def serialized_result(data):
    return {k: format(v.normalize(), "f") if isinstance(v, Decimal) else v
            for k, v in economic_scenario(data).items()}
