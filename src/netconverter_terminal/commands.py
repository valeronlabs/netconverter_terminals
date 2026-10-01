"""Small guided command language; no eval, subprocess, shell, or remote URLs."""

import json
import shlex

HELP = """/open "file.cfg" cisco_asa|palo_alto_set|palo_alto_xml|palo_alto_panorama
/analyze   /optimize   /convert {"target_vendor":"palo_alto_set","panos_target_version":"11.2","routing_engine":"lr","pipeline_mode":"like_for_like"}
/jobs   /resume [job_id]   /status   /target   /download   /allowance
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
    if command == "open":
        parts = shlex.split(rest)
        if len(parts) != 2:
            raise ValueError('Use /open "filename" vendor')
        return controller.select(*parts)
    if command in {"analyze", "optimize", "convert"}:
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
    if command == "allowance":
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
    }:
        args = json.loads(rest) if rest else {}
        if not isinstance(args, dict):
            raise ValueError("Arguments must be a JSON object")
        return controller.query(command, args)
    raise ValueError("Unsupported command; use /help")
