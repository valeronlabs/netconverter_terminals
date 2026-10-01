"""User-directed local orchestration; providers never receive this object."""

import base64
import hashlib
import json
import time
import uuid
from .workspace import Workspace, WorkspaceError
from .api import APIError, Client


class Controller:
    def __init__(self, workspace, client, provider=None):
        self.workspace = Workspace(workspace)
        self.client = client
        self.provider = provider
        self.state = self.workspace.load()
        self.allowance = {}

    def capabilities(self):
        self.allowance = self.client.capabilities()
        return self.allowance

    def select(self, filename, vendor):
        path, content, digest = self.workspace.snapshot(filename)
        result = self.client.upload(content, vendor)
        if result["source_sha256"] != digest:
            raise WorkspaceError("Server revision checksum mismatch")
        handle = result["configuration_id"]
        self.state["configurations"][handle] = {
            "path": str(path.relative_to(self.workspace.root)),
            "sha256": digest,
            "vendor": vendor,
        }
        self.state["selected"] = handle
        self.state.pop("active_job", None)
        self.workspace.store(self.state)
        return result

    def submit(self, operation, options=None):
        selected = self.state.get("selected")
        if not selected:
            raise WorkspaceError("Open a configuration first")
        request = {
            "configuration_id": selected,
            "operation": operation,
            "options": options or {},
        }
        pending = self.state.get("pending")
        if pending and pending["request"] != request:
            raise WorkspaceError(
                "An interrupted submission is pending; use resume before submitting different work"
            )
        key = pending["key"] if pending else uuid.uuid4().hex
        self.state["pending"] = {"key": key, "request": request, "started": time.time()}
        self.workspace.store(self.state)
        try:
            result = self.client.submit(selected, operation, options or {}, key)
        except APIError as exc:
            if exc.status in {400, 403, 404, 413, 422, 429}:
                self.state.pop("pending", None)
                self.workspace.store(self.state)
            raise
        self.state["jobs"][result["job_id"]] = {
            "configuration_id": selected,
            "operation": operation,
            "options": options or {},
            "submitted_at": self.state["pending"]["started"],
        }
        self.state["active_job"] = result["job_id"]
        self.state.pop("pending", None)
        self.workspace.store(self.state)
        return result

    def resume(self, job_id=None):
        if self.state.get("pending"):
            request = self.state["pending"]["request"]
            return self.submit(request["operation"], request["options"])
        job = job_id or self.state.get("active_job")
        if not job:
            return self.client.jobs()
        result = self.client.status(job)
        self.state["active_job"] = job
        configuration = result.get("configuration_id")
        if configuration:
            self.state["selected"] = configuration
            self.state["jobs"].setdefault(job, {})["configuration_id"] = configuration
        self.workspace.store(self.state)
        return result

    def query(self, operation, arguments=None):
        job = self.state.get("active_job")
        if not job:
            raise WorkspaceError("Select a completed job with resume first")
        digest = hashlib.sha256(
            json.dumps([job, operation, arguments or {}], sort_keys=True).encode()
        ).hexdigest()
        keys = self.state.setdefault("query_keys", {})
        key = keys.setdefault(digest, uuid.uuid4().hex)
        self.workspace.store(self.state)
        result = self.client.query(job, operation, arguments or {}, key)
        offset = result.get("pagination", {}).get("next_offset")

        def merge(left, right):
            for field, value in right.items():
                if isinstance(value, list):
                    left.setdefault(field, []).extend(value)
                elif isinstance(value, dict):
                    merge(left.setdefault(field, {}), value)

        while offset is not None:
            page = self.client.query(
                job, operation, arguments or {}, key, offset=offset
            )
            merge(result["details"], page["details"])
            next_offset = page.get("pagination", {}).get("next_offset")
            if next_offset is not None and next_offset <= offset:
                raise WorkspaceError("Invalid findings pagination")
            offset = next_offset
        result["pagination"] = {"complete": True}
        config = self.state["jobs"].get(job, {}).get("configuration_id")
        source = self.state["configurations"].get(config, {}).get("path")
        parent = (
            self.workspace._inside((self.workspace.root / source).parent)
            if source
            else self.workspace.root
        )
        # PostgreSQL JSONB may reorder keys on an idempotent replay. Canonical
        # bytes keep repeat downloads stable while preserving older artifacts.
        content = json.dumps(result, indent=2, default=str, sort_keys=True).encode()
        digest = hashlib.sha256(content).hexdigest()
        output = Workspace(parent)
        query_id = Client.identifier(result["query_id"])
        result["saved"] = [
            str(output.save_artifact(job, query_id + "." + digest[:12] + "." + ext, content, digest))
            for ext in ("json", "txt")
        ]
        return result

    def download(self):
        job = self.state.get("active_job")
        if not job:
            raise WorkspaceError("Select a job first")
        config = self.state["jobs"].get(job, {}).get("configuration_id")
        metadata = self.state["configurations"].get(config, {})
        parent = (
            (self.workspace.root / metadata.get("path", ".")).parent
            if metadata.get("path")
            else self.workspace.root
        )
        parent = self.workspace._inside(parent)
        output = Workspace(parent)
        paths = []
        for item in self.client.artifacts(job)["artifacts"]:
            data = self.client.download(job, item["artifact_id"])
            if any(data.get(k) != item[k] for k in ("filename", "sha256", "bytes")):
                raise WorkspaceError("Artifact manifest changed; retry download")
            try:
                content = base64.b64decode(data["content_base64"], validate=True)
            except ValueError:
                raise WorkspaceError("Invalid artifact encoding") from None
            if len(content) != item["bytes"]:
                raise WorkspaceError("Artifact size mismatch")
            paths.append(
                str(
                    output.save_artifact(job, item["filename"], content, item["sha256"])
                )
            )
        return {"job_id": job, "saved": paths}

    def target(self):
        job = self.state.get("active_job")
        if not job:
            raise WorkspaceError("Select a completed conversion first")
        result = self.client.target(job)
        source = self.state["jobs"].get(job, {}).get("configuration_id")
        self.state["configurations"][result["configuration_id"]] = {
            "parent_job_id": job,
            "display_name": "Generated " + result["vendor"] + " · " + job,
            "vendor": result["vendor"],
            "path": self.state["configurations"].get(source, {}).get("path", ""),
            "sha256": result["source_sha256"],
        }
        self.state["selected"] = result["configuration_id"]
        self.state.pop("active_job", None)
        self.workspace.store(self.state)
        return result

    def interpret(self, text):
        if not self.provider:
            raise WorkspaceError("No model connected. Use /help for guided commands.")
        return self.provider.select(text)
