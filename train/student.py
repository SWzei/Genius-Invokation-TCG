"""Student-model adapters over the shared strategy supervision (MASD-ADM).

The supervision records (``reps.strategy``) are model-agnostic; this module is the
thin layer that lets different students consume them:

* online protocol -- ``distribution(built) -> probabilities over the legal
  options``. It is the protocol ``ForkSearchPolicy.prior`` and
  ``train.resolver.PriorResolver`` already use, so any student can rank search
  candidates, drive a gate (``envs.adaptive``) or be scored;
* offline protocol -- ``record_distribution(record)`` over a stored
  ``DecisionSupervision`` (text students), or ``store_distributions(store, ...)``
  over encoded samples (network students).

Implemented and tested: :class:`NetworkStudent` (CVPN / TransformerCVPN
checkpoints) and :class:`TextStudent` with an *injected* scorer.

Not implemented: an LLM-backed scorer. ``TextStudent`` defines exactly what such a
student may read (:func:`render_record` / :func:`render_context` -- the acting
player's public view, the legal options, knowledge-unit text) and what it must
return; calling a model is left to the caller. Per ``AGENTS.md`` an LLM never takes
part in strength acceptance.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

from reps.strategy import DecisionSupervision, verdict
from train.resolver import PriorResolver

# scorer(prompt, option_texts) -> one finite score per option (higher = preferred)
Scorer = Callable[[str, Sequence[str]], Sequence[float]]


@runtime_checkable
class Student(Protocol):
    name: str

    def distribution(self, built: Any) -> Sequence[float]:
        """Probabilities over ``built.context.legal_low_level_codes`` (same order)."""


class NetworkStudent(PriorResolver):
    """A CVPN-interface checkpoint as a student (CVPN or TransformerCVPN)."""

    name: str = "network"

    @classmethod
    def from_checkpoint(cls, checkpoint: str, *, temperature: float = 1.0) -> "NetworkStudent":
        from envs.observation import default_encoder, encoder_from_config
        from train.model import checkpoint_encoder_config, load_cvpn_model

        config = checkpoint_encoder_config(checkpoint)
        encoder = encoder_from_config(config) if config is not None else default_encoder()
        student = cls(model=load_cvpn_model(checkpoint), encoder=encoder, temperature=temperature)
        student.name = f"network:{checkpoint}"
        return student

    def store_distributions(self, store: Any, positions: Sequence[int], *, batch_size: int = 256) -> list[list[float]]:
        """Option distributions for stored samples (features exactly as trained on)."""
        import torch
        from torch.nn.utils.rnn import pad_sequence

        out: list[list[float]] = []
        self.model.eval()
        with torch.no_grad():
            for start in range(0, len(positions), batch_size):
                chunk = list(positions[start : start + batch_size])
                tokens = [store.tokens[i] for i in chunk]
                options = [store.options[i] for i in chunk]
                t_len = torch.tensor([t.shape[0] for t in tokens])
                k_len = torch.tensor([o.shape[0] for o in options])
                tok = pad_sequence(tokens, batch_first=True)
                opt = pad_sequence(options, batch_first=True)
                tok_mask = torch.arange(tok.shape[1]).unsqueeze(0) < t_len.unsqueeze(1)
                opt_mask = torch.arange(opt.shape[1]).unsqueeze(0) < k_len.unsqueeze(1)
                logits, _value = self.model(tok, tok_mask, opt, opt_mask)
                probs = torch.softmax(logits / max(self.temperature, 1e-6), dim=-1)
                for row, k in enumerate(k_len.tolist()):
                    out.append([float(p) for p in probs[row, :k]])
        return out


def _normalise(scores: Sequence[float], n: int) -> list[float]:
    values = [float(v) for v in scores]
    if len(values) != n or not all(math.isfinite(v) for v in values):
        raise ValueError(f"scorer must return {n} finite scores, got {values!r}")
    top = max(values)
    weights = [math.exp(v - top) for v in values]
    total = sum(weights)
    return [w / total for w in weights]


def render_record(record: DecisionSupervision, *, kb: Any = None) -> str:
    """Prompt body for a stored decision. Uses only the record's info-safe fields."""
    lines = [f"request={record.request_type} round={record.round_number}", record.text]
    if kb is not None and record.knowledge:
        from reps.knowledge import render_units

        lines.append("applicable strategy notes (unverified text):")
        lines.append(render_units(kb, record.knowledge))
    lines.append("legal options:")
    lines.extend(option.text or f"[{option.index}] {option.kind}" for option in record.options)
    return "\n".join(line for line in lines if line)


def render_context(context: Any, *, describer: Any, kb: Any = None) -> tuple[str, list[str]]:
    """Prompt body and option texts for a live decision (acting player's view only)."""
    from reps.knowledge import matching_units, render_units

    options = [describer.describe_candidate(context, spec, index)
               for index, spec in enumerate(context.legal_low_level_specs)]
    view = context.player_view
    lines = [f"request={context.request_type.value} round={int(view.round_number) if view is not None else 0}"]
    if view is not None:
        lines.append(describer.describe_state(context))
    if kb is not None:
        units = matching_units(context)
        if units:
            lines.append("applicable strategy notes (unverified text):")
            lines.append(render_units(kb, units))
    lines.append("legal options:")
    lines.extend(options)
    return "\n".join(line for line in lines if line), options


class TextStudent:
    """A student that reads text. The scorer (e.g. an LLM call) is injected."""

    def __init__(self, scorer: Scorer, *, describer: Any = None, kb: Any = None, name: str = "text") -> None:
        self.scorer = scorer
        self.describer = describer
        self.kb = kb
        self.name = name

    def record_distribution(self, record: DecisionSupervision) -> list[float]:
        options = [option.text or f"[{option.index}] {option.kind}" for option in record.options]
        return _normalise(self.scorer(render_record(record, kb=self.kb), options), len(options))

    def distribution(self, built: Any) -> list[float]:
        if self.describer is None:
            raise ValueError("TextStudent.distribution needs a describer (train.evidence.default_describer)")
        prompt, options = render_context(built.context, describer=self.describer, kb=self.kb)
        return _normalise(self.scorer(prompt, options), len(options))


def evidence_agreement(
    choices: Mapping[tuple[Any, ...], int],
    records: Sequence[DecisionSupervision],
    *,
    alpha: float = 0.05,
    min_pairs: int = 8,
) -> dict[str, Any]:
    """Offline scores of a student's argmax choices against supervision records.

    ``choices`` maps ``record.store_key`` to the student's chosen option index.
    Reported, each with its ``n``:

    * ``expert_agreement``   -- share of decisions where the choice is the expert's;
    * ``verified_agreement`` -- on gate-passing decisions, share where the choice is
      the supported action;
    * ``mean_dq_of_choice``  -- where the choice was one of the evaluated candidates,
      mean paired ``Q(choice) - Q(expert)`` (0 when the choice *is* the expert's).

    These are consistency measures against Monte-Carlo evidence under its stated
    continuation policies. They are not playing strength.
    """
    n = expert_hits = 0
    verified_n = verified_hits = 0
    dq: list[float] = []
    for record in records:
        choice = choices.get(tuple(record.store_key))
        if choice is None:
            continue
        n += 1
        expert_hits += int(choice == record.expert_index)
        evidence = record.evidence
        if evidence is None:
            continue
        result = verdict(evidence, alpha=alpha, min_pairs=min_pairs)
        if result.verified:
            verified_n += 1
            verified_hits += int(choice == result.option_index)
        if choice == evidence.baseline_index:
            dq.append(0.0)
        else:
            for comparison in evidence.comparisons():
                if comparison.option_index == choice and comparison.n_pairs > 0:
                    dq.append(comparison.mean_diff)
    return {
        "n": n,
        "expert_agreement": round(expert_hits / n, 4) if n else None,
        "verified_n": verified_n,
        "verified_agreement": round(verified_hits / verified_n, 4) if verified_n else None,
        "dq_n": len(dq),
        "mean_dq_of_choice": round(sum(dq) / len(dq), 4) if dq else None,
    }
