"""Per-run step and token-cost circuit breakers."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


class BudgetExceeded(RuntimeError):
    """A run crossed its configured step or token-cost limit."""


@dataclass(frozen=True)
class TokenPricing:
    """Standard API prices in USD per million tokens."""

    input_usd_per_million: Decimal
    output_usd_per_million: Decimal

    def cost(self, *, input_tokens: int, output_tokens: int) -> Decimal:
        million = Decimal(1_000_000)
        return (
            Decimal(input_tokens) * self.input_usd_per_million
            + Decimal(output_tokens) * self.output_usd_per_million
        ) / million


@dataclass
class RunBudget:
    max_steps: int
    max_token_cost_usd: Decimal
    step_count: int = 0
    token_cost_usd: Decimal = Decimal(0)

    def charge_step(self) -> None:
        self.step_count += 1
        if self.step_count > self.max_steps:
            raise BudgetExceeded(
                f"step budget exceeded: {self.step_count} > {self.max_steps}"
            )

    def charge_tokens(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        pricing: TokenPricing,
    ) -> None:
        self.token_cost_usd += pricing.cost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        if self.token_cost_usd > self.max_token_cost_usd:
            raise BudgetExceeded(
                "token cost budget exceeded: "
                f"{self.token_cost_usd} > {self.max_token_cost_usd} USD"
            )


__all__ = ["BudgetExceeded", "RunBudget", "TokenPricing"]
