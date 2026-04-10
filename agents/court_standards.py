"""Court standards guardrails for MACT-style legal drafting.

This module is intentionally deterministic for high-risk legal outputs.
It provides:
1. Deterministic compensation calculation (Sarla Verma + Pranay Sethi style heads)
2. Citation-locked draft assembly
3. Validation gate that blocks non-compliant packets
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Tuple


@dataclass
class CompensationInput:
    victim_name: str
    victim_age: int
    monthly_income_inr: float
    dependents_count: int
    is_bachelor: bool
    future_prospect_rate: float = 0.4


@dataclass
class CompensationBreakdown:
    annual_income_inr: float
    future_prospects_addition_inr: float
    adjusted_annual_income_inr: float
    personal_expense_fraction: float
    annual_dependency_inr: float
    multiplier: int
    loss_of_dependency_inr: float
    loss_of_estate_inr: float
    loss_of_consortium_inr: float
    funeral_expenses_inr: float
    total_compensation_inr: float


@dataclass
class ValidationResult:
    passed: bool
    errors: List[str]
    warnings: List[str]
    score: float


def multiplier_for_age(age: int) -> int:
    if age <= 15:
        return 15
    if age <= 25:
        return 18
    if age <= 30:
        return 17
    if age <= 35:
        return 16
    if age <= 40:
        return 15
    if age <= 45:
        return 14
    if age <= 50:
        return 13
    if age <= 55:
        return 11
    if age <= 60:
        return 9
    if age <= 65:
        return 7
    return 5


def personal_expense_fraction(dependents_count: int, is_bachelor: bool) -> float:
    if is_bachelor:
        return 0.5
    if dependents_count <= 3:
        return 1.0 / 3.0
    if dependents_count <= 6:
        return 0.25
    return 0.2


def compute_compensation(inputs: CompensationInput) -> CompensationBreakdown:
    annual_income = max(0.0, inputs.monthly_income_inr) * 12.0
    future_add = annual_income * max(0.0, inputs.future_prospect_rate)
    adjusted_annual_income = annual_income + future_add

    exp_fraction = personal_expense_fraction(inputs.dependents_count, inputs.is_bachelor)
    annual_dependency = adjusted_annual_income * (1.0 - exp_fraction)
    multiplier = multiplier_for_age(inputs.victim_age)
    loss_dependency = annual_dependency * multiplier

    loss_of_estate = 15000.0
    loss_of_consortium = 40000.0
    funeral_expenses = 15000.0
    total = loss_dependency + loss_of_estate + loss_of_consortium + funeral_expenses

    return CompensationBreakdown(
        annual_income_inr=round(annual_income, 2),
        future_prospects_addition_inr=round(future_add, 2),
        adjusted_annual_income_inr=round(adjusted_annual_income, 2),
        personal_expense_fraction=round(exp_fraction, 4),
        annual_dependency_inr=round(annual_dependency, 2),
        multiplier=multiplier,
        loss_of_dependency_inr=round(loss_dependency, 2),
        loss_of_estate_inr=loss_of_estate,
        loss_of_consortium_inr=loss_of_consortium,
        funeral_expenses_inr=funeral_expenses,
        total_compensation_inr=round(total, 2),
    )


def build_citation_registry(legal_reference_db: Dict) -> Dict[str, Dict]:
    """Create approved citation registry from loaded legal reference DB."""
    registry: Dict[str, Dict] = {}
    for sec, sec_info in legal_reference_db.items():
        registry[f"MVA-{sec}"] = {
            "section": sec,
            "title": sec_info.get("title", ""),
            "chapter": sec_info.get("chapter", ""),
            "authority": "Statute",
        }
    # Include explicit precedent anchors used by deterministic calculator.
    registry["SC-SARLA-VERMA-2009"] = {
        "section": "precedent",
        "title": "Sarla Verma v. DTC (2009)",
        "authority": "Supreme Court",
    }
    registry["SC-PRANAY-SETHI-2017"] = {
        "section": "precedent",
        "title": "National Insurance Co. Ltd. v. Pranay Sethi (2017)",
        "authority": "Supreme Court",
    }
    registry["MVA-166"] = {
        "section": "166",
        "title": "Application for compensation (fault liability)",
        "authority": "Statute",
    }
    registry["MVA-140"] = {
        "section": "140",
        "title": "Liability to pay compensation in certain cases on no fault basis",
        "authority": "Statute",
    }
    return registry


def build_section_166_draft(
    claim: Dict,
    compensation: CompensationBreakdown,
    citations: List[str],
) -> str:
    """Assemble a citation-locked draft text with placeholders kept explicit."""
    return (
        f"IN THE COURT OF MOTOR ACCIDENT CLAIMS TRIBUNAL AT {claim.get('jurisdiction', 'TBD')}\n"
        f"Application under Section 166 and 140 of the Motor Vehicles Act, 1988\n\n"
        f"Claimant: {claim.get('claimant_name', 'TBD')}\n"
        f"Victim: {claim.get('victim_name', 'TBD')} | Age: {claim.get('victim_age', 'TBD')}\n"
        f"Occupation: {claim.get('occupation', 'TBD')} | Monthly Income: INR {claim.get('monthly_income_inr', 'TBD')}\n\n"
        f"Accident Facts:\n"
        f"Date: {claim.get('accident_date', 'TBD')} | Time: {claim.get('accident_time', 'TBD')}\n"
        f"Location: {claim.get('accident_location', 'TBD')}\n"
        f"Narrative: {claim.get('accident_narrative', 'TBD')}\n\n"
        f"Respondents:\n"
        f"1. Driver: {claim.get('respondent_driver', 'TBD')}\n"
        f"2. Owner: {claim.get('respondent_owner', 'TBD')}\n"
        f"3. Insurer: {claim.get('respondent_insurer', 'TBD')}\n\n"
        f"Compensation Computation (Deterministic):\n"
        f"Annual Income: INR {compensation.annual_income_inr}\n"
        f"Future Prospects Addition: INR {compensation.future_prospects_addition_inr}\n"
        f"Personal Expense Fraction: {compensation.personal_expense_fraction}\n"
        f"Multiplier: {compensation.multiplier}\n"
        f"Loss of Dependency: INR {compensation.loss_of_dependency_inr}\n"
        f"Loss of Estate: INR {compensation.loss_of_estate_inr}\n"
        f"Loss of Consortium: INR {compensation.loss_of_consortium_inr}\n"
        f"Funeral Expenses: INR {compensation.funeral_expenses_inr}\n"
        f"Total Claimed Compensation: INR {compensation.total_compensation_inr}\n\n"
        f"Prayer:\n"
        f"It is prayed that compensation of INR {compensation.total_compensation_inr} "
        f"with interest at {claim.get('interest_percent', 12)}% per annum "
        f"from date of filing till realization be awarded against respondents jointly and severally.\n\n"
        f"Citations Used: {', '.join(citations)}\n"
    )


def validate_court_packet(packet: Dict, citation_registry: Dict[str, Dict]) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []

    required_top = ["claim", "compensation", "citations", "draft_text"]
    for key in required_top:
        if key not in packet:
            errors.append(f"Missing required key: {key}")

    citations = packet.get("citations", [])
    if not citations:
        errors.append("No citations provided")
    else:
        invalid = [c for c in citations if c not in citation_registry]
        if invalid:
            errors.append(f"Unapproved citations found: {invalid}")

    comp = packet.get("compensation", {})
    total = float(comp.get("total_compensation_inr", 0.0))
    sub_sum = float(comp.get("loss_of_dependency_inr", 0.0)) + float(comp.get("loss_of_estate_inr", 0.0)) + float(comp.get("loss_of_consortium_inr", 0.0)) + float(comp.get("funeral_expenses_inr", 0.0))
    if round(total, 2) != round(sub_sum, 2):
        errors.append("Compensation arithmetic mismatch")

    claim = packet.get("claim", {})
    required_claim_fields = [
        "jurisdiction",
        "claimant_name",
        "victim_name",
        "victim_age",
        "monthly_income_inr",
        "accident_date",
        "accident_location",
        "respondent_driver",
        "respondent_owner",
        "respondent_insurer",
    ]
    for field in required_claim_fields:
        if not str(claim.get(field, "")).strip():
            errors.append(f"Missing claim field: {field}")

    draft_text = packet.get("draft_text", "")
    if "Application under Section 166 and 140" not in draft_text:
        warnings.append("Draft does not include explicit Section 166/140 heading")

    checks_total = 4
    checks_passed = 0
    if "claim" in packet and "compensation" in packet and "citations" in packet and "draft_text" in packet:
        checks_passed += 1
    if not [c for c in citations if c not in citation_registry]:
        checks_passed += 1
    if round(total, 2) == round(sub_sum, 2):
        checks_passed += 1
    if not [f for f in required_claim_fields if not str(claim.get(f, "")).strip()]:
        checks_passed += 1

    score = checks_passed / float(checks_total)
    return ValidationResult(passed=len(errors) == 0, errors=errors, warnings=warnings, score=score)


def build_and_validate_packet(claim: Dict, legal_reference_db: Dict) -> Tuple[Dict, ValidationResult]:
    citation_registry = build_citation_registry(legal_reference_db)

    comp_inputs = CompensationInput(
        victim_name=str(claim.get("victim_name", "")),
        victim_age=int(claim.get("victim_age", 0) or 0),
        monthly_income_inr=float(claim.get("monthly_income_inr", 0.0) or 0.0),
        dependents_count=int(claim.get("dependents_count", 0) or 0),
        is_bachelor=bool(claim.get("is_bachelor", False)),
        future_prospect_rate=float(claim.get("future_prospect_rate", 0.4) or 0.4),
    )
    compensation = compute_compensation(comp_inputs)

    citations = [
        "MVA-166",
        "MVA-140",
        "SC-SARLA-VERMA-2009",
        "SC-PRANAY-SETHI-2017",
    ]
    # Keep only citations available in current registry so validation is deterministic.
    citations = [c for c in citations if c in citation_registry]

    draft_text = build_section_166_draft(claim=claim, compensation=compensation, citations=citations)

    packet = {
        "claim": claim,
        "compensation": asdict(compensation),
        "citations": citations,
        "draft_text": draft_text,
        "registry_size": len(citation_registry),
    }
    validation = validate_court_packet(packet, citation_registry=citation_registry)
    packet["validation"] = asdict(validation)
    return packet, validation
