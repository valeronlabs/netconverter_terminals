"""A short guided tour of the client: what it does, how jobs and privacy work,
and how to wire it into AI assistants. Shared by `netconverter walkthrough`
and the TUI's /walkthrough so both say the same thing."""

import sys

# (title, lines). Lines starting with "$ " or "/" are commands and are shown
# as such; everything else is prose. Keep every step short enough for 80x24.
STEPS = [
    ("What NetConverter does", [
        "NetConverter migrates, validates and optimizes network configurations:",
        "Palo Alto, Fortinet, Cisco ASA and IOS-XE, Juniper, Aruba and more.",
        "This client runs on your machine. The conversion itself runs on",
        "NetConverter's servers as a job, and the results come back here.",
    ]),
    ("Your files stay in your folder", [
        "The client works inside one folder (your workspace) and never reads",
        "outside it. A configuration is uploaded only when you start a job, and",
        "results are saved next to it with a SHA-256 check before writing.",
        "Credentials live in your operating system's credential store.",
        "$ netconverter --workspace ~/migrations",
    ]),
    ("Sign in", [
        "Sign in once with your NetConverter account. A browser opens; on a",
        "machine without one, use a device code instead.",
        "$ netconverter login --clerk",
        "$ netconverter login --device",
        "$ netconverter whoami",
    ]),
    ("Run a job", [
        "Convert, validate or optimize a configuration in your workspace.",
        "Each job gets an ID; follow it, then download the files.",
        "Vendor codes for your account: netconverter capabilities",
        "$ netconverter convert edge-fw.conf --vendor cisco_asa --to palo_alto_set",
        "$ netconverter validate edge-fw.conf --vendor cisco_asa",
        "$ netconverter jobs",
        "$ netconverter resume <job-id>",
        "In the terminal app: /convert, /validate, /optimize, /jobs, /download.",
    ]),
    ("Use it from your AI assistant", [
        "The client is also a local MCP server (the bridge). Your AI assistant",
        "asks it to submit jobs and read results; the configuration goes",
        "straight from your disk to NetConverter, and the assistant sees",
        "summaries and file paths, not the configuration text.",
        "$ netconverter connect claude-code",
        "Also: claude-desktop, cursor, vscode, codex, gemini, windsurf, lmstudio.",
        "$ netconverter connect --all",
        "ChatGPT and claude.ai connect to NetConverter directly:",
        "$ netconverter connect chatgpt",
    ]),
    ("Plain-language questions (optional)", [
        "Inside the terminal app you can connect a model (Anthropic, OpenAI,",
        "Gemini or a local Ollama model) to ask questions in plain words.",
        "The model only picks an operation; your configuration never goes to it.",
        "/model",
    ]),
    ("Help and license", [
        "/help lists every command. `netconverter <command> --help` explains one.",
        "The client is licensed for use with your NetConverter account only;",
        "it may not be redistributed.",
        "$ netconverter license show",
        "Questions: contact@netconverter.ai",
    ]),
]


def render_text(step_index: int) -> str:
    title, lines = STEPS[step_index]
    head = f"Step {step_index + 1} of {len(STEPS)} · {title}"
    body = "\n".join(("    " + line[2:]) if line.startswith("$ ") else ("  " + line) for line in lines)
    return f"{head}\n{'-' * len(head)}\n{body}\n"


def run(args, ask=input, out=print) -> int:
    """`netconverter walkthrough [STEP] [--all]`."""
    step = getattr(args, "step", None)
    if step is not None:
        if not 1 <= step <= len(STEPS):
            out(f"netconverter: choose a step from 1 to {len(STEPS)}.")
            return 2
        out(render_text(step - 1))
        return 0
    if getattr(args, "all", False) or not sys.stdin.isatty():
        for index in range(len(STEPS)):
            out(render_text(index))
        return 0
    for index in range(len(STEPS)):
        out(render_text(index))
        if index == len(STEPS) - 1:
            break
        try:
            answer = ask("Enter for the next step, q to stop: ")
        except (EOFError, KeyboardInterrupt):
            out("")
            return 0
        if answer.strip().lower() in {"q", "quit", "exit"}:
            return 0
        out("")
    out("That's the tour. Run `netconverter` to open the terminal app, or /walkthrough inside it.")
    return 0
