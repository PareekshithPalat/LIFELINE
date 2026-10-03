import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Tuple
from models.schemas import PersonalProfile

ADULT, ADOLESCENT, CHILD, INFANT = "adult", "adolescent", "child", "infant"
AGE_CATEGORIES = (ADULT, ADOLESCENT, CHILD, INFANT)

# A recorded allergy to the key implies sensitivity to every listed term.
ALLERGEN_CLASSES: Dict[str, List[str]] = {
    "nsaid": ["nsaid", "nsaids", "ibuprofen", "naproxen", "aspirin", "diclofenac", "ketorolac", "advil",
              "motrin", "aleve", "anti-inflammatory", "anti-inflammatories"],
    "aspirin": ["aspirin", "acetylsalicylic"],
    "ibuprofen": ["ibuprofen", "advil", "motrin"],
    "naproxen": ["naproxen", "aleve"],
    "penicillin": ["penicillin", "amoxicillin", "ampicillin", "augmentin"],
    "peanut": ["peanut", "peanuts", "peanut butter", "groundnut"],
    "tree nut": ["almond", "cashew", "walnut", "hazelnut", "pecan", "pistachio"],
    "nut": ["nut", "nuts", "peanut", "peanut butter", "almond", "cashew", "walnut", "hazelnut"],
    "shellfish": ["shellfish", "shrimp", "prawn", "crab", "lobster"],
    "sulfa": ["sulfa", "sulfonamide", "sulfamethoxazole"],
    "latex": ["latex"],
    "egg": ["egg", "eggs"],
    "milk": ["milk", "dairy"],
    "honey": ["honey"],
}

# Terms a patient condition or medication makes unsafe: (pattern on the condition/med, avoid terms, reason)
CONDITION_RULES: List[Tuple[str, List[str], str]] = [
    (r"bleed|ulcer|haemorrha|hemorrha|haemophilia|hemophilia",
     ["aspirin", "ibuprofen", "naproxen", "nsaid", "nsaids", "blood thinner", "blood thinners"],
     "bleeding risk"),
    (r"warfarin|apixaban|rivaroxaban|dabigatran|edoxaban|clopidogrel|heparin|anticoagul",
     ["aspirin", "ibuprofen", "naproxen", "nsaid", "nsaids"],
     "already on blood-thinning medication"),
    (r"pregnan", ["abdominal thrust", "abdominal thrusts", "heimlich"], "pregnancy (use chest thrusts instead)"),
]
# Conditions that only produce a caution, never withhold a step.
CONDITION_CAUTIONS: List[Tuple[str, str]] = [
    (r"asthma", "Patient has asthma: NSAIDs and beta-blockers can trigger bronchospasm."),
    (r"diabet", "Patient is diabetic: check blood glucose if confused or drowsy."),
    (r"epilep|seizure", "Patient has a seizure disorder: protect the head and time any seizure."),
]

AGE_RULES: Dict[str, List[Tuple[List[str], str, Optional[str]]]] = {
    INFANT: [
        (["aspirin"], "aspirin must not be given to children (Reye syndrome)", None),
        (["abdominal thrust", "abdominal thrusts", "heimlich", "lean person slightly forward", "stand behind"],
         "adult choking technique must not be used on infants under 1 year",
         "Infant under 1 year: support the head face-down along your forearm and give 5 back blows, then turn "
         "face-up and give 5 chest thrusts with 2 fingers on the centre of the chest. Repeat until the object "
         "comes out or the infant becomes unresponsive (then start infant CPR)."),
    ],
    CHILD: [(["aspirin"], "aspirin must not be given to children (Reye syndrome)", None)],
    ADOLESCENT: [(["aspirin"], "aspirin must not be given to adolescents (Reye syndrome)", None)],
    ADULT: [],
}

_INFANT_WORDS = r"\b(baby|babies|infant|infants|newborn|new-born)\b"
_CHILD_WORDS = r"\b(child|children|kid|kids|toddler|toddlers|preschooler|little boy|little girl)\b"
_TEEN_WORDS = r"\b(teen|teens|teenager|teenagers|adolescent|adolescents)\b"
_ADULT_WORDS = r"\b(adult|adults|man|woman|husband|wife|father|mother|dad|mum|mom|grandfather|grandmother|elderly)\b"


def detect_age_category(text: str) -> Optional[str]:
    """Infers the patient's age group from free text; None when not stated."""
    t = text.lower()
    m = re.search(r"\b(\d{1,2})[\s-]*(month|months|mo)[\s-]*old\b", t)
    if m:
        return INFANT if int(m.group(1)) < 12 else CHILD
    m = re.search(r"\b(\d{1,3})[\s-]*(year|years|yr|yrs)[\s-]*old\b", t)
    if m:
        age = int(m.group(1))
        return INFANT if age < 1 else CHILD if age < 12 else ADOLESCENT if age < 18 else ADULT
    if re.search(_INFANT_WORDS, t):
        return INFANT
    if re.search(_CHILD_WORDS, t):
        return CHILD
    if re.search(_TEEN_WORDS, t):
        return ADOLESCENT
    if re.search(_ADULT_WORDS, t):
        return ADULT
    return None


_OTHER_PERSON = re.compile(
    r"\b(my|our|his|her|their)\s+(husband|wife|partner|boyfriend|girlfriend|father|mother|dad|mum|mom|parent|"
    r"son|daughter|child|kid|baby|brother|sister|friend|grandfather|grandmother|grandpa|grandma|uncle|aunt|"
    r"cousin|neighbou?r|colleague|coworker|boss|roommate|flatmate)\b"
    r"|\b(someone|somebody|a stranger|a man|a woman|a person|a child|a kid|a baby|this man|this woman)\b",
    re.IGNORECASE)


def describes_other_person(text: str) -> bool:
    """True when the query is clearly about someone other than the device owner."""
    return bool(_OTHER_PERSON.search(text))


def _singular(term: str) -> str:
    if term.endswith("ies") and len(term) > 4:
        return term[:-3] + "y"
    if term.endswith("s") and not term.endswith("ss") and len(term) > 3:
        return term[:-1]
    return term


def allergy_terms(allergy: str) -> Set[str]:
    """
    "NSAIDs (Ibuprofen, Naproxen)" -> {"nsaid", "nsaids", "ibuprofen", "naproxen", "aspirin", ...}
    Splits compound entries, normalises plurals and expands drug/food classes.
    """
    text = allergy.lower()
    parts = re.split(r"[,;/()]|\band\b|\bor\b|\ballergy\b|\ballergic to\b", text)
    terms: Set[str] = set()
    for part in parts:
        p = re.sub(r"[^a-z0-9\- ]", " ", part).strip()
        p = re.sub(r"\s+", " ", p)
        if len(p) < 3:
            continue
        for candidate in {p, _singular(p)}:
            terms.add(candidate)
            for key, members in ALLERGEN_CLASSES.items():
                if candidate == key or _singular(candidate) == key or candidate == key + "s":
                    terms.update(members)
    return terms


def _term_regex(term: str) -> re.Pattern:
    return re.compile(r"\b" + re.escape(term).replace(r"\ ", r"[\s-]+") + r"(?:s|es)?\b", re.IGNORECASE)


@dataclass
class AvoidRule:
    term: str
    reason: str
    replacement: Optional[str] = None
    _pattern: Optional[re.Pattern] = field(default=None, repr=False)

    def matches(self, text: str) -> bool:
        if self._pattern is None:
            self._pattern = _term_regex(self.term)
        return bool(self._pattern.search(text))


@dataclass
class SafetyContext:
    """Everything that can make a protocol step unsafe for THIS patient."""
    age_category: str = ADULT
    rules: List[AvoidRule] = field(default_factory=list)
    cautions: List[str] = field(default_factory=list)

    def violations(self, text: str) -> List[AvoidRule]:
        hits, seen = [], set()
        for rule in self.rules:
            if rule.reason not in seen and rule.matches(text):
                hits.append(rule)
                seen.add(rule.reason)
        return hits


def build_safety_context(profile: Optional[PersonalProfile], age_category: Optional[str]) -> SafetyContext:
    age = age_category if age_category in AGE_CATEGORIES else ADULT
    ctx = SafetyContext(age_category=age)
    if profile:
        for allergy in profile.allergies:
            for term in sorted(allergy_terms(allergy)):
                ctx.rules.append(AvoidRule(term, f"patient is allergic to {allergy}"))
        for item in profile.chronic_conditions + profile.current_medications:
            low = item.lower()
            for pattern, avoid, why in CONDITION_RULES:
                if re.search(pattern, low):
                    for term in avoid:
                        ctx.rules.append(AvoidRule(term, f"patient has '{item}' ({why})"))
        for item in profile.chronic_conditions:
            for pattern, caution in CONDITION_CAUTIONS:
                if re.search(pattern, item.lower()) and caution not in ctx.cautions:
                    ctx.cautions.append(caution)
    for terms, why, replacement in AGE_RULES[age]:
        for term in terms:
            ctx.rules.append(AvoidRule(term, why, replacement))
    return ctx


@dataclass
class StepScreening:
    safe_steps: List[str]
    withheld: List[str]
    warnings: List[str]


def screen_steps(steps: List[str], ctx: SafetyContext) -> StepScreening:
    """Removes every step that involves something unsafe for this patient and says why."""
    safe, withheld, warnings = [], [], []
    for step in steps:
        hits = ctx.violations(step)
        if not hits:
            safe.append(step)
            continue
        reasons = "; ".join(sorted({h.reason for h in hits}))
        withheld.append(step)
        warnings.append(f"STEP WITHHELD ({reasons}): \"{step}\"")
        for h in hits:
            if h.replacement and h.replacement not in safe:
                safe.append(h.replacement)
    return StepScreening(safe, withheld, warnings)


_ADMINISTER = re.compile(r"\b(give|giving|take|taking|use|using|administer|administering|offer|apply|"
                         r"safe|ok|okay|should|can|could)\b", re.IGNORECASE)


def query_conflicts(query: str, ctx: SafetyContext) -> List[str]:
    """
    Flags a question that asks about GIVING something this patient must not receive
    ("can I give aspirin?"). A description of an exposure ("ate peanuts, throat
    swelling") is not a conflict - it is exactly what the protocol is for.
    """
    if not _ADMINISTER.search(query):
        return []
    by_term: Dict[str, List[str]] = {}
    for rule in ctx.rules:
        if rule.matches(query):
            by_term.setdefault(rule.term, [])
            if rule.reason not in by_term[rule.term]:
                by_term[rule.term].append(rule.reason)
    # Report each mentioned substance once, using its longest matching name.
    out, covered = [], set()
    for term in sorted(by_term, key=len, reverse=True):
        reasons = tuple(by_term[term])
        if reasons in covered:
            continue
        covered.add(reasons)
        out.append(f"DO NOT GIVE {term.upper()}: " + "; ".join(reasons) + ".")
    return out
