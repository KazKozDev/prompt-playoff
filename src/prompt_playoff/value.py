"""What a measured technique is worth, in the numbers a budget is written in.

Everything here is arithmetic over cards that were already measured. Nothing in
this module calls a model, and nothing in it invents a figure: each ratio is
either computed from two real scorecards or reported as absent, with the reason
it is absent, because "we could not tell" and "no gain" are different answers
and a business screen that renders them alike is worse than one that renders
neither.

The question it exists to answer is not which technique is best. It is whether
a cheap model, prompted properly, does the job well enough that the expensive
one is not worth paying for — and if not, how much of the distance it covered.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from prompt_playoff.domain import ModelProfile
from prompt_playoff.evals import Scorecard

#: Below this the reference is not meaningfully better than the untreated small
#: model, and dividing by the difference turns measurement noise into a
#: headline. The honest reading at that point is that there is no gap to close.
MIN_REFERENCE_HEADROOM = 0.01

TOKENS = "tokens"
HARDWARE = "hardware-hours"
UNKNOWN = "unknown"


def cost_basis(model: ModelProfile) -> str:
    """Which meter this model's cost was read off, in the same order it is billed."""
    if (
        model.input_cost_per_million_usd is not None
        and model.output_cost_per_million_usd is not None
    ):
        return TOKENS
    if model.hardware_cost_per_hour_usd is not None:
        return HARDWARE
    return UNKNOWN


class ValueCell(BaseModel):
    """One measured configuration, reduced to what a buyer compares."""

    role: str
    model_id: str
    technique_id: str | None = None
    technique_title: str | None = None
    quality: float
    reliability: float
    mean_latency_seconds: float
    p95_latency_seconds: float
    mean_cost_usd: float | None = None
    cost_basis: str = UNKNOWN

    @classmethod
    def from_scorecard(
        cls,
        role: str,
        model: ModelProfile,
        card: Scorecard,
        *,
        technique_id: str | None = None,
        technique_title: str | None = None,
    ) -> ValueCell:
        return cls(
            role=role,
            model_id=model.model_id,
            technique_id=technique_id,
            technique_title=technique_title,
            quality=card.quality,
            reliability=card.reliability,
            mean_latency_seconds=card.mean_latency_seconds,
            p95_latency_seconds=card.p95_latency_seconds,
            mean_cost_usd=card.mean_cost_usd,
            cost_basis=cost_basis(model),
        )

    @property
    def cost_per_success_usd(self) -> float | None:
        """Cost of one answer that was actually right.

        Dividing by quality is what makes two prices comparable: a cheaper call
        that is wrong a third of the time is not cheaper per delivered result,
        and this is the only number on the card that says so.
        """
        if self.mean_cost_usd is None or self.quality <= 0:
            return None
        return round(self.mean_cost_usd / self.quality, 8)

    def monthly_usd(self, tasks_per_month: int) -> float | None:
        if self.mean_cost_usd is None:
            return None
        return round(self.mean_cost_usd * tasks_per_month, 2)


class ValueReport(BaseModel):
    """Baseline, optimized and reference held against each other."""

    dataset: str
    examples: int
    repeats: int
    baseline: ValueCell
    optimized: ValueCell
    reference: ValueCell | None = None
    tasks_per_month: int = Field(default=100_000, ge=1)
    target_quality: float | None = Field(default=None, ge=0, le=1)
    notes: list[str] = Field(default_factory=list)

    @property
    def quality_gain_pp(self) -> float:
        """How far the technique moved the small model, in percentage points."""
        return round((self.optimized.quality - self.baseline.quality) * 100, 2)

    @property
    def gap_closed(self) -> float | None:
        """Share of the small-to-large distance the prompt covered.

        Absent whenever the denominator is not a real distance — no reference
        was run, or the reference was no better than the untreated small model.
        A value above 1 is left as measured rather than capped: the small model
        overtaking the expensive one is the finding, not an error to round away.
        """
        if self.reference is None:
            return None
        headroom = self.reference.quality - self.baseline.quality
        if headroom < MIN_REFERENCE_HEADROOM:
            return None
        return round((self.optimized.quality - self.baseline.quality) / headroom, 4)

    @property
    def cost_ratio_vs_reference(self) -> float | None:
        """What the optimized small model costs per success, as a share of the big one."""
        if self.reference is None:
            return None
        mine = self.optimized.cost_per_success_usd
        theirs = self.reference.cost_per_success_usd
        if mine is None or theirs is None or theirs <= 0:
            return None
        return round(mine / theirs, 6)

    @property
    def quality_ratio_vs_reference(self) -> float | None:
        if self.reference is None or self.reference.quality <= 0:
            return None
        return round(self.optimized.quality / self.reference.quality, 4)

    @property
    def monthly_saving_usd(self) -> float | None:
        """Money not spent per month by running the small model instead.

        Reported only when the optimized model actually meets the target the
        user set, because a saving bought by dropping below the required quality
        is not a saving; it is a different, worse service at a lower price.
        """
        if self.reference is None or not self.meets_target:
            return None
        mine = self.optimized.monthly_usd(self.tasks_per_month)
        theirs = self.reference.monthly_usd(self.tasks_per_month)
        if mine is None or theirs is None:
            return None
        return round(theirs - mine, 2)

    @property
    def meets_target(self) -> bool:
        """Whether the optimized small model clears the quality that was asked for.

        With no target set there is nothing to clear, and the honest answer is
        yes only in the sense that no bar was ever raised — so the screens that
        use this must show the target alongside it.
        """
        if self.target_quality is None:
            return True
        return self.optimized.quality >= self.target_quality

    @property
    def cheapest_meeting_target(self) -> ValueCell | None:
        """The least expensive configuration that does the job at the required quality.

        This is the product's actual answer: not the best prompt and not the
        best model, but the smallest bill that still clears the bar.
        """
        bar = self.target_quality
        cells = [cell for cell in self.cells() if bar is None or cell.quality >= bar]
        priced = [cell for cell in cells if cell.cost_per_success_usd is not None]
        if not priced:
            return None
        return min(priced, key=lambda cell: cell.cost_per_success_usd or 0.0)

    def cells(self) -> list[ValueCell]:
        return [
            cell for cell in (self.baseline, self.optimized, self.reference) if cell is not None
        ]

    def summary(self) -> dict[str, Any]:
        """The card the business screen renders, computed fields included.

        Pydantic does not serialize properties, and every consumer of this
        report wants the derived numbers rather than the three raw cells, so the
        flattening happens once here instead of in each surface.
        """
        return {
            "dataset": self.dataset,
            "examples": self.examples,
            "repeats": self.repeats,
            "tasks_per_month": self.tasks_per_month,
            "target_quality": self.target_quality,
            "baseline": self.baseline.model_dump(),
            "optimized": self.optimized.model_dump(),
            "reference": self.reference.model_dump() if self.reference else None,
            "quality_gain_pp": self.quality_gain_pp,
            "gap_closed": self.gap_closed,
            "quality_ratio_vs_reference": self.quality_ratio_vs_reference,
            "cost_ratio_vs_reference": self.cost_ratio_vs_reference,
            "baseline_cost_per_success_usd": self.baseline.cost_per_success_usd,
            "optimized_cost_per_success_usd": self.optimized.cost_per_success_usd,
            "reference_cost_per_success_usd": (
                self.reference.cost_per_success_usd if self.reference else None
            ),
            "monthly_optimized_usd": self.optimized.monthly_usd(self.tasks_per_month),
            "monthly_reference_usd": (
                self.reference.monthly_usd(self.tasks_per_month) if self.reference else None
            ),
            "monthly_saving_usd": self.monthly_saving_usd,
            "meets_target": self.meets_target,
            "cheapest_meeting_target": (
                self.cheapest_meeting_target.model_dump() if self.cheapest_meeting_target else None
            ),
            "notes": self.notes + list(self.warnings()),
        }

    def warnings(self) -> list[str]:
        """Every reason a number on this card is missing or should not be trusted."""
        out: list[str] = []
        unpriced = [cell.role for cell in self.cells() if cell.mean_cost_usd is None]
        if unpriced:
            out.append(
                f"No price for {', '.join(unpriced)}: set token rates for a hosted model, or "
                "an hourly machine rate for a self-hosted one, and the cost figures appear."
            )
        if self.reference is None:
            out.append(
                "No reference model was run, so this says how much the technique helped, "
                "not whether it removed the need for a larger model."
            )
        elif self.gap_closed is None:
            out.append(
                f"The reference scored {self.reference.quality:.2f} against the untreated "
                f"{self.baseline.quality:.2f}, which is no real headroom — there is no gap to "
                "close, and on this data the small model was already competitive."
            )
        if self.reference is not None and self.reference.model_id == self.baseline.model_id:
            out.append(
                f"Reference and baseline are both {self.baseline.model_id}, so the comparison "
                "is against itself and any gap it reports is noise."
            )
        if not self.meets_target and self.target_quality is not None:
            out.append(
                f"Quality {self.optimized.quality:.2f} is below the {self.target_quality:.2f} "
                "asked for, so the saving is not offered: it would be paid for in wrong answers."
            )
        return out
