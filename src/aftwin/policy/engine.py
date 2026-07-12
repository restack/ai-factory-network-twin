"""Static policy orchestration."""

from collections.abc import Callable

from aftwin.domain.graph import FabricGraph
from aftwin.domain.models import Fabric
from aftwin.policy.findings import Finding, ValidationReport
from aftwin.policy.profile import PolicyProfile
from aftwin.policy.rules import addressing, clos, general, plane
from aftwin.policy.rules.context import RuleContext

Rule = Callable[[RuleContext], list[Finding]]

DEFAULT_RULES: tuple[Rule, ...] = (
    general.evaluate,
    plane.evaluate,
    clos.evaluate,
    addressing.evaluate,
)


class PolicyEngine:
    """Evaluate every rule and aggregate findings without fail-fast behavior."""

    def __init__(self, rules: tuple[Rule, ...] = DEFAULT_RULES) -> None:
        self.rules = rules

    def validate(self, fabric: Fabric, profile: PolicyProfile) -> ValidationReport:
        context = RuleContext(
            fabric=fabric,
            graph=FabricGraph(fabric),
            profile=profile,
        )
        findings = tuple(finding for rule in self.rules for finding in rule(context))
        return ValidationReport(findings=findings)
