import logging, httpx
from datetime import datetime, timedelta, timezone
from .config import Settings
from .db import Project, Snapshot

log = logging.getLogger(__name__)
class GitHub:
    def __init__(self, settings: Settings):
        self.client = httpx.Client(timeout=20, headers={"Accept":"application/vnd.github+json", **({"Authorization":f"Bearer {settings.github_token}"} if settings.github_token else {})})
    def search(self, query):
        r = self.client.get("https://api.github.com/search/repositories", params={"q":query, "sort":"updated", "per_page":30}); r.raise_for_status(); return r.json().get("items", [])
    def repo(self, full_name):
        r=self.client.get(f"https://api.github.com/repos/{full_name}"); r.raise_for_status(); return r.json()
    def files(self, full_name, branch):
        r=self.client.get(f"https://api.github.com/repos/{full_name}/git/trees/{branch}", params={"recursive":"1"}); r.raise_for_status(); return {x["path"]:"" for x in r.json().get("tree",[]) if x.get("type")=="blob"}

def discover(session, settings):
    gh=GitHub(settings); seen=0
    for query in settings.keywords()["search_queries"]:
        for item in gh.search(query):
            name=item["full_name"]
            p=session.query(Project).filter_by(full_name=name).one_or_none()
            if not p:
                p=Project(full_name=name, html_url=item.get("html_url"), description=item.get("description"), default_branch=item.get("default_branch"), is_fork=item.get("fork",False), stars=item.get("stargazers_count",0), forks=item.get("forks_count",0), open_issues=item.get("open_issues_count",0)); session.add(p); seen+=1
    session.commit(); return seen

def collect(session, settings):
    gh=GitHub(settings); count=0
    for p in session.query(Project).filter(Project.status != "ARCHIVED").all():
        try:
            x=gh.repo(p.full_name); p.is_fork=x.get("fork",p.is_fork); p.parent_full_name=(x.get("parent") or {}).get("full_name"); p.stars=x.get("stargazers_count",0); p.forks=x.get("forks_count",0); p.open_issues=x.get("open_issues_count",0); p.metadata_json={"license":(x.get("license") or {}).get("spdx_id"), "topics":x.get("topics",[])}
            session.add(Snapshot(project_id=p.id, data=x)); count+=1
        except httpx.HTTPError as e: log.warning("collect failed for %s: %s",p.full_name,e)
    session.commit(); return count
