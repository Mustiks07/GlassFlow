"""U07 shared scenario inputs. Decimal strings, measured labor and explicit assumptions."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from .common import DTO, DatasetRequest, Identifier, MoneyString, NonnegativeInt


class LaborStudy(DTO):
    task_id: Identifier
    protocol: str = Field(min_length=1, max_length=1000)
    observer: Identifier
    operator: Identifier
    measured_at: str
    start_definition: str = Field(min_length=1, max_length=1000)
    end_definition: str = Field(min_length=1, max_length=1000)
    task_input_ref: str = Field(min_length=1)
    manual_result_ref: str = Field(min_length=1)
    app_result_ref: str = Field(min_length=1)
    manual_started_at: str
    manual_finished_at: str
    app_started_at: str
    app_finished_at: str
    manual_active_seconds: MoneyString
    app_active_seconds: MoneyString
    manual_error_count: NonnegativeInt
    app_error_count: NonnegativeInt
    manual_rework_seconds: MoneyString
    app_rework_seconds: MoneyString

    @model_validator(mode="after")
    def measured_intervals(self):
        for mode in ("manual", "app"):
            start = datetime.fromisoformat(getattr(self, f"{mode}_started_at").replace("Z", "+00:00"))
            end = datetime.fromisoformat(getattr(self, f"{mode}_finished_at").replace("Z", "+00:00"))
            active = Decimal(getattr(self, f"{mode}_active_seconds"))
            rework = Decimal(getattr(self, f"{mode}_rework_seconds"))
            if (start.tzinfo is None or end.tzinfo is None or end <= start
                    or not 0 < active <= Decimal(str((end - start).total_seconds()))
                    or rework > active):
                raise ValueError("Real paired intervals require timezone, positive active time within elapsed time, rework included")
        return self


class DecimalRange(DTO):
    low: MoneyString
    high: MoneyString

    @model_validator(mode="after")
    def ordered(self):
        if Decimal(self.low) > Decimal(self.high):
            raise ValueError("Sensitivity low must not exceed high")
        return self


class EconomicSensitivity(DTO):
    monthly_operations: DecimalRange | None = None
    monthly_dataset_multiplier: DecimalRange | None = None
    hourly_rate_tg: DecimalRange | None = None
    material_use_fraction: DecimalRange | None = None


class EconomicInputs(DTO):
    measurement_status: Literal["supplied_measurements", "synthetic"]
    labor_studies: list[LaborStudy] = Field(min_length=10, max_length=1000)
    final_material_value_tg: MoneyString
    baseline_material_value_tg: MoneyString
    baseline_validation_ref: str = Field(min_length=1)
    final_validation_ref: str = Field(min_length=1)
    baseline_description: str = Field(min_length=1, max_length=1000)
    monthly_dataset_multiplier: MoneyString
    monthly_operations: MoneyString
    hourly_rate_tg: MoneyString
    hourly_rate_basis: str = Field(min_length=1, max_length=1000)
    monthly_volume_basis: str = Field(min_length=1, max_length=1000)
    ai_monthly_tg: MoneyString
    ai_cost_basis: str = Field(min_length=1, max_length=1000)
    hosting_monthly_tg: MoneyString
    support_monthly_tg: MoneyString
    implementation_tg: MoneyString
    implementation_basis: str = Field(min_length=1, max_length=1000)
    material_use_fraction: MoneyString = "1"
    material_use_basis: str = Field(default="Сценарное допущение: весь прирост оценки используется", min_length=1, max_length=1000)
    confirmed_material_use_value_tg: MoneyString | None = None
    confirmed_material_use_ref: str | None = None
    potential_remnant_sale_tg: MoneyString = "0"
    actual_sale_revenue_tg: MoneyString | None = None
    actual_sale_ref: str | None = None
    sensitivity: EconomicSensitivity = Field(default_factory=EconomicSensitivity)

    @model_validator(mode="after")
    def evidence_consistency(self):
        if len({s.task_id for s in self.labor_studies}) != len(self.labor_studies):
            raise ValueError("Ten distinct paired tasks required")
        if not 0 <= Decimal(self.material_use_fraction) <= 1:
            raise ValueError("Material use fraction must be between0 and1")
        if self.sensitivity.material_use_fraction and Decimal(self.sensitivity.material_use_fraction.high) > 1:
            raise ValueError("Sensitivity material use fraction cannot exceed1")
        for value, ref in ((self.confirmed_material_use_value_tg, self.confirmed_material_use_ref),
                           (self.actual_sale_revenue_tg, self.actual_sale_ref)):
            if (value is None) != (not bool(ref)):
                raise ValueError("Confirmed use/actual sale need both value and explicit evidence reference")
        for field in ("monthly_operations", "monthly_dataset_multiplier", "hourly_rate_tg", "material_use_fraction"):
            interval = getattr(self.sensitivity, field)
            if interval and not Decimal(interval.low) <= Decimal(getattr(self, field)) <= Decimal(interval.high):
                raise ValueError("Central assumptions must lie inside sensitivity bounds")
        return self


class EconomicsCreate(DatasetRequest):
    name: str = Field(min_length=1, max_length=200)
    inputs: EconomicInputs


class EconomicsUpdate(DatasetRequest):
    expected_version: NonnegativeInt
    inputs: EconomicInputs


class EconomicResult(DTO):
    planned_material_value_tg: str
    baseline_material_value_tg: str
    planned_material_delta_tg: str
    material_delta_tg: str
    labor_effect_tg: str
    monthly_costs_tg: str
    scenario_net_effect_tg: str
    payback_months: str | None
    manual_median_seconds: str
    app_median_seconds: str
    paired_saved_median_seconds: str
    paired_saved_min_seconds: str
    paired_saved_max_seconds: str
    study_count: int
    manual_error_count: int
    app_error_count: int
    confirmed_material_use_value_tg: str | None
    potential_remnant_sale_tg: str
    actual_sale_revenue_tg: str | None
    net_range_low_tg: str
    net_range_high_tg: str


class EconomicsScenario(EconomicsCreate):
    scenario_id: str
    version: NonnegativeInt
    formula_version: Literal["economics-v2"] = "economics-v2"
    source_hashes: dict[str, str]
    input_hash: str
    result_hash: str
    results: EconomicResult
    created_at: str
    competition_release_eligible: Literal[False] = False
