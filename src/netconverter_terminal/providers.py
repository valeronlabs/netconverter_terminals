"""Stateless provider protocols. Only a closed vocabulary and projected counts leave."""

from __future__ import annotations
import json
import re
from urllib.parse import urlsplit
import httpx
from .privacy import model_summary

OPERATIONS = (
    "analyze",
    "optimize",
    "convert",
    "unused_objects",
    "routes",
    "interfaces",
    "policy",
    "nat",
    "dependencies",
    "flow",
    "status",
    "artifacts",
)
SCHEMA = {
    "type": "object",
    "properties": {"operation": {"type": "string", "enum": list(OPERATIONS)}},
    "required": ["operation"],
    "additionalProperties": False,
}
SYSTEM = (
    "Select one NetConverter operation using the request_operation tool. "
    "The operation argument must be a single string, not a schema or list. "
    'For example, finding unused objects requires {"operation":"unused_objects"}. '
    "Parameters and conversion decisions are collected by the terminal. Never invent parameters."
)
# Unknown words are opaque references, never sent verbatim. No configuration text,
# arbitrary prose, filenames, identifiers, addresses, or provider-returned text is retained.
WORDS = frozenset(
    "find unused objects explain what can be cleaned up clean cleanup analyze analysis optimize optimization convert conversion migrate migration asa cisco palo alto set xml panorama routing routes consolidation recommendations ideas show get list interfaces policy rules nat dependencies where used traffic flow tcp udp port open allow allowed deny denied is do i have status progress job artifacts download reports evidence configuration source target selected please help me the a an and or to from for in on of with how which this that it my does check".split()
)


def abstract_intent(text):
    if len(text) > 4000:
        raise ValueError("Question is too long")
    # Keep only individually allowlisted words; everything else becomes a fixed
    # opaque marker. Even a pasted configuration cannot cross this boundary.
    return " ".join(
        word.lower() if word.lower() in WORDS else "REFERENCE"
        for word in re.findall(r"\S+", text)
    )


class ProviderError(RuntimeError):
    pass


class Provider:
    def __init__(self, name, model, key="", *, endpoint=None, transport=None):
        if (
            name not in {"openai", "anthropic", "gemini", "ollama"}
            or not model
            or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", model)
        ):
            raise ValueError("Select a supported provider and an explicit model")
        self.name, self.model, self.key = name, model, key
        defaults = {
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com/v1",
            "gemini": "https://generativelanguage.googleapis.com/v1beta",
            "ollama": "http://127.0.0.1:11434",
        }
        self.endpoint = endpoint or defaults[name]
        if name != "ollama" and self.endpoint != defaults[name]:
            raise ValueError("Hosted providers use their fixed official endpoint")
        parts = urlsplit(self.endpoint)
        if (
            parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or (
                name == "ollama"
                and (
                    parts.scheme != "http"
                    or parts.hostname not in {"localhost", "127.0.0.1", "::1"}
                )
            )
        ):
            raise ValueError("Local inference requires an explicit loopback endpoint")
        self.http = httpx.Client(
            timeout=45, transport=transport, follow_redirects=False, trust_env=False
        )

    def close(self):
        self.http.close()

    def select(self, text, summary=None):
        content = json.dumps(
            {"intent": abstract_intent(text), "context": model_summary(summary or {})}
        )
        function = {
            "name": "request_operation",
            "description": "Request a permitted operation for the selected revision",
            "parameters": SCHEMA,
        }
        headers = {}
        if self.name == "openai":
            url = self.endpoint + "/responses"
            headers = {"Authorization": "Bearer " + self.key}
            body = {
                "model": self.model,
                "store": False,
                "instructions": SYSTEM,
                "input": content,
                "tools": [{"type": "function", **function, "strict": True}],
                "tool_choice": "required",
                "parallel_tool_calls": False,
            }
        elif self.name == "anthropic":
            url = self.endpoint + "/messages"
            headers = {"x-api-key": self.key, "anthropic-version": "2023-06-01"}
            body = {
                "model": self.model,
                "max_tokens": 256,
                "system": SYSTEM,
                "messages": [{"role": "user", "content": content}],
                "tools": [
                    {
                        "name": function["name"],
                        "description": function["description"],
                        "input_schema": SCHEMA,
                    }
                ],
                "tool_choice": {"type": "tool", "name": "request_operation"},
            }
        elif self.name == "gemini":
            if "/" in self.model or ":" in self.model:
                raise ValueError("Use the Gemini model ID without a path")
            url = self.endpoint + "/models/" + self.model + ":generateContent"
            headers = {"x-goog-api-key": self.key}
            body = {
                "systemInstruction": {"parts": [{"text": SYSTEM}]},
                "contents": [{"role": "user", "parts": [{"text": content}]}],
                "tools": [{"functionDeclarations": [function]}],
                "toolConfig": {
                    "functionCallingConfig": {
                        "mode": "ANY",
                        "allowedFunctionNames": ["request_operation"],
                    }
                },
            }
        else:
            url = self.endpoint + "/api/chat"
            body = {
                "model": self.model,
                "stream": False,
                "options": {"num_ctx": 4096, "num_predict": 128, "temperature": 0},
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": content},
                ],
                "tools": [{"type": "function", "function": function}],
            }
        try:
            response = self.http.post(url, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()
            if self.name == "openai":
                calls = [
                    (c["name"], json.loads(c["arguments"]))
                    for c in data["output"]
                    if c["type"] == "function_call"
                ]
            elif self.name == "anthropic":
                calls = [
                    (c["name"], c["input"])
                    for c in data["content"]
                    if c["type"] == "tool_use"
                ]
            elif self.name == "gemini":
                calls = [
                    (p["functionCall"]["name"], p["functionCall"]["args"])
                    for p in data["candidates"][0]["content"]["parts"]
                    if "functionCall" in p
                ]
            else:
                calls = [
                    (c["function"]["name"], c["function"]["arguments"])
                    for c in data["message"].get("tool_calls", [])
                ]
            if len(calls) != 1 or calls[0][0] != "request_operation":
                raise ValueError()
            args = calls[0][1]
            if (
                not isinstance(args, dict)
                or set(args) != {"operation"}
                or args["operation"] not in OPERATIONS
            ):
                raise ValueError()
            return args["operation"]
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            raise ProviderError(
                "Model unavailable or returned a forbidden operation; guided commands remain available"
            ) from None
