"""User-directed local orchestration; providers never receive this object."""

import base64
import os
import hashlib
import json
import time
import uuid
from pathlib import Path

from .workspace import Workspace, WorkspaceError
from .api import APIError, Client, ExternalClient
from .backend import EXTERNAL_MAX_BYTES, download_external, submit_external
from .catalog import Catalog
from .job_options import check as check_options

# Query commands → the NetConverter MCP tool of the same purpose (full API profile).
QUERY_TOOLS = {
    "unused_objects": "get_unused_objects",
    "routes": "get_route_summary",
    "interfaces": "get_interface_summary",
    "policy": "get_acl_summary",
    "nat": "get_nat_summary",
    "dependencies": "get_object_dependencies",
    "flow": "simulate_flow",
    # The configuration lines NetConverter could not parse (#7): fixed tool arguments.
    "unparsed_lines": ("get_evidence", {"section": "unparsed_lines"}),
}


# Internal pipeline evidence stays on the server (upstream 0439995).
INTERNAL_EVIDENCE_FILES = frozenset({"evidence.json", "pipeline-evidence.json"})


def fetch_artifacts(client, job, output: Workspace) -> list:
    """Download every manifest artifact, verify size and SHA-256, publish atomically."""
    saved = []
    for item in client.artifacts(job)["artifacts"]:
        if item["filename"] in INTERNAL_EVIDENCE_FILES:
            continue
        data = client.download(job, item["artifact_id"])
        if any(data.get(k) != item[k] for k in ("filename", "sha256", "bytes")):
            raise WorkspaceError("Artifact manifest changed; retry download")
        try:
            content = base64.b64decode(data["content_base64"], validate=True)
        except ValueError:
            raise WorkspaceError("Invalid artifact encoding") from None
        if len(content) != item["bytes"]:
            raise WorkspaceError("Artifact size mismatch")
        saved.append(output.save_artifact(job, item["filename"], content, item["sha256"]))
    return saved


class Controller:
    """``kind`` is the credential profile: ``external`` (full API, any vendor) or
    ``quick`` (0.1.x pilot key). ``remote`` returns a RemoteMCP for full-API queries."""

    def __init__(self, workspace, client, provider=None, *, kind=None, remote=None):
        self.workspace = Workspace(workspace)
        self.client = client
        self.provider = provider
        self.kind = kind or ("external" if isinstance(client, ExternalClient) else "quick")
        self.remote_factory = remote
        self._remote = None
        self.state = self.workspace.load()
        self.allowance = {}
        self.catalog = Catalog()

    # -- folders (typed by the user; never a model operation) -------------------

    MAX_LISTED = 200

    def _resolve_folder(self, path):
        raw = Path(os.path.expanduser(path or "~"))
        target = (raw if raw.is_absolute() else self.workspace.root / raw).resolve()
        if not target.is_dir():
            raise WorkspaceError(f"Not a folder: {target}")
        return target

    def change_folder(self, path):
        """/cd: make another folder the workspace and load its own job state.

        Only the user can type this. It is not in the model's operation list, and the
        MCP bridge keeps its configured root, so a prompt cannot move the boundary.
        """
        target = self._resolve_folder(path)
        if not os.access(target, os.W_OK):
            raise WorkspaceError(f"{target} is not writable; choose a folder you own")
        workspace = Workspace(target)
        state = workspace.load()  # refuse before switching if its state is invalid
        self.workspace, self.state = workspace, state
        return {"folder": str(target), "jobs_here": len(state.get("jobs", {}))}

    def list_folder(self, path=""):
        """/ls, /dir: names and sizes only, never file contents."""
        target = self._resolve_folder(path or ".")
        entries = []
        for item in target.iterdir():
            if item.name.startswith("."):
                continue
            try:
                is_dir = item.is_dir()
                size = None if is_dir else item.stat().st_size
            except OSError:
                continue
            entries.append({"name": item.name, "folder": is_dir, "bytes": size})
        entries.sort(key=lambda e: (not e["folder"], e["name"].lower()))
        return {"folder": str(target), "entries": entries[: self.MAX_LISTED],
                "total": len(entries), "inside_workspace": target.is_relative_to(self.workspace.root)}

    @property
    def external(self) -> bool:
        return self.kind == "external"

    def capabilities(self):
        try:
            self.allowance = self.client.capabilities()
        except APIError as exc:
            if self.external and exc.status == 404:
                raise WorkspaceError("This NetConverter server does not publish its capabilities yet "
                                     "(GET /capabilities); update the server, then retry /refresh") from None
            raise
        self.catalog = (Catalog.from_external if self.external else Catalog.from_quick)(self.allowance)
        return self.allowance

    def max_bytes(self) -> int:
        if self.catalog.loaded:
            return self.catalog.max_bytes
        return EXTERNAL_MAX_BYTES if self.external else Catalog().max_bytes

    def select(self, filename, vendor):
        if self.external:
            return self._select_local(filename, vendor)
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

    def _select_local(self, filename, vendor):
        """Full API: nothing is uploaded until submit; the revision is pinned by SHA-256."""
        path, _, digest = self.workspace.snapshot(filename, self.max_bytes())
        handle = "local_" + digest[:16]
        self.state["configurations"][handle] = {
            "path": str(path.relative_to(self.workspace.root)),
            "sha256": digest,
            "vendor": vendor,
            "local": True,
        }
        self.state["selected"] = handle
        self.state.pop("active_job", None)
        self.workspace.store(self.state)
        return {"configuration_id": handle, "source_sha256": digest, "vendor": vendor, "local": True}

    def _selected_revision(self, handle):
        metadata = self.state["configurations"].get(handle) or {}
        _, content, digest = self.workspace.snapshot(metadata.get("path", ""), self.max_bytes())
        if digest != metadata.get("sha256"):
            raise WorkspaceError("The selected file changed after you chose it; select it again")
        return metadata, content

    def submit(self, operation, options=None):
        selected = self.state.get("selected")
        if not selected:
            raise WorkspaceError("Open a configuration first")
        if self.external and operation == "analyze":
            operation = "validate"
        settings = dict(options or {})
        target = settings.pop("target_vendor", None)
        # Before anything is stored or sent: an option the server would ignore is refused.
        check_options(settings, "validate" if operation == "analyze" else operation, target,
                      profile="external" if self.external else "quick")
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
            if self.external:
                metadata, content = self._selected_revision(selected)
                settings = dict(options or {})
                target = settings.pop("target_vendor", None)
                result = submit_external(self.client, content, metadata["vendor"], target,
                                         operation, settings, key)
            else:
                wire = "analyze" if operation == "validate" else operation  # the pilot API's name
                result = self.client.submit(selected, wire, options or {}, key)
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
        result = self.client.job(job) if self.external else self.client.status(job)
        self.state["active_job"] = job
        configuration = result.get("configuration_id")
        if configuration:
            self.state["selected"] = configuration
            self.state["jobs"].setdefault(job, {})["configuration_id"] = configuration
        self.workspace.store(self.state)
        return result

    def jobs(self):
        return self.client.jobs()

    def findings(self, job_id):
        """Every finding of a completed validate/optimize job as (bucket, title); None if unavailable."""
        from .summary import sarif_findings

        if not self.external:
            return None
        try:
            return sarif_findings(self.client.findings(job_id))
        except (APIError, ValueError):
            return None

    def remote(self):
        if self._remote is None:
            self._remote = self.remote_factory() if self.remote_factory else None
        if self._remote is None:
            raise WorkspaceError("Questions about a job need NetConverter MCP access; sign in with netconverter login --clerk")
        return self._remote

    def _query_remote(self, job, operation, arguments):
        from .remote_mcp import RemoteError

        tool = QUERY_TOOLS.get(operation)
        if not tool:
            raise WorkspaceError("Unsupported question; use /help")
        tool, fixed = (tool, {}) if isinstance(tool, str) else tool
        try:
            remote = self.remote()
            remote.call_tool("select_job", {"job_id": job})
            reply = remote.call_tool(tool, {**arguments, **fixed})
        except RemoteError as exc:
            raise WorkspaceError(f"NetConverter could not answer this question ({exc.code})") from None
        details = reply.get("structuredContent")
        if not isinstance(details, dict):
            try:
                details = json.loads(reply["content"][0]["text"])
            except (KeyError, IndexError, TypeError, ValueError):
                details = {"result": "No structured result"}
        if reply.get("isError"):
            raise WorkspaceError(str(details.get("message") or details.get("error") or "The question failed"))
        return {"job_id": job, "operation": operation, "details": details,
                "query_id": operation + "_" + uuid.uuid4().hex[:12]}

    def query(self, operation, arguments=None):
        job = self.state.get("active_job")
        if not job:
            raise WorkspaceError("Select a completed job with resume first")
        if self.external:
            result = self._query_remote(job, operation, arguments or {})
            return self._save_query(job, result)
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
        return self._save_query(job, result)

    def _save_query(self, job, result):
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
        if self.external:
            paths = download_external(self.client, job, Workspace(parent))
        else:
            paths = fetch_artifacts(self.client, job, Workspace(parent))
        return {"job_id": job, "saved": [str(path) for path in paths]}

    def target(self):
        job = self.state.get("active_job")
        if not job:
            raise WorkspaceError("Select a completed conversion first")
        if self.external:
            return self._target_local(job)
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

    def _target_local(self, job):
        """Full API: save the translated config beside the source, then select it."""
        status = self.client.job(job)
        target = status.get("target_vendor")
        translated = self.client.translated(job)
        if not translated or not target or target == "n/a":
            raise WorkspaceError("This job has no generated configuration yet")
        config = self.state["jobs"].get(job, {}).get("configuration_id")
        source = self.state["configurations"].get(config, {}).get("path")
        parent = self.workspace._inside((self.workspace.root / source).parent) if source else self.workspace.root
        saved = Workspace(parent).save_artifact(job, "translated.txt", translated,
                                                hashlib.sha256(translated).hexdigest())
        result = self._select_local(str(saved.relative_to(self.workspace.root)), target)
        self.state["configurations"][result["configuration_id"]].update(
            parent_job_id=job, display_name=f"Generated {target} · {job}")
        self.workspace.store(self.state)
        return {**result, "parent_job_id": job}
