from __future__ import annotations

import base64
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from .analyzer import analyze_text
from .config import Settings
from .db import GitHubSnapshot, Project, utcnow

log = logging.getLogger(__name__)

TEXT_FILE_SUFFIXES = {".c", ".cc", ".conf", ".cpp", ".cu", ".go", ".h", ".hpp", ".ini", ".json", ".md", ".py", ".rs", ".sh", ".toml", ".txt", ".yaml", ".yml"}
CORE_HINTS = ("miner", "wallet", "node", "daemon", "consensus", "pow", "genesis", "mainnet", "testnet", "seed", "stratum")
BUILD_FILES = {"cargo.toml", "cmakelists.txt", "dockerfile", "go.mod", "makefile", "package.json", "pyproject.toml"}
ROADMAP_HINTS = ("roadmap", "milestone", "plan")


class GitHub:
    def __init__(self, settings: Settings):
        self.base_url = settings.github_api_base.rstrip("/")
        self.max_pages = settings.github_max_pages
        self.client = httpx.Client(
            timeout=settings.github_timeout_seconds,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "pow-radar/0.1",
                **({"Authorization": f"******"} if settings.github_token else {}),
            },
        )

    def request_json(self, path: str, *, params: dict | None = None) -> dict | list:
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                response = self.client.get(url, params=params)
                if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
                    reset_at = int(response.headers.get("x-ratelimit-reset", "0") or 0)
                    sleep_for = max(min(reset_at - int(time.time()), 10), 1)
                    log.warning("GitHub rate limit hit for %s; sleeping %ss", path, sleep_for)
                    time.sleep(sleep_for)
                    continue
                if response.status_code in {429, 500, 502, 503, 504}:
                    sleep_for = min(2**attempt, 8)
                    log.warning("GitHub transient error %s for %s; retry in %ss", response.status_code, path, sleep_for)
                    time.sleep(sleep_for)
                    continue
                response.raise_for_status()
                if response.status_code == 204:
                    return {}
                return response.json()
            except httpx.HTTPError as exc:  # pragma: no cover - network only
                last_error = exc
                sleep_for = min(2**attempt, 8)
                log.warning("GitHub request failed for %s: %s; retry in %ss", path, exc, sleep_for)
                time.sleep(sleep_for)
        raise last_error or RuntimeError(f"GitHub request failed: {path}")

    def paginate(self, path: str, *, params: dict | None = None) -> list[dict]:
        items: list[dict] = []
        page_params = dict(params or {})
        per_page = int(page_params.get("per_page", 30))
        for page in range(1, self.max_pages + 1):
            page_params["page"] = page
            page_params["per_page"] = per_page
            payload = self.request_json(path, params=page_params)
            page_items = payload.get("items", []) if isinstance(payload, dict) else payload
            if not page_items:
                break
            items.extend(page_items)
            if len(page_items) < per_page:
                break
        return items

    def search(self, query: str) -> list[dict]:
        return self.paginate("/search/repositories", params={"q": query, "sort": "updated", "per_page": 30})

    def repo(self, full_name: str) -> dict:
        return self.request_json(f"/repos/{full_name}")

    def contributors(self, full_name: str) -> list[dict]:
        return self.paginate(f"/repos/{full_name}/contributors", params={"anon": "false", "per_page": 30})

    def releases(self, full_name: str) -> list[dict]:
        return self.paginate(f"/repos/{full_name}/releases", params={"per_page": 10})

    def commits_since(self, full_name: str, *, since: datetime) -> list[dict]:
        return self.paginate(
            f"/repos/{full_name}/commits",
            params={"since": since.replace(microsecond=0).isoformat().replace("+00:00", "Z"), "per_page": 30},
        )

    def tree(self, full_name: str, branch: str) -> list[str]:
        payload = self.request_json(f"/repos/{full_name}/git/trees/{branch}", params={"recursive": "1"})
        return [item["path"] for item in payload.get("tree", []) if item.get("type") == "blob"]

    def content(self, full_name: str, path: str, *, ref: str) -> str:
        payload = self.request_json(f"/repos/{full_name}/contents/{path}", params={"ref": ref})
        if payload.get("type") != "file":
            return ""
        if payload.get("size", 0) > 200_000:
            return ""
        if payload.get("encoding") == "base64":
            return base64.b64decode(payload["content"]).decode("utf-8", errors="ignore")
        return payload.get("content", "")


def discover(session, settings: Settings) -> int:
    github = GitHub(settings)
    seen = 0
    for query in settings.keywords().get("search_queries", []):
        for item in github.search(query):
            full_name = item["full_name"]
            project = session.query(Project).filter_by(full_name=full_name).one_or_none()
            if project is None:
                project = Project(full_name=full_name)
                session.add(project)
                seen += 1
            project.html_url = item.get("html_url")
            project.description = item.get("description")
            project.homepage = item.get("homepage")
            project.default_branch = item.get("default_branch")
            project.language = item.get("language")
            project.is_fork = item.get("fork", False)
            project.stars = item.get("stargazers_count", 0)
            project.forks = item.get("forks_count", 0)
            project.open_issues = item.get("open_issues_count", 0)
            project.last_checked_at = utcnow()
    session.commit()
    return seen


def collect(session, settings: Settings) -> int:
    github = GitHub(settings)
    count = 0
    keywords = settings.keywords()
    for project in session.query(Project).filter(Project.status != "ARCHIVED").all():
        try:
            repo = github.repo(project.full_name)
            default_branch = repo.get("default_branch") or project.default_branch or "main"
            tree = github.tree(project.full_name, default_branch)
            selected_paths = _interesting_paths(tree)
            files = {path: github.content(project.full_name, path, ref=default_branch) for path in selected_paths}
            analysis = analyze_text(files, keywords)
            contributors = github.contributors(project.full_name)
            releases = github.releases(project.full_name)
            commits_30d = github.commits_since(project.full_name, since=utcnow() - timedelta(days=30))

            project.html_url = repo.get("html_url")
            project.description = repo.get("description")
            project.homepage = repo.get("homepage")
            project.default_branch = default_branch
            project.language = repo.get("language")
            project.is_fork = repo.get("fork", project.is_fork)
            project.parent_full_name = (repo.get("parent") or {}).get("full_name")
            project.stars = repo.get("stargazers_count", 0)
            project.forks = repo.get("forks_count", 0)
            project.open_issues = repo.get("open_issues_count", 0)
            project.latest_release = releases[0].get("tag_name") if releases else None
            project.latest_commit_at = _parse_dt(repo.get("pushed_at"))
            project.last_checked_at = utcnow()

            metadata = {
                **(project.metadata_json or {}),
                "license": (repo.get("license") or {}).get("spdx_id"),
                "topics": repo.get("topics", []),
                "contributors": len(contributors),
                "commits_30d": len(commits_30d),
                "inactive_days": _inactive_days(repo),
                "core_files": _count_core_files(tree),
                "has_tests": any("test" in path.lower() for path in tree),
                "has_pow": analysis["pow"],
                "has_gpu": analysis["gpu"],
                "has_miner": analysis["miner"],
                "buildable_node": analysis["node"] and any(Path(path).name.lower() in BUILD_FILES for path in tree),
                "mainnet_window": analysis["launch"] and any(term in _flatten_text(files) for term in ("mainnet", "launch", "release candidate", "rc")),
                "parameters_frozen": analysis["parameter"] and any(term in _flatten_text(files) for term in ("genesis", "difficulty", "block reward", "epoch")),
                "fair_launch": not analysis["premine"],
                "low_visibility": project.stars <= settings.rules().get("low_visibility_max_stars", 200),
                "launch_signal": analysis["launch"],
                "malicious_script": analysis["remote_exec"],
                "technical_discussion": repo.get("open_issues_count", 0) > 0,
                "author_history_years": _owner_history_years(repo),
                "reproducible_release": bool(releases) and any(Path(path).name.lower() in BUILD_FILES for path in tree),
                "roadmap_present": any(any(hint in path.lower() for hint in ROADMAP_HINTS) for path in tree),
                "anti_asic": any(term in _flatten_text(files) for term in ("anti-asic", "asic resistant", "gpu fair")),
                "analysis": analysis,
                "interesting_paths": selected_paths,
                "files_sampled": len(files),
            }
            project.metadata_json = metadata
            session.add(
                GitHubSnapshot(
                    project_id=project.id,
                    data={
                        "repo": repo,
                        "contributors_count": len(contributors),
                        "commits_30d": len(commits_30d),
                        "latest_release": project.latest_release,
                        "selected_paths": selected_paths,
                        "analysis": analysis,
                    },
                )
            )
            count += 1
        except httpx.HTTPError as exc:  # pragma: no cover - network only
            log.warning("collect failed for %s: %s", project.full_name, exc)
    session.commit()
    return count


def _interesting_paths(tree: list[str]) -> list[str]:
    selected: list[str] = []
    for path in tree:
        lower = path.lower()
        suffix = Path(lower).suffix
        if Path(lower).name in BUILD_FILES or suffix in TEXT_FILE_SUFFIXES or any(hint in lower for hint in CORE_HINTS):
            selected.append(path)
    selected.sort(key=lambda item: (0 if Path(item).name.lower().startswith("readme") else 1, len(item), item))
    return selected[:25]


def _flatten_text(files: dict[str, str]) -> str:
    return "\n".join(f"{path}\n{content}" for path, content in files.items()).lower()


def _count_core_files(tree: list[str]) -> int:
    count = 0
    for path in tree:
        lower = path.lower()
        if any(hint in lower for hint in CORE_HINTS) and Path(lower).suffix in TEXT_FILE_SUFFIXES:
            count += 1
    return count


def _owner_history_years(repo: dict) -> int:
    created_at = _parse_dt(repo.get("created_at"))
    if created_at is None:
        return 0
    return max((utcnow() - created_at).days // 365, 0)


def _inactive_days(repo: dict) -> int:
    pushed_at = _parse_dt(repo.get("pushed_at")) or _parse_dt(repo.get("updated_at"))
    if pushed_at is None:
        return 9999
    return max((utcnow() - pushed_at).days, 0)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
