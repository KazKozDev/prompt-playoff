from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from prompt_selector.checks import CheckConfigError, CheckRun, run_checks
from prompt_selector.domain import (
    CompileRequest,
    Constraints,
    ModelClass,
    ModelProfile,
    Priorities,
    RunRequest,
    TaskProfile,
    TaskShape,
    TaskType,
)
from prompt_selector.evals import BenchmarkReport, load_jsonl
from prompt_selector.graders import grader_names
from prompt_selector.lint import format_issues, has_errors, lint_registry, registry_summary
from prompt_selector.normalizer import parse_capabilities
from prompt_selector.optimizer import BACKENDS
from prompt_selector.registry import Registry
from prompt_selector.service import PromptSelectorService
from prompt_selector.strategies import aggregator_names, strategy_names

app = typer.Typer(no_args_is_help=True, help="Explainable prompt-technique selector.")
console = Console()

REPORT_DIR = Path("benchmark-results")


def _model(
    provider: str,
    model: str,
    model_class: ModelClass,
    capabilities: str,
    local: bool,
    base_url: str | None,
) -> ModelProfile:
    return ModelProfile(
        provider=provider,
        model_id=model,
        model_class=model_class,
        local=local,
        capabilities=parse_capabilities(capabilities),
        base_url=base_url,
    )


def _engine_model(
    model: str | None,
    provider: str | None,
    base_url: str | None,
) -> ModelProfile | None:
    """A profile of its own — the engine may be remote while the target is local."""
    if not model:
        return None
    resolved = provider or "ollama"
    return ModelProfile(
        provider=resolved,
        model_id=model,
        local=resolved == "ollama",
        base_url=base_url,
    )


def _shape(value: str) -> set[TaskShape]:
    try:
        return {TaskShape(item.strip()) for item in value.split(",") if item.strip()}
    except ValueError as exc:
        known = ", ".join(item.value for item in TaskShape)
        raise typer.BadParameter(f"{exc}. Known shapes: {known}") from None


def _task(
    task: TaskType,
    model: ModelProfile,
    strict_json: bool,
    priorities: Priorities | None = None,
    tools_allowed: bool = False,
    max_calls: int = 3,
    retrieval_required: bool = False,
    shape: str = "",
) -> TaskProfile:
    return TaskProfile(
        task_type=task,
        shape=_shape(shape),
        output_contract="json_schema" if strict_json else "free_text",
        priorities=priorities or Priorities(),
        constraints=Constraints(
            strict_json=strict_json,
            requires_validation=True,
            tools_allowed=tools_allowed or retrieval_required,
            retrieval_required=retrieval_required,
            max_calls=max_calls,
        ),
        model=model,
    )


def _print_selection(result) -> None:
    table = Table(title="Recommended techniques")
    table.add_column("Rank", justify="right")
    table.add_column("Technique")
    table.add_column("Family")
    table.add_column("Score", justify="right")
    table.add_column("Confidence", justify="right")
    table.add_column("Evidence")
    for index, item in enumerate(result.recommendations, 1):
        table.add_row(
            str(index),
            item.title,
            item.family,
            f"{item.score:.3f}",
            f"{item.confidence:.3f}",
            "measured" if item.evidence_source == "measured" else "prior",
        )
    console.print(table)
    for item in result.recommendations:
        console.print(f"\n[bold]{item.title}[/bold] ({item.technique_id})")
        for reason in item.reasons:
            console.print(f"  • {reason}")
    for warning in result.warnings:
        console.print(f"\n[yellow]Warning:[/yellow] {warning}")


def _print_program(program) -> None:
    console.print(
        f"[bold]{program.technique_title}[/bold] "
        f"({program.technique_id} v{program.technique_version})"
    )
    console.print(
        f"[dim]strategy[/dim] {program.strategy}  "
        f"[dim]calls[/dim] {program.expected_calls}  "
        f"[dim]validators[/dim] {', '.join(program.validators) or 'none'}"
    )
    for stage in program.stages:
        console.print(
            Panel(
                f"[dim]system[/dim]\n{stage.messages[0].content}\n\n"
                f"[dim]user[/dim]\n{stage.messages[1].content}",
                title=f"stage: {stage.stage}"
                + (
                    f"  (runtime: {', '.join('{' + p + '}' for p in stage.deferred_placeholders)})"
                    if stage.deferred_placeholders
                    else ""
                ),
                border_style="cyan",
            )
        )
    if program.response_schema:
        console.print("[dim]Native response schema is enforced by the provider.[/dim]")
    for note in program.notes:
        console.print(f"[yellow]note[/yellow] {note}")


def _print_report(report: BenchmarkReport) -> None:
    card = report.scorecard
    table = Table(title=f"Measured: {report.technique_title} on {report.model_id}")
    table.add_column("Metric")
    table.add_column("Measured", justify="right")
    table.add_column("Declared", justify="right")
    table.add_row("quality", f"{card.quality:.3f}", f"{report.declared.get('quality', 0):.3f}")
    table.add_row(
        "reliability", f"{card.reliability:.3f}", f"{report.declared.get('reliability', 0):.3f}"
    )
    table.add_row("contract pass rate", f"{card.contract_pass_rate:.3f}", "—")
    table.add_row("stability across repeats", f"{card.stability:.3f}", "—")
    table.add_row("mean latency (s)", f"{card.mean_latency_seconds:.3f}", "—")
    table.add_row("p95 latency (s)", f"{card.p95_latency_seconds:.3f}", "—")
    table.add_row("mean tokens", f"{card.mean_total_tokens:.1f}", "—")
    table.add_row("mean calls", f"{card.mean_calls:.2f}", "—")
    table.add_row("failures", str(card.failures), "—")
    console.print(table)

    grades = Table(title="Graders")
    grades.add_column("Grader")
    grades.add_column("Mean", justify="right")
    for name, value in sorted(card.grades.items()):
        marker = " (headline quality)" if name == card.quality_grader else ""
        grades.add_row(name + marker, f"{value:.3f}")
    console.print(grades)

    if report.prior is not None:
        console.print(
            f"\n[dim]Registry prior was {report.prior:.2f}; measured quality is "
            f"{card.quality:.2f} on {report.examples} examples × {report.repeats} repeats.[/dim]"
        )

    worst = sorted(report.runs, key=lambda run: min(run.grades.values(), default=1.0))[:3]
    if worst:
        console.print("\n[bold]Weakest examples[/bold]")
        for run in worst:
            detail = run.error or "; ".join(run.schema_errors) or ""
            console.print(
                f"  [dim]{run.example_id}[/dim] {run.grades} {detail}\n"
                f"    {run.output[:160].replace(chr(10), ' ')}"
            )


def _print_check_run(run: CheckRun) -> None:
    for check in run.checks:
        table = Table(title=f"Check: {check.name} [{check.status}]")
        table.add_column("Metric")
        table.add_column("Measured", justify="right")
        table.add_column("Required", justify="right")
        table.add_column("Verdict")
        if check.error:
            table.add_row("setup", "—", "—", check.error)
        for threshold in check.thresholds:
            operator = ">=" if threshold.bound == "min" else "<="
            if threshold.passed:
                verdict = "PASS"
            else:
                breach = abs(threshold.difference)
                verdict = f"FAIL by {breach:.6g}"
            table.add_row(
                threshold.field,
                f"{threshold.measured:.6g}",
                f"{operator} {threshold.required:.6g}",
                verdict,
            )
        console.print(table)
    if run.updated:
        console.print(f"[green]Updated requirements in {run.config}.[/green]")


@app.command()
def recommend(
    description: Annotated[str, typer.Argument(help="Describe the LLM task and constraints.")],
    model: Annotated[str, typer.Option(help="Model name.")] = "unknown",
    provider: Annotated[str, typer.Option(help="Provider id.")] = "ollama",
    model_class: Annotated[
        ModelClass, typer.Option(help="Approximate model class.")
    ] = ModelClass.medium,
    capabilities: Annotated[
        str, typer.Option(help="Comma-separated capability names.")
    ] = "system_messages",
    local: Annotated[bool, typer.Option(help="Whether execution is local.")] = True,
    base_url: Annotated[str | None, typer.Option(help="Custom provider base URL.")] = None,
    engine_model: Annotated[
        str | None,
        typer.Option(help="Model that reads the description. Never the model under test."),
    ] = None,
    engine_provider: Annotated[str | None, typer.Option(help="Engine provider id.")] = None,
    engine_base_url: Annotated[str | None, typer.Option(help="Engine provider base URL.")] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable JSON.")
    ] = False,
) -> None:
    """Rank techniques for a task described in plain language, with the reasons for each."""
    service = PromptSelectorService(Registry.load())
    result, normalization = asyncio.run(
        service.recommend(
            description=description,
            model=_model(provider, model, model_class, capabilities, local, base_url),
            engine_model=_engine_model(engine_model, engine_provider, engine_base_url),
        )
    )
    if json_output:
        console.print_json(result.model_dump_json())
    else:
        console.print(f"[dim]Task profile read by: {normalization.source}[/dim]")
        console.print_json(normalization.profile.model_dump_json())
        _print_selection(result)


@app.command("select")
def select_command(
    task: Annotated[TaskType, typer.Option(help="Task type.")],
    model: Annotated[str, typer.Option(help="Model name.")] = "unknown",
    provider: Annotated[str, typer.Option(help="Provider id.")] = "ollama",
    model_class: Annotated[ModelClass, typer.Option()] = ModelClass.medium,
    capabilities: Annotated[str, typer.Option()] = "system_messages",
    strict_json: Annotated[bool, typer.Option()] = False,
    tools_allowed: Annotated[bool, typer.Option()] = False,
    retrieval_required: Annotated[
        bool,
        typer.Option(help="The material to answer from has to be fetched, not pasted."),
    ] = False,
    shape: Annotated[
        str,
        typer.Option(
            help="Comma-separated request traits, e.g. multi_step,verifiable. "
            "This is what makes two tasks of the same type rank differently."
        ),
    ] = "",
    local_only: Annotated[bool, typer.Option()] = False,
    max_calls: Annotated[int, typer.Option(min=1, max=20)] = 3,
    quality: Annotated[float, typer.Option(min=0)] = 0.35,
    reliability: Annotated[float, typer.Option(min=0)] = 0.35,
    latency: Annotated[float, typer.Option(min=0)] = 0.15,
    token_cost: Annotated[float, typer.Option(min=0)] = 0.15,
    base_url: Annotated[str | None, typer.Option()] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Rank techniques from a task profile given as options, skipping description parsing."""
    model_profile = _model(
        provider, model, model_class, capabilities, local_only or provider == "ollama", base_url
    )
    profile = _task(
        task,
        model_profile,
        strict_json,
        Priorities(
            quality=quality, reliability=reliability, latency=latency, token_cost=token_cost
        ),
        tools_allowed,
        max_calls,
        retrieval_required,
        shape,
    )
    profile.constraints.local_only = local_only
    result = PromptSelectorService(Registry.load()).select(profile)
    if json_output:
        console.print_json(result.model_dump_json())
    else:
        _print_selection(result)


@app.command("select-file")
def select_file(
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Rank techniques from a TaskProfile saved as JSON."""
    profile = TaskProfile.model_validate_json(path.read_text(encoding="utf-8"))
    _print_selection(PromptSelectorService(Registry.load()).select(profile))


@app.command("compile")
def compile_command(
    task: Annotated[TaskType, typer.Option()],
    input_file: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    model: Annotated[str, typer.Option()] = "unknown",
    provider: Annotated[str, typer.Option()] = "ollama",
    model_class: Annotated[ModelClass, typer.Option()] = ModelClass.medium,
    capabilities: Annotated[str, typer.Option()] = "system_messages",
    schema_file: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    technique: Annotated[str | None, typer.Option()] = None,
    variables: Annotated[str | None, typer.Option(help="JSON object of recipe variables.")] = None,
    tools_allowed: Annotated[bool, typer.Option()] = False,
    retrieval_required: Annotated[
        bool,
        typer.Option(help="The material to answer from has to be fetched, not pasted."),
    ] = False,
    shape: Annotated[
        str,
        typer.Option(
            help="Comma-separated request traits, e.g. multi_step,verifiable. "
            "This is what makes two tasks of the same type rank differently."
        ),
    ] = "",
    base_url: Annotated[str | None, typer.Option()] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Build the prompt a technique implies, stage by stage, without calling a model."""
    schema = json.loads(schema_file.read_text(encoding="utf-8")) if schema_file else None
    profile = _task(
        task,
        _model(provider, model, model_class, capabilities, provider == "ollama", base_url),
        bool(schema),
        tools_allowed=tools_allowed,
        retrieval_required=retrieval_required,
        shape=shape,
    )
    request = CompileRequest(
        task=profile,
        user_input=input_file.read_text(encoding="utf-8"),
        response_schema=schema,
        technique_id=technique,
        variables=json.loads(variables) if variables else {},
    )
    program = PromptSelectorService(Registry.load()).compile(request)
    if json_output:
        console.print_json(program.model_dump_json())
    else:
        _print_program(program)


@app.command("run")
def run_command(
    task: Annotated[TaskType, typer.Option()],
    input_file: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    model: Annotated[str, typer.Option()],
    provider: Annotated[str, typer.Option()] = "ollama",
    model_class: Annotated[ModelClass, typer.Option()] = ModelClass.medium,
    capabilities: Annotated[str, typer.Option()] = "system_messages",
    schema_file: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    technique: Annotated[str | None, typer.Option()] = None,
    tools_allowed: Annotated[bool, typer.Option()] = False,
    base_url: Annotated[str | None, typer.Option()] = None,
    timeout_seconds: Annotated[float, typer.Option(min=1)] = 120,
) -> None:
    """Compile and execute once against a live model, reporting calls, latency and tokens."""
    schema = json.loads(schema_file.read_text(encoding="utf-8")) if schema_file else None
    profile = _task(
        task,
        _model(provider, model, model_class, capabilities, provider == "ollama", base_url),
        bool(schema),
        tools_allowed=tools_allowed,
    )
    request = RunRequest(
        task=profile,
        user_input=input_file.read_text(encoding="utf-8"),
        response_schema=schema,
        technique_id=technique,
        timeout_seconds=timeout_seconds,
    )
    trace = asyncio.run(PromptSelectorService(Registry.load()).run(request))
    console.print(trace.output)
    console.print(
        f"\n[dim]{len(trace.calls)} call(s), {trace.latency_seconds:.2f}s, "
        f"{trace.total_tokens} tokens[/dim]"
    )
    if trace.aggregation:
        console.print_json(json.dumps(trace.aggregation, ensure_ascii=False))


@app.command("benchmark")
def benchmark_command(
    model: Annotated[str, typer.Option()],
    dataset: Annotated[str | None, typer.Option(help="Built-in dataset name.")] = None,
    dataset_file: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    task: Annotated[TaskType, typer.Option()] = TaskType.structured_extraction,
    provider: Annotated[str, typer.Option()] = "ollama",
    model_class: Annotated[ModelClass, typer.Option()] = ModelClass.medium,
    capabilities: Annotated[str, typer.Option()] = "structured_output,system_messages",
    technique: Annotated[str | None, typer.Option()] = None,
    repeats: Annotated[
        int, typer.Option(min=1, max=10, help="Repeats per example; >1 measures stability.")
    ] = 1,
    strict_json: Annotated[bool, typer.Option()] = True,
    tools_allowed: Annotated[
        bool, typer.Option(help="Expose registered deterministic tools to tool-using techniques.")
    ] = False,
    base_url: Annotated[str | None, typer.Option()] = None,
    timeout_seconds: Annotated[float, typer.Option(min=1)] = 120,
    save: Annotated[bool, typer.Option(help="Write the full report to benchmark-results/.")] = True,
    record: Annotated[bool, typer.Option(help="Feed the result back into ranking.")] = True,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Measure one technique on a dataset: quality, reliability, stability, latency, tokens."""
    service = PromptSelectorService(Registry.load())
    profile = _task(
        task,
        _model(provider, model, model_class, capabilities, provider == "ollama", base_url),
        strict_json,
        tools_allowed=tools_allowed,
    )
    inline = load_jsonl(dataset_file) if dataset_file else None
    name = dataset_file.stem if dataset_file else dataset
    if inline is None and name is None:
        raise typer.BadParameter("Provide --dataset or --dataset-file")

    with console.status("Running against the model…"):
        report = asyncio.run(
            service.benchmark(
                task=profile,
                technique_id=technique,
                dataset_name=None if inline else name,
                inline=inline,
                repeats=repeats,
                timeout_seconds=timeout_seconds,
                record=record,
            )
        )
    if inline:
        report.dataset = name or "inline"

    if json_output:
        console.print_json(report.model_dump_json())
    else:
        _print_report(report)
    if save:
        path = service.save_report(report, REPORT_DIR)
        console.print(f"\n[green]Report written to[/green] {path}")
    if record:
        console.print("[dim]Measurement recorded; future rankings will use it.[/dim]")


@app.command("check")
def check_command(
    config: Annotated[
        Path,
        typer.Option(help="Committed expectation file."),
    ] = Path("prompt-selector.yaml"),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print one machine-readable result."),
    ] = False,
    update: Annotated[
        bool,
        typer.Option(help="Replace require values with the current measurements."),
    ] = False,
    no_record: Annotated[
        bool,
        typer.Option("--no-record", help="Do not add these measurements to the evidence store."),
    ] = False,
) -> None:
    """Re-measure committed expectations and fail CI on regression."""
    if json_output and update:
        console.print("--update cannot be combined with --json; run one mode at a time")
        raise typer.Exit(code=2)
    try:
        result = asyncio.run(run_checks(config, record=not no_record, update=update))
    except CheckConfigError as exc:
        if json_output:
            console.print_json(
                json.dumps(
                    {
                        "status": "error",
                        "exit_code": 2,
                        "config": str(config),
                        "checks": [],
                        "error": str(exc),
                    }
                )
            )
        else:
            console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from None
    if json_output:
        console.print_json(result.model_dump_json())
    else:
        _print_check_run(result)
    if result.exit_code:
        raise typer.Exit(code=result.exit_code)


@app.command("compare")
def compare_command(
    model: Annotated[str, typer.Option()],
    techniques: Annotated[str, typer.Option(help="Comma-separated technique ids.")],
    dataset: Annotated[str | None, typer.Option()] = None,
    dataset_file: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    task: Annotated[TaskType, typer.Option()] = TaskType.structured_extraction,
    provider: Annotated[str, typer.Option()] = "ollama",
    model_class: Annotated[ModelClass, typer.Option()] = ModelClass.medium,
    capabilities: Annotated[str, typer.Option()] = "structured_output,system_messages",
    repeats: Annotated[int, typer.Option(min=1, max=10)] = 1,
    strict_json: Annotated[bool, typer.Option()] = True,
    tools_allowed: Annotated[
        bool, typer.Option(help="Expose registered deterministic tools to tool-using techniques.")
    ] = False,
    quality: Annotated[float, typer.Option(min=0)] = 0.35,
    reliability: Annotated[float, typer.Option(min=0)] = 0.35,
    latency: Annotated[float, typer.Option(min=0)] = 0.15,
    token_cost: Annotated[float, typer.Option(min=0)] = 0.15,
    base_url: Annotated[str | None, typer.Option()] = None,
    timeout_seconds: Annotated[float, typer.Option(min=1)] = 120,
    save: Annotated[bool, typer.Option()] = True,
) -> None:
    """Measure several techniques on one dataset and rank them by your priorities."""
    service = PromptSelectorService(Registry.load())
    profile = _task(
        task,
        _model(provider, model, model_class, capabilities, provider == "ollama", base_url),
        strict_json,
        Priorities(
            quality=quality, reliability=reliability, latency=latency, token_cost=token_cost
        ),
        tools_allowed=tools_allowed,
    )
    inline = load_jsonl(dataset_file) if dataset_file else None
    ids = [item.strip() for item in techniques.split(",") if item.strip()]

    with console.status(f"Benchmarking {len(ids)} techniques…"):
        comparison, reports = asyncio.run(
            service.compare(
                task=profile,
                technique_ids=ids,
                dataset_name=None if inline else dataset,
                inline=inline,
                repeats=repeats,
                timeout_seconds=timeout_seconds,
            )
        )

    table = Table(title=f"Measured comparison on {comparison.model_id}")
    table.add_column("Technique")
    table.add_column("Weighted", justify="right")
    table.add_column("Quality", justify="right")
    table.add_column("Reliability", justify="right")
    table.add_column("Latency s", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Calls", justify="right")
    for entry in comparison.entries:
        table.add_row(
            entry.technique_id,
            f"{entry.weighted_score:.3f}",
            f"{entry.scorecard.quality:.3f}",
            f"{entry.scorecard.reliability:.3f}",
            f"{entry.scorecard.mean_latency_seconds:.2f}",
            f"{entry.scorecard.mean_total_tokens:.0f}",
            f"{entry.scorecard.mean_calls:.1f}",
        )
    console.print(table)
    console.print(f"[green]Winner:[/green] {comparison.winner}")
    console.print(f"[dim]{comparison.note}[/dim]")
    if save:
        for report in reports:
            service.save_report(report, REPORT_DIR)
        console.print(f"[dim]Full reports written to {REPORT_DIR}/[/dim]")


@app.command("optimize")
def optimize_command(
    model: Annotated[str, typer.Option()],
    dataset: Annotated[str | None, typer.Option()] = None,
    dataset_file: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    task: Annotated[TaskType, typer.Option()] = TaskType.structured_extraction,
    technique: Annotated[str | None, typer.Option()] = None,
    backend: Annotated[
        str, typer.Option(help="Search algorithm: native, dspy:mipro, dspy:gepa, dspy:bootstrap.")
    ] = "native",
    provider: Annotated[str, typer.Option()] = "ollama",
    model_class: Annotated[ModelClass, typer.Option()] = ModelClass.medium,
    capabilities: Annotated[str, typer.Option()] = "structured_output,system_messages",
    rounds: Annotated[int, typer.Option(min=1, max=6, help="native backend only")] = 2,
    candidates: Annotated[int, typer.Option(min=1, max=6, help="native backend only")] = 3,
    beam_width: Annotated[
        int,
        typer.Option(min=1, max=5, help="native backend only: parents mutated per round."),
    ] = 2,
    auto: Annotated[str, typer.Option(help="DSPy budget: light, medium, heavy.")] = "light",
    max_metric_calls: Annotated[int | None, typer.Option(help="DSPy rollout budget.")] = None,
    repeats: Annotated[int, typer.Option(min=1, max=5)] = 1,
    strict_json: Annotated[bool, typer.Option()] = True,
    tools_allowed: Annotated[
        bool, typer.Option(help="Expose registered deterministic tools to tool-using techniques.")
    ] = False,
    quality: Annotated[float, typer.Option(min=0)] = 0.4,
    reliability: Annotated[float, typer.Option(min=0)] = 0.3,
    latency: Annotated[float, typer.Option(min=0)] = 0.1,
    token_cost: Annotated[float, typer.Option(min=0)] = 0.2,
    optimizer_model: Annotated[
        str | None,
        typer.Option(help="Deprecated name for --engine-model."),
    ] = None,
    engine_model: Annotated[
        str | None,
        typer.Option(help="Model that proposes rewrites. Never the model under test."),
    ] = None,
    engine_provider: Annotated[str | None, typer.Option(help="Engine provider id.")] = None,
    engine_base_url: Annotated[str | None, typer.Option(help="Engine provider base URL.")] = None,
    base_url: Annotated[str | None, typer.Option()] = None,
    timeout_seconds: Annotated[float, typer.Option(min=1)] = 120,
    export: Annotated[
        Path | None, typer.Option(help="Write the winner as a technique YAML.")
    ] = None,
    export_front: Annotated[
        Path | None,
        typer.Option(help="Directory for every Pareto-front candidate, not just the winner."),
    ] = None,
) -> None:
    """Search for a better prompt using measured results as the fitness function."""
    if backend not in BACKENDS:
        raise typer.BadParameter(f"Unknown backend. Known: {', '.join(BACKENDS)}")
    service = PromptSelectorService(Registry.load())
    target_model = _model(
        provider, model, model_class, capabilities, provider == "ollama", base_url
    )
    profile = _task(
        task,
        target_model,
        strict_json,
        Priorities(
            quality=quality, reliability=reliability, latency=latency, token_cost=token_cost
        ),
        tools_allowed=tools_allowed,
    )
    inline = load_jsonl(dataset_file) if dataset_file else None
    if inline is None and not dataset:
        raise typer.BadParameter("Provide --dataset or --dataset-file")

    if optimizer_model and not engine_model:
        console.print("[yellow]--optimizer-model is deprecated; use --engine-model.[/yellow]")
    engine_profile = _engine_model(
        engine_model or optimizer_model, engine_provider, engine_base_url
    )

    def show(event: dict) -> None:
        console.print(f"[dim]{event}[/dim]")

    result = asyncio.run(
        service.optimize(
            task=profile,
            technique_id=technique,
            dataset_name=None if inline else dataset,
            inline=inline,
            backend=backend,
            rounds=rounds,
            candidates_per_round=candidates,
            beam_width=beam_width,
            repeats=repeats,
            timeout_seconds=timeout_seconds,
            engine_model=engine_profile,
            max_metric_calls=max_metric_calls,
            auto=auto,
            progress=show,
        )
    )
    _print_optimization(result, export, export_front)


def _print_optimization(result, export: Path | None, export_front: Path | None = None) -> None:
    table = Table(title=f"Held-out validation ({result.backend})")
    table.add_column("Metric")
    table.add_column("Baseline", justify="right")
    table.add_column("Optimized", justify="right")
    table.add_column("Delta", justify="right")
    base, best = result.baseline_validation, result.winner_validation
    for label, left, right in (
        ("quality", base.quality, best.quality),
        ("reliability", base.reliability, best.reliability),
        ("mean tokens", base.mean_total_tokens, best.mean_total_tokens),
        ("mean latency s", base.mean_latency_seconds, best.mean_latency_seconds),
    ):
        table.add_row(label, f"{left:.3f}", f"{right:.3f}", f"{right - left:+.3f}")
    console.print(table)
    # Without the per-candidate numbers you cannot tell a search that found
    # nothing from one whose winner lost on cost despite better answers.
    if result.rounds:
        search = Table(title="Search history (measured on the train split)")
        search.add_column("Round", justify="right")
        search.add_column("Candidate")
        search.add_column("Origin")
        search.add_column("Weighted", justify="right")
        search.add_column("Quality", justify="right")
        search.add_column("Tokens", justify="right")
        front = {item.id for item in result.pareto_front}
        for entry in result.rounds:
            for candidate in entry.evaluated:
                card = candidate.train
                marker = " ★" if candidate.id in front else ""
                search.add_row(
                    str(entry.round),
                    candidate.id + marker,
                    candidate.origin,
                    f"{candidate.score:.3f}" if candidate.score is not None else "—",
                    f"{card.quality:.3f}" if card else "—",
                    f"{card.mean_total_tokens:.0f}" if card else "—",
                )
        console.print(search)
        console.print("[dim]★ = on the Pareto front[/dim]")

    console.print(
        f"[green]Winner:[/green] {result.winner.id} ({result.winner.origin}) — "
        f"{result.total_calls} model calls, {result.elapsed_seconds}s, "
        f"train {result.train_size} / validation {result.validation_size}"
    )
    if result.pareto_front:
        console.print(
            f"[dim]Pareto front: {', '.join(item.id for item in result.pareto_front)}[/dim]"
        )
    for note in result.notes:
        console.print(f"[yellow]note[/yellow] {note}")

    for stage in result.compiled_prompt.get("stages", []):
        console.print(
            Panel(
                stage["user"],
                title=f"optimized prompt — stage {stage['stage']}",
                border_style="green",
            )
        )

    if export:
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_text(
            yaml.safe_dump(
                result.exported_technique, sort_keys=False, allow_unicode=True, width=100
            ),
            encoding="utf-8",
        )
        console.print(f"[green]Exported technique to[/green] {export}")

    if export_front:
        # The scalarized winner is not always the one you want: a candidate can be
        # both more accurate and cheaper and still lose on the weighted score.
        from prompt_selector.optimizer import export_front as build_front

        spec = Registry.load().technique(result.winner.technique_id)
        payloads = build_front(result, spec)
        export_front.mkdir(parents=True, exist_ok=True)
        for candidate in result.pareto_front:
            payload = payloads[candidate.id]
            path = export_front / f"{candidate.id.replace('+', '_')}.yaml"
            path.write_text(
                yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100),
                encoding="utf-8",
            )
            card = candidate.train
            console.print(
                f"  {path}  quality {card.quality:.3f}  tokens {card.mean_total_tokens:.0f}"
                if card
                else f"  {path}"
            )


@app.command("export-promptfoo")
def export_promptfoo_command(
    techniques: Annotated[str, typer.Option(help="Comma-separated technique ids.")],
    models: Annotated[str, typer.Option(help="Comma-separated model ids.")],
    dataset: Annotated[str | None, typer.Option()] = None,
    dataset_file: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    task: Annotated[TaskType, typer.Option()] = TaskType.structured_extraction,
    provider: Annotated[str, typer.Option()] = "ollama",
    model_class: Annotated[ModelClass, typer.Option()] = ModelClass.medium,
    capabilities: Annotated[str, typer.Option()] = "structured_output,system_messages",
    strict_json: Annotated[bool, typer.Option()] = True,
    base_url: Annotated[str | None, typer.Option()] = None,
    output: Annotated[Path, typer.Option(help="Directory to write the project into.")] = Path(
        "promptfoo"
    ),
) -> None:
    """Write a promptfoo project: same prompts, same graders, run in their harness."""
    service = PromptSelectorService(Registry.load())
    model_ids = [item.strip() for item in models.split(",") if item.strip()]
    profiles = [
        _model(provider, model_id, model_class, capabilities, provider == "ollama", base_url)
        for model_id in model_ids
    ]
    profile = _task(task, profiles[0], strict_json)
    inline = load_jsonl(dataset_file) if dataset_file else None
    if inline is None and not dataset:
        raise typer.BadParameter("Provide --dataset or --dataset-file")

    result = service.export_promptfoo(
        directory=output,
        task=profile,
        technique_ids=[item.strip() for item in techniques.split(",") if item.strip()],
        dataset_name=None if inline else dataset,
        inline=inline,
        models=profiles,
    )
    console.print(f"[green]Wrote[/green] {result.config_path}")
    for path in result.prompt_paths:
        console.print(f"  prompt  {path}")
    console.print(f"  asserts {result.bridge_path}")
    for warning in result.warnings:
        console.print(f"[yellow]warning[/yellow] {warning}")
    console.print(f"\nRun it with:\n  cd {output} && promptfoo eval && promptfoo view")


@app.command("import-traces")
def import_traces_command(
    output: Annotated[Path, typer.Option(help="JSONL dataset to write.")],
    source: Annotated[str, typer.Option(help="Trace backend to read from.")] = "langfuse",
    limit: Annotated[int, typer.Option(min=1, max=1000)] = 100,
    technique: Annotated[str | None, typer.Option(help="Filter by technique id.")] = None,
    session: Annotated[str | None, typer.Option()] = None,
    user: Annotated[str | None, typer.Option()] = None,
    tags: Annotated[str | None, typer.Option(help="Comma-separated trace tags.")] = None,
    output_as_expected: Annotated[
        bool,
        typer.Option(
            help="Record what the model produced as the gold answer. "
            "Only honest for reviewed traffic."
        ),
    ] = False,
) -> None:
    """Turn observed production calls into a benchmark dataset."""
    if source != "langfuse":
        raise typer.BadParameter("Only 'langfuse' can read traces back out today.")
    from prompt_selector.integrations.tracing import import_langfuse_dataset, write_jsonl

    examples = import_langfuse_dataset(
        limit=limit,
        technique_id=technique,
        session_id=session,
        user_id=user,
        tags=[item.strip() for item in tags.split(",")] if tags else None,
        include_output_as_expected=output_as_expected,
    )
    if not examples:
        console.print("[yellow]No matching generations found.[/yellow]")
        raise typer.Exit(code=1)
    count = write_jsonl(output, examples)
    console.print(f"[green]Wrote {count} examples to[/green] {output}")
    if not output_as_expected:
        console.print(
            "[dim]`expected` is null on every row: fill it in before treating the "
            "quality number as meaningful.[/dim]"
        )


@app.command("import-hf")
def import_hf_command(
    preset: Annotated[
        str,
        typer.Argument(
            help="Dataset preset: multiconer-en, few-nerd, gsm8k, mbpp. "
            "Run list-hf-presets for their shape and licence."
        ),
    ],
    output: Annotated[Path, typer.Option(help="JSONL dataset to write.")],
    limit: Annotated[int, typer.Option(min=2, max=5000)] = 200,
    empty_ratio: Annotated[
        float, typer.Option(min=0, max=0.5, help="Share of examples with no entities.")
    ] = 0.1,
    scan: Annotated[int, typer.Option(min=10, help="Rows to read before sampling.")] = 4000,
) -> None:
    """Convert a Hugging Face corpus — entities, questions or code — into a benchmark dataset."""
    from prompt_selector.integrations.huggingface import (
        CODE_PRESETS,
        PRESETS,
        QA_PRESETS,
        convert,
        convert_code,
        convert_qa,
    )
    from prompt_selector.integrations.tracing import write_jsonl

    if preset in CODE_PRESETS:
        with console.status(f"Downloading and converting {CODE_PRESETS[preset].repo_id}…"):
            examples, spec = convert_code(preset, limit=limit, scan=scan)
    elif preset in QA_PRESETS:
        with console.status(f"Downloading and converting {QA_PRESETS[preset].repo_id}…"):
            examples, spec = convert_qa(preset, limit=limit, scan=scan)
    elif preset in PRESETS:
        with console.status(f"Downloading and converting {PRESETS[preset].repo_id}…"):
            examples, spec = convert(preset, limit=limit, empty_ratio=empty_ratio, scan=scan)
    else:
        known = sorted({*PRESETS, *QA_PRESETS, *CODE_PRESETS})
        raise typer.BadParameter(f"Known presets: {', '.join(known)}")
    count = write_jsonl(output, examples)

    console.print(f"[green]Wrote {count} examples to[/green] {output}")
    if hasattr(spec, "fields"):
        shape = f"fields: {', '.join(spec.fields)}"
    elif hasattr(spec, "tests_column"):
        shape = "task -> code, graded by running its tests"
    else:
        shape = f"question -> {'number' if spec.numeric else 'text'}"
    console.print(f"[dim]{spec.repo_id} · {spec.config} · {spec.split} · {shape}[/dim]")
    console.print(f"[yellow]licence[/yellow] {spec.licence}")
    console.print(f"[yellow]cite[/yellow] {spec.citation}")
    for note in spec.notes:
        console.print(f"[yellow]note[/yellow] {note}")


@app.command("list-hf-presets")
def list_hf_presets() -> None:
    """Hugging Face corpora that convert cleanly into benchmark examples."""
    from prompt_selector.integrations.huggingface import CODE_PRESETS, PRESETS, QA_PRESETS

    table = Table(title="Hugging Face presets")
    table.add_column("Preset")
    table.add_column("Dataset")
    table.add_column("Shape")
    table.add_column("Licence")
    for name, spec in sorted(PRESETS.items()):
        table.add_row(name, spec.repo_id, ", ".join(spec.fields), spec.licence)
    for name, qa in sorted(QA_PRESETS.items()):
        table.add_row(name, qa.repo_id, "question -> number", qa.licence)
    for name, code in sorted(CODE_PRESETS.items()):
        table.add_row(name, code.repo_id, "task -> code, run its tests", code.licence)
    console.print(table)


@app.command("tracing-status")
def tracing_status() -> None:
    """Show which tracing backend is active and whether its dependency is present."""
    import importlib.util
    import os

    backend = os.getenv("PROMPT_SELECTOR_TRACING", "none")
    table = Table(title="Tracing")
    table.add_column("Setting")
    table.add_column("Value")
    table.add_row("PROMPT_SELECTOR_TRACING", backend)
    table.add_row("langfuse installed", str(importlib.util.find_spec("langfuse") is not None))
    table.add_row(
        "opentelemetry installed", str(importlib.util.find_spec("opentelemetry.sdk") is not None)
    )
    table.add_row("dspy installed", str(importlib.util.find_spec("dspy") is not None))
    for key in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
        value = os.getenv(key)
        table.add_row(key, "set" if value else "unset")
    console.print(table)


@app.command("list-techniques")
def list_techniques() -> None:
    """List every technique with its strategy, call count and evidence level."""
    table = Table(title="Technique registry")
    table.add_column("ID")
    table.add_column("Family")
    table.add_column("Strategy")
    table.add_column("Calls", justify="right")
    table.add_column("Strong tasks")
    table.add_column("Evidence")
    for item in sorted(Registry.load().techniques.values(), key=lambda value: value.id):
        table.add_row(
            item.id,
            item.family,
            item.execution.strategy,
            str(item.min_calls),
            ", ".join(sorted(task.value for task in item.strong_tasks)),
            item.evidence_level.value,
        )
    console.print(table)


@app.command("list-datasets")
def list_datasets() -> None:
    """List benchmark datasets: how many examples, and how many carry gold answers."""
    service = PromptSelectorService(Registry.load())
    table = Table(title="Benchmark datasets")
    table.add_column("Name")
    table.add_column("Examples", justify="right")
    table.add_column("With expected", justify="right")
    table.add_column("With schema", justify="right")
    for name in sorted(service.registry.datasets):
        examples = service.dataset(name)
        table.add_row(
            name,
            str(len(examples)),
            str(sum(1 for item in examples if item.expected is not None)),
            str(sum(1 for item in examples if item.response_schema is not None)),
        )
    console.print(table)


@app.command("capabilities")
def capabilities_command() -> None:
    """Everything a new technique YAML may reference."""
    registry = Registry.load()
    payload = {
        **registry_summary(registry),
        "aggregators": aggregator_names(),
    }
    console.print_json(json.dumps(payload, indent=2))


@app.command("validate-registry")
def validate_registry(
    strict: Annotated[bool, typer.Option(help="Fail on warnings too.")] = False,
) -> None:
    """Check every technique file: placeholders, strategies, graders, render probe."""
    registry = Registry.load()
    issues = lint_registry(registry)
    console.print(
        f"[bold]{len(registry.techniques)}[/bold] techniques, "
        f"[bold]{len(registry.models)}[/bold] model profiles, "
        f"[bold]{len(registry.datasets)}[/bold] datasets, "
        f"strategies: {', '.join(strategy_names())}"
    )
    console.print(format_issues(issues))
    if has_errors(issues) or (strict and issues):
        raise typer.Exit(code=1)
    console.print("[green]Registry valid.[/green]")


@app.command("new-technique")
def new_technique(
    technique_id: Annotated[str, typer.Argument(help="e.g. structured.my-technique")],
    title: Annotated[str, typer.Option()] = "New technique",
    family: Annotated[str, typer.Option()] = "custom",
    strategy: Annotated[str, typer.Option()] = "single",
    task: Annotated[TaskType, typer.Option()] = TaskType.structured_extraction,
    output: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Scaffold a technique file. Adding one never requires touching Python."""
    if strategy not in strategy_names():
        raise typer.BadParameter(f"Unknown strategy. Known: {', '.join(strategy_names())}")
    payload = {
        "id": technique_id,
        "version": "1.0.0",
        "title": title,
        "family": family,
        "description": "Describe when this technique wins and when it does not.",
        "strong_tasks": [task.value],
        "acceptable_tasks": [],
        "avoid_tasks": [],
        "suits": [TaskShape.verifiable.value],
        "required_capabilities": ["system_messages"],
        "model_classes": ["small", "medium", "large", "reasoning"],
        "min_calls": 1,
        "tools_required": False,
        "strict_json_fit": False,
        "validation_fit": True,
        "characteristics": {
            "quality": 0.7,
            "reliability": 0.7,
            "latency_efficiency": 0.8,
            "token_efficiency": 0.8,
            "simplicity": 0.8,
        },
        "recipe": {
            "system": "One sentence stating the behaviour this technique enforces.",
            "instructions": ["Step one.", "Step two."],
            "blocks": [
                {"name": "role", "title": "OBJECTIVE", "body": "Perform this {task_type} task.\n"},
                {"name": "rules", "title": "RULES", "body": "{instructions}\n"},
                {
                    "name": "contract_embedded",
                    "title": "OUTPUT CONTRACT",
                    "when": "embedded_schema",
                    "body": "Return JSON matching:\n{schema_json}\n",
                },
                {"name": "input", "title": "INPUT", "body": "{input}\n"},
            ],
            "validators": [],
            "fallback": "What to do when validation fails.",
        },
        "execution": {"strategy": strategy},
        "benchmark_priors": {"default": 0.7},
        "evidence_level": "heuristic",
        "tags": [],
    }
    destination = output or Path(
        f"src/prompt_selector/data/techniques/{technique_id.split('.')[-1]}.yaml"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8"
    )
    console.print(f"[green]Wrote[/green] {destination}")
    console.print(
        "Placeholders available: "
        + ", ".join(f"{{{name}}}" for name in sorted(_placeholder_help()))
    )
    console.print(f"Graders you can list as validators: {', '.join(grader_names())}")
    console.print("Now run: [bold]prompt-selector validate-registry[/bold]")


def _placeholder_help() -> set[str]:
    from prompt_selector.templating import BASE_PLACEHOLDERS, DEFERRED_PLACEHOLDERS

    return set(BASE_PLACEHOLDERS) | set(DEFERRED_PLACEHOLDERS)


@app.command("show-technique")
def show_technique(technique_id: Annotated[str, typer.Argument()]) -> None:
    """Print one technique's full specification as YAML."""
    spec = Registry.load().technique(technique_id)
    console.print(
        Syntax(
            yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
            "yaml",
        )
    )


@app.command()
def serve(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8000,
    reload: Annotated[bool, typer.Option()] = False,
) -> None:
    """Start the HTTP API and the web interface."""
    try:
        import fastapi  # noqa: F401
        import multipart  # noqa: F401
        import uvicorn
    except ModuleNotFoundError as exc:
        if exc.name in {"fastapi", "uvicorn", "multipart"}:
            console.print(
                "Server dependencies are missing; run: pip install 'prompt-selector[serve]'",
                style="red",
                markup=False,
            )
            raise typer.Exit(code=1) from None
        raise
    uvicorn.run("prompt_selector.api:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
