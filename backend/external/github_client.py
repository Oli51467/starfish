from __future__ import annotations


class GitHubClient:
    """Skeleton GitHub API wrapper."""

    def fetch_repo(self, repo_url: str) -> dict:
        return {
            "repo_url": repo_url,
            "name": repo_url.rstrip("/").split("/")[-1] or "unknown-repo",
            "stars": 0,
            "description": "Mock GitHub repository data.",
        }
