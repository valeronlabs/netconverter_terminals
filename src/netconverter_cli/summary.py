"""Plain job summaries shared by the one-shot CLI (#7) and the TUI job card (#27).

One model (``Summary``) is built from a ``GET /jobs/{id}`` payload (or a submit
receipt) and rendered two ways: ``plain_lines`` for the terminal (at most ten
lines unless every finding is asked for, ending with the next command) and
``scorecard`` for the full-screen app. Both use:

* one verdict vocabulary: ready / needs review / blocked, plus a one-line why;
* one severity scale: blocking / error / warning / info (the count buckets);
* counts derived from one list, so a "N findings: …" sentence always adds up;
* plain wording for server text: no check codes (BC1, CP3), "IR", "vacuous",
  "RAG" or "graph contribution", and no "push" on a validation.

Server text is data: it is made printable, single-line and capped before it is
shown. Nothing here calls the network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .catalog import NAMES

LIST_DEFAULT = 3
TEXT_MAX = 160
BUCKETS = ("blocker", "error", "warning", "info")
BUCKET_LABEL = {"blocker": "blocking", "error": "error", "warning": "warning", "info": "info"}
_PLURAL = {"blocker": ("blocking", "blocking"), "error": ("error", "errors"),
           "warning": ("warning", "warnings"), "info": ("info", "info")}
PENDING = frozenset({"queued", "processing", "running", "pending", "unknown"})
KIND_TITLE = {"convert": "Conversion", "validate": "Validation", "optimize": "Optimization",
              "analyze": "Validation"}

# Check codes -> what a reader understands (docs/architecture/checkpoints in the engine).
_CHECKS = {
    "BC1": "the access-rule reachability check", "BC2": "the NAT equivalence check",
    "BC3": "the shadowing check", "BC4": "the zone check",
    "CP0": "the parse coverage check", "CP1": "the object completeness check",
    "CP2": "the feature coverage check", "CP3": "the reference check",
    "CP4A": "the vendor rule check", "CP4B": "the automatic correction step",
    "CP4C": "the advisory review", "CP4": "the vendor rule check",
}
_CHECK = re.compile(r"\b(BC[1-4]|CP4[abc]|CP[0-4])\b", re.IGNORECASE)
_WORDING = [
    (re.compile(r"\bRAG confidence (?:of )?(0?\.\d+|1(?:\.0+)?)\b"),
     lambda m: f"knowledge-base match {round(float(m.group(1)) * 100)}%"),
    (re.compile(r"\bRAG confidence (?:of )?(\d{1,3})\s*%"), lambda m: f"knowledge-base match {m.group(1)}%"),
    (re.compile(r"\bRAG confidence\b"), lambda m: "knowledge-base match"),
    (re.compile(r"\bRAG\b"), lambda m: "knowledge base"),
    (re.compile(r"\bgraph contribution\b", re.IGNORECASE), lambda m: "relationship score"),
    (re.compile(r"\b(?:passed |was )?vacuous(?:ly)?(?: pass(?:ed)?)?\b", re.IGNORECASE),
     lambda m: "had nothing to test"),
    (re.compile(r"\bIR\b"), lambda m: "the parsed model"),
]
_PUSH = re.compile(r"\bpush(ed|ing|es)?\b", re.IGNORECASE)


def _printable(value) -> str:
    text = "".join(ch for ch in str(value) if ch.isprintable() or ch.isspace())
    return " ".join(text.split())


def plain(text, *, validate: bool = False) -> str:
    """Server text in plain words: printable, one line, no internal codes, capped."""
    text = _printable(text if text is not None else "")
    text = _CHECK.sub(lambda m: _CHECKS[m.group(1).upper()], text)
    for pattern, repl in _WORDING:
        text = pattern.sub(repl, text)
    text = re.sub(r"\bthe (\w+(?: \w+)?) (check|step|review) had nothing to test(?: on)?",
                  r"the \1 \2 had nothing to test", text)
    text = re.sub(r"\b(the|a) the\b", r"\1", text)
    text = text.replace("(the ", "(")
    if validate:
        text = _PUSH.sub(lambda m: "convert" + {"ed": "ed", "ing": "ing", "es": "s"}.get(m.group(1) or "", ""),
                         text)
    text = re.sub(r"\s+([:;,])", r"\1", text).strip()
    if text[:4] == "the ":
        text = "The " + text[4:]
    return text if len(text) <= TEXT_MAX else text[: TEXT_MAX - 1].rstrip() + "…"


def sentence_case(text: str) -> str:
    """'HTTP Management Exposed to Any Host' -> 'HTTP management exposed to any host'."""
    words = text.split(" ")
    out = words[:1]
    for word in words[1:]:
        core = word.strip("():,;.'\"")
        out.append(word.lower() if re.fullmatch(r"[A-Z][a-z]+(?:-[A-Z]?[a-z]+)*", core) else word)
    return " ".join(out)


def _int(value) -> int:
    return value if type(value) is int and value >= 0 else 0


def _name(code) -> str:
    return NAMES.get(code) or str(code or "—")


@dataclass
class Summary:
    job_id: str
    kind: str                      # convert | validate | optimize
    heading: str
    verdict: str | None = None     # ready | needs review | blocked
    why: str = ""
    status_line: str = ""          # pending stage, or why a job did not finish
    facts: str = ""
    counts: dict = field(default_factory=dict)   # bucket -> count; the one list the sentence uses
    findings: list = field(default_factory=list)  # [(bucket or "", text)]
    total: int = 0                 # findings that exist (≥ len(findings))
    bullets: bool = False          # reasons (convert) rather than graded findings
    hints: list = field(default_factory=list)
    next_cli: str = ""
    next_tui: str = ""


def _kind(job: dict, operation=None) -> str:
    kind = job.get("job_type") or operation or ""
    if isinstance(job.get("validation"), dict) or kind in {"validate", "analyze"}:
        return "validate"
    if isinstance(job.get("optimization"), dict) or kind == "optimize":
        return "optimize"
    return "convert"


def verdict_of(job: dict) -> str | None:
    """ready / needs review / blocked for a completed job; None otherwise.

    The server's ``ci_verdict`` when present, else the same rules
    (aws-netconverter.ai app/api/v1/public/ci_output.py).
    """
    status = str(job.get("status") or "").lower()
    if status != "completed":
        return None
    server = job.get("ci_verdict")
    if server in ("ready", "needs_review", "blocked"):
        return server.replace("_", " ")
    kind = _kind(job)
    if kind == "validate":
        digest = job.get("validation") if isinstance(job.get("validation"), dict) else {}
        issues = digest.get("validation_issues") if isinstance(digest.get("validation_issues"), dict) else {}
        opt = digest.get("optimizer_findings") if isinstance(digest.get("optimizer_findings"), dict) else {}
        if (_int(issues.get("blocker")) or _int(issues.get("blocking")) or _int(opt.get("blocker"))
                or str(digest.get("confidence_band") or "").lower() == "unsafe-to-push"):
            return "blocked"
        return "ready" if digest.get("ready_for_conversion") is True else "needs review"
    if kind == "optimize":
        counts = (job.get("optimization") or {}).get("findings") or {}
        if _int(counts.get("blocker")):
            return "blocked"
        return "needs review" if _int(counts.get("error")) else "ready"
    ts = str(job.get("translation_status") or "").lower()
    if str(job.get("job_status") or "").lower() == "blocked" or ts == "blocked":
        return "blocked"
    if ts in ("passed", "passed_with_warnings") and job.get("review_required") is not True:
        return "ready"
    return "needs review"


def _count_sentence(counts: dict) -> str:
    total = sum(counts.values())
    if not total:
        return "No findings."
    parts = [f"{n} {_PLURAL[b][n != 1]}" for b, n in counts.items() if n]
    return f"{total} finding{'s' if total != 1 else ''}: {', '.join(parts)}"


def sarif_findings(report) -> list:
    """Every finding of a ``findings.sarif`` report as (bucket, title)."""
    out = []
    runs = report.get("runs") if isinstance(report, dict) else None
    for run in runs if isinstance(runs, list) else []:
        results = run.get("results") if isinstance(run, dict) else None
        for result in results if isinstance(results, list) else []:
            if not isinstance(result, dict):
                continue
            props = result.get("properties") if isinstance(result.get("properties"), dict) else {}
            bucket = props.get("bucket")
            if bucket not in BUCKETS:
                bucket = {"error": "error", "warning": "warning"}.get(result.get("level"), "info")
            message = result.get("message") if isinstance(result.get("message"), dict) else {}
            out.append((bucket, str(message.get("text") or result.get("ruleId") or "finding")))
    rank = {b: i for i, b in enumerate(BUCKETS)}
    return sorted(out, key=lambda item: rank[item[0]])


def _finding_text(title, affected=None, *, validate=False) -> str:
    text = sentence_case(plain(title, validate=validate))
    if type(affected) is int and affected > 1:
        text += f" ({affected})"
    return text


def summarize(job, *, operation=None, names=None, file=None, findings=None) -> Summary:
    """The summary of a job payload, a submit receipt, or a list of jobs.

    ``names`` maps a vendor code to its name (``Catalog.name``); ``file`` is the
    configuration the command named, for the next command; ``findings`` is the
    complete list from ``sarif_findings`` when every finding was fetched.
    """
    name = names or _name
    if isinstance(job, list):
        return _jobs_summary(job, name)
    job = job if isinstance(job, dict) else {}
    job_id = str(job.get("job_id") or "?")
    kind = _kind(job, operation)
    status = str(job.get("status") or "unknown").lower()
    route = name(job.get("source_vendor")) if job.get("source_vendor") else ""
    target = job.get("target_vendor")
    if kind == "convert" and target and target != "n/a":
        route = f"{route} → {name(target)}" if route else name(target)
    progress = job.get("progress")
    progress = progress.get("percentage") if isinstance(progress, dict) else progress
    state = status + (f" {progress}%" if status in PENDING and type(progress) is int else "")
    parts = [f"{KIND_TITLE[kind]} {job_id}"] + ([route] if route else []) + [state]
    s = Summary(job_id, kind, " · ".join(parts))
    vendor = job.get("source_vendor") or "<vendor>"
    file_arg = file or "<file>"
    if status in PENDING and not {"source_vendor", "job_type", "translation_status", "progress"} & set(job):
        s.heading = f"{KIND_TITLE[kind]} {job_id} submitted · {status}"
    if status in PENDING:
        stage = job.get("stage_key") or job.get("stage")
        if isinstance(stage, str) and stage.strip() and stage != "complete":
            s.status_line = "Stage: " + plain(stage)
        s.next_cli = f"netconverter resume {job_id}"
        s.next_tui = "/status refreshes it"
        return s
    if status != "completed":
        reason = job.get("failure_reason") or job.get("block_reason")
        s.status_line = "Did not finish" + (f": {plain(reason)}" if reason else ".")
        s.next_cli = f"netconverter resume {job_id} --json"
        s.next_tui = "/jobs lists your jobs"
        return s
    s.verdict = verdict_of(job)
    if kind == "convert":
        _convert(s, job)
    elif kind == "validate":
        _validate(s, job, findings, vendor, file_arg)
    else:
        _optimize(s, job, findings)
    return s


def _convert(s: Summary, job: dict) -> None:
    blocking = [r for r in job.get("blocking_reasons") or [] if isinstance(r, str)]
    review = [r for r in job.get("review_reasons") or [] if isinstance(r, str)]
    reasons = blocking + review
    more = " or more" if job.get("reasons_truncated") else ""
    if s.verdict == "blocked":
        s.why = plain(blocking[0]) if blocking else "the conversion was stopped before output"
    elif s.verdict == "needs review":
        s.why = f"{len(reasons)}{more} item{'s' if len(reasons) != 1 else ''} to review" if reasons \
            else "a person should review the output"
    else:
        s.why = "passed the checks" + (f"; {len(reasons)} note{'s' if len(reasons) != 1 else ''}" if reasons else "")
    s.findings = [("", plain(r)) for r in reasons]
    s.total = len(reasons)
    s.bullets = True
    if job.get("reasons_truncated"):
        s.hints.append("More reasons are in the report: netconverter download")
    s.next_cli = "netconverter download"
    s.next_tui = "/download saves the configuration and report"


def _validate(s: Summary, job: dict, findings, vendor, file_arg) -> None:
    digest = job.get("validation") if isinstance(job.get("validation"), dict) else {}
    issues = digest.get("validation_issues") if isinstance(digest.get("validation_issues"), dict) else {}
    opt = digest.get("optimizer_findings") if isinstance(digest.get("optimizer_findings"), dict) else {}
    s.counts = {b: _int(issues.get(b)) + _int(opt.get(b)) for b in BUCKETS}
    gaps = digest.get("parse_gaps") if isinstance(digest.get("parse_gaps"), dict) else {}
    unparsed = _int(gaps.get("unparsed_lines"))
    pct = gaps.get("unparsed_percentage")
    facts = []
    if type(digest.get("confidence")) is int:
        facts.append(f"Score {digest['confidence']}/100")
    facts += [f"{_int(digest.get('objects'))} objects", f"{_int(digest.get('rules'))} rules",
              f"{unparsed} unparsed line{'s' if unparsed != 1 else ''}"
              + (f" ({pct:g}%)" if isinstance(pct, (int, float)) and not isinstance(pct, bool) and unparsed else "")]
    s.facts = " · ".join(facts)
    reasons = [plain(r, validate=True) for r in digest.get("not_ready_reasons") or [] if isinstance(r, str)]
    blockers = max(s.counts["blocker"], _int(issues.get("blocking")))
    if s.verdict == "blocked":
        s.why = (f"not ready to convert: {blockers} blocking issue{'s' if blockers != 1 else ''}" if blockers
                 else "not ready to convert" + (f": {reasons[0]}" if reasons else ""))
        s.next_cli = f"fix the blocking issues, then: netconverter validate {file_arg} --vendor {vendor}"
        s.next_tui = "Fix the blocking issues, then /validate again"
    elif s.verdict == "needs review":
        s.why = reasons[0] if reasons else "not ready to convert yet; review the findings"
        s.next_cli = "netconverter download"
        s.next_tui = "/download saves the full report"
    else:
        warnings = s.counts["error"] + s.counts["warning"]
        s.why = "no blocking issues" + (f"; {warnings} finding{'s' if warnings != 1 else ''} to review"
                                        if warnings else "")
        s.next_cli = f"netconverter convert {file_arg} --vendor {vendor} --to <target>"
        s.next_tui = "/convert migrates it"
    _graded(s, digest.get("top"), findings, validate=True)
    if unparsed:
        s.hints.append("Unparsed lines: netconverter query unparsed_lines")


def _optimize(s: Summary, job: dict, findings) -> None:
    digest = job.get("optimization") if isinstance(job.get("optimization"), dict) else {}
    counts = digest.get("findings") if isinstance(digest.get("findings"), dict) else {}
    s.counts = {b: _int(counts.get(b)) for b in BUCKETS}
    facts = [f"Score {digest['score']}/100"] if type(digest.get("score")) is int else []
    facts += [f"{_int(digest.get('objects'))} objects", f"{_int(digest.get('rules'))} rules"]
    s.facts = " · ".join(facts)
    if s.verdict == "blocked":
        n = s.counts["blocker"]
        s.why = f"{n} blocking finding{'s' if n != 1 else ''}"
    elif s.verdict == "needs review":
        n = s.counts["error"]
        s.why = f"{n} error{'s' if n != 1 else ''} to review"
    else:
        s.why = "no errors" + (f"; {s.counts['warning']} warning{'s' if s.counts['warning'] != 1 else ''}"
                               if s.counts["warning"] else "")
    s.next_cli = "netconverter download"
    s.next_tui = "/download saves the full report"
    _graded(s, digest.get("top"), findings)


def _graded(s: Summary, top, findings, *, validate=False) -> None:
    s.total = sum(s.counts.values())
    if findings is not None:
        s.findings = [(b, _finding_text(t, validate=validate)) for b, t in findings]
        s.total = max(s.total, len(s.findings))
        return
    rows = [t for t in top or [] if isinstance(t, dict)]
    s.findings = [(t.get("bucket") if t.get("bucket") in BUCKETS else "info",
                   _finding_text(t.get("title") or t.get("kind") or "finding", t.get("affected_count"),
                                 validate=validate)) for t in rows]


def _jobs_summary(jobs: list, name) -> Summary:
    s = Summary("", "jobs", f"{len(jobs)} recent job{'s' if len(jobs) != 1 else ''}")
    for job in jobs[:8]:
        if not isinstance(job, dict):
            continue
        kind = _kind(job)
        verdict = verdict_of(job) or str(job.get("status") or "unknown")
        s.findings.append(("", f"{job.get('job_id', '?')}  {kind:<9} {verdict}"))
    s.total = len(jobs)
    s.bullets = True
    s.next_cli = "netconverter resume JOB_ID"
    s.next_tui = "/resume JOB_ID follows a job"
    return s


def _finding_lines(s: Summary, limit, *, more_cli: str) -> list[str]:
    shown = s.findings if limit is None else s.findings[:limit]
    lines = []
    for bucket, text in shown:
        lines.append(f"  • {text}" if s.bullets or not bucket else f"  {BUCKET_LABEL[bucket]:<9} {text}")
    left = s.total - len(shown)
    if left > 0 and more_cli:
        lines.append(f"  … {left} more: {more_cli}")
    return lines


def plain_lines(s: Summary, *, all_findings: bool = False) -> list[str]:
    """The terminal summary: ≤10 lines by default, ending with ``Next: <command>``."""
    lines = [s.heading]
    if s.verdict:
        lines.append(f"Verdict: {s.verdict}" + (f" · {s.why}" if s.why else ""))
    if s.status_line:
        lines.append(s.status_line)
    if s.facts:
        lines.append(s.facts)
    if s.counts:
        lines.append(_count_sentence(s.counts))
    more = "" if s.kind == "jobs" else f"netconverter resume {s.job_id} --all"
    lines += _finding_lines(s, None if all_findings else LIST_DEFAULT, more_cli="" if all_findings else more)
    if all_findings and s.total > len(s.findings) and s.kind != "jobs":
        lines.append(f"  … {s.total - len(s.findings)} more are in the report: netconverter download")
    lines += s.hints
    lines.append(f"Next: {s.next_cli}")
    return lines


def scorecard(job, *, names=None, surface: str = "tui"):
    """The TUI job card body for a completed validate/optimize job (#27)."""
    from rich.console import Group
    from rich.text import Text

    from .palette import ERROR, FG, MUTED, SUCCESS, WARNING
    from .presentation import literal

    s = summarize(job, names=names)
    color = {"ready": SUCCESS, "needs review": WARNING, "blocked": ERROR}.get(s.verdict, MUTED)
    rows = []
    if s.verdict:
        line = Text.assemble((f" {s.verdict.upper()} ", f"bold on {color}"))
        if s.why:
            line.append("  ")
            line.append_text(literal(s.why, FG))
        rows.append(line)
    for text in (s.status_line, s.facts, _count_sentence(s.counts) if s.counts else ""):
        if text:
            rows.append(literal(text, FG))
    for bucket, text in s.findings[:LIST_DEFAULT]:
        style = {"blocker": ERROR, "error": ERROR, "warning": WARNING}.get(bucket, MUTED)
        line = Text(f"  {BUCKET_LABEL.get(bucket, ''):<9} ", style=style)
        line.append_text(literal(text, FG))
        rows.append(line)
    left = s.total - min(len(s.findings), LIST_DEFAULT)
    if left > 0:
        rows.append(literal(f"  … {left} more in the full report", MUTED))
    for hint in s.hints:
        rows.append(literal(hint.replace("netconverter query unparsed_lines", "/unparsed_lines"), MUTED))
    following = s.next_tui if surface == "tui" else s.next_cli
    rows.append(literal(f"Next: {following}", MUTED))
    if surface == "tui" and s.verdict and "/download" not in following:
        rows.append(literal("Full detail: /download saves the report", MUTED))
    return Group(*rows)
