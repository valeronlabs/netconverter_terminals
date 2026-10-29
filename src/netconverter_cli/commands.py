"""Small guided command language; no eval, subprocess, shell, or remote URLs."""

import json
import shlex

HELP = """/open "file.cfg" VENDOR_CODE        (vendor codes: run `netconverter capabilities`)
/convert {"target_vendor":"palo_alto_xml"}   /validate   /optimize
/cd FOLDER   /ls [FOLDER]   /dir   /pwd
/jobs   /resume [job_id]   /status   /target   /download   /refresh
/unused_objects   /routes   /interfaces   /policy   /nat
/dependencies {"object_name":"NAME"}
/flow {"source_ip":"192.0.2.1","destination_ip":"198.51.100.1","protocol":"tcp","destination_port":80}
Questions use the configured model to select a permitted operation. Sensitive parameters are entered through commands and go directly to NetConverter."""


def execute(controller, text):
    if not text.startswith("/"):
        op = controller.interpret(text)
        if op in {"convert", "flow", "dependencies"}:
            return {
                "requires_input": op,
                "instructions": "Use /"
                + op
                + " with explicit parameters. /help shows the format.",
            }
        text = "/" + op
    command, _, rest = text[1:].partition(" ")
    rest = rest.strip()
    if command == "help":
        return {"help": HELP}
    if command == "cd":
        return controller.change_folder(rest)
    if command in {"ls", "dir"}:
        return controller.list_folder(rest)
    if command == "pwd":
        return {"folder": str(controller.workspace.root)}
    if command == "open":
        parts = shlex.split(rest)
        if len(parts) != 2:
            raise ValueError('Use /open "filename" vendor')
        return controller.select(*parts)
    if command in {"analyze", "validate", "optimize", "convert"}:
        options = json.loads(rest) if rest else {}
        if not isinstance(options, dict):
            raise ValueError("Options must be a JSON object")
        return controller.submit(command, options)
    if command in {"status", "resume"}:
        return controller.resume(rest or None)
    if command == "jobs":
        return controller.client.jobs()
    if command in {"artifacts", "download"}:
        return controller.download()
    if command in {"refresh", "allowance"}:  # /allowance: the 0.4 name
        return controller.capabilities()
    if command == "target":
        return controller.target()
    if command in {
        "unused_objects",
        "routes",
        "interfaces",
        "policy",
        "nat",
        "dependencies",
        "flow",
        "unparsed_lines",
    }:
        args = json.loads(rest) if rest else {}
        if not isinstance(args, dict):
            raise ValueError("Arguments must be a JSON object")
        return controller.query(command, args)
    raise ValueError("Unsupported command; use /help")
