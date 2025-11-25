"""Parser for inferring API endpoints from repository URLs."""

from typing import Optional, Dict, Tuple
import re


def parse_repository_url(repository: str) -> Dict[str, str]:
    """Parse a git repository URL and infer API endpoints.

    Supports:
    - GitHub: git@github.com:owner/repo.git or https://github.com/owner/repo.git
    - GitLab: git@gitlab.com:owner/repo.git or https://gitlab.com/owner/repo.git
    - Generic Git: git@host.com:owner/repo.git or https://host.com/owner/repo.git

    Args:
        repository: Repository URL (SSH or HTTPS format)

    Returns:
        Dictionary with 'api', 'tags_endpoint', 'archive_endpoint' inferred from the URL

    Raises:
        ValueError: If repository URL cannot be parsed
    """
    # Try SSH format first: git@host.com:owner/repo.git
    ssh_match = re.match(r"git@(.+?):(.+)/(.+?)(?:\.git)?$", repository)
    if ssh_match:
        host, owner, repo = ssh_match.groups()
        return _infer_endpoints(host, owner, repo)

    # Try HTTPS format: https://host.com/owner/repo.git
    https_match = re.match(r"https?://(.+?)/(.+)/(.+?)(?:\.git)?/?$", repository)
    if https_match:
        host, owner, repo = https_match.groups()
        return _infer_endpoints(host, owner, repo)

    raise ValueError(f"Cannot parse repository URL: {repository}")


def _infer_endpoints(host: str, owner: str, repo: str) -> Dict[str, str]:
    """Infer API endpoints based on the host.

    Args:
        host: The git host (e.g., 'github.com', 'gitlab.inria.fr')
        owner: The repository owner
        repo: The repository name

    Returns:
        Dictionary with 'api', 'tags_endpoint', 'archive_endpoint'
    """
    if "github.com" in host:
        return _get_github_endpoints(owner, repo)
    elif "gitlab" in host:
        return _get_gitlab_endpoints(host, owner, repo)
    else:
        # For other git hosts, assume GitHub-like structure
        return _get_github_endpoints(owner, repo)


def _get_github_endpoints(owner: str, repo: str) -> Dict[str, str]:
    """Get GitHub API endpoints."""
    return {
        "api": "https://api.github.com/",
        "tags_endpoint": f"/repos/{owner}/{repo}/git/tags",
        "archive_endpoint": f"/repos/{owner}/{repo}/zipball/{{ref}}",
    }


def _get_gitlab_endpoints(host: str, owner: str, repo: str) -> Dict[str, str]:
    """Get GitLab API endpoints.

    Note: GitLab projects use numeric IDs in the API, but we construct
    a URL-encoded project path as an alternative format.
    """
    # Construct base URL
    base_url = f"https://{host}"
    api_path = f"{base_url}/api/v4"
    project_path = f"{owner}%2F{repo}"

    return {
        "api": f"{api_path}/",
        "tags_endpoint": f"/projects/{project_path}/repository/tags",
        "archive_endpoint": f"/projects/{project_path}/repository/archive.zip",
    }


def merge_endpoints(
    inferred: Dict[str, str],
    explicit: Dict[str, Optional[str]],
) -> Dict[str, str]:
    """Merge explicit endpoints with inferred endpoints.

    Explicit endpoints take priority over inferred ones.

    Args:
        inferred: Inferred endpoints from repository
        explicit: Explicitly provided endpoints from config

    Returns:
        Merged endpoints dictionary
    """
    result = inferred.copy()
    for key in ("api", "tags_endpoint", "archive_endpoint"):
        if explicit.get(key) is not None:
            result[key] = explicit[key]
    return result
