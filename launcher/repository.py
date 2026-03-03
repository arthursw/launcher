"""Repository URL parsing and API endpoint inference."""

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus

from .config import AppConfig


@dataclass
class RepositoryInfo:
    """Parsed repository information with API endpoints."""

    host: str
    owner: str
    repo: str
    api_base: str
    releases_endpoint: str
    archive_endpoint: str  # Contains {ref} placeholder


# SSH pattern: git@github.com:owner/repo.git
SSH_PATTERN = re.compile(r"^git@([^:]+):([^/]+)/([^/]+?)(?:\.git)?$")

# HTTPS pattern: https://github.com/owner/repo.git
HTTPS_PATTERN = re.compile(r"^https?://([^/]+)/([^/]+)/([^/]+?)(?:\.git)?$")


def parse_repository_url(url: str) -> RepositoryInfo:
    """Parse a repository URL and infer API endpoints.

    Supports:
        - SSH: git@github.com:owner/repo.git
        - HTTPS: https://github.com/owner/repo.git
        - Both with or without .git suffix

    Args:
        url: The repository URL to parse

    Returns:
        RepositoryInfo with inferred API endpoints

    Raises:
        ValueError: If the URL format is not recognized
    """
    # Try SSH pattern first
    match = SSH_PATTERN.match(url)
    if match:
        host, owner, repo = match.groups()
        return _create_repository_info(host, owner, repo)

    # Try HTTPS pattern
    match = HTTPS_PATTERN.match(url)
    if match:
        host, owner, repo = match.groups()
        return _create_repository_info(host, owner, repo)

    raise ValueError(f"Unrecognized repository URL format: {url}")


def _create_repository_info(host: str, owner: str, repo: str) -> RepositoryInfo:
    """Create RepositoryInfo with appropriate API endpoints based on host.

    Args:
        host: The git host (e.g., github.com, gitlab.com)
        owner: Repository owner/organization
        repo: Repository name

    Returns:
        RepositoryInfo with correct API endpoints for the host
    """
    host_lower = host.lower()

    if "github" in host_lower:
        return _github_endpoints(host, owner, repo)
    elif "gitlab" in host_lower:
        return _gitlab_endpoints(host, owner, repo)
    else:
        # Default to GitHub-style API for unknown hosts
        return _github_endpoints(host, owner, repo)


def _github_endpoints(host: str, owner: str, repo: str) -> RepositoryInfo:
    """Create GitHub API endpoints.

    GitHub API:
        - Releases: GET /repos/{owner}/{repo}/releases/latest
        - Archive: GET /repos/{owner}/{repo}/zipball/{ref}
    """
    # Use api.github.com for github.com, otherwise use host/api/v3
    if host.lower() == "github.com":
        api_base = "https://api.github.com"
    else:
        api_base = f"https://{host}/api/v3"

    return RepositoryInfo(
        host=host,
        owner=owner,
        repo=repo,
        api_base=api_base,
        releases_endpoint=f"/repos/{owner}/{repo}/releases/latest",
        archive_endpoint=f"/repos/{owner}/{repo}/zipball/{{ref}}",
    )


def _gitlab_endpoints(host: str, owner: str, repo: str) -> RepositoryInfo:
    """Create GitLab API endpoints.

    GitLab API:
        - Releases: GET /projects/{id}/releases (sorted by released_at)
        - Archive: GET /projects/{id}/repository/archive.zip?sha={ref}

    The project ID is URL-encoded as owner%2Frepo
    """
    # Use gitlab.com/api/v4 for gitlab.com, otherwise use host/api/v4
    if host.lower() == "gitlab.com":
        api_base = "https://gitlab.com/api/v4"
    else:
        api_base = f"https://{host}/api/v4"

    # GitLab uses URL-encoded project path as ID
    project_id = quote_plus(f"{owner}/{repo}")

    return RepositoryInfo(
        host=host,
        owner=owner,
        repo=repo,
        api_base=api_base,
        releases_endpoint=f"/projects/{project_id}/releases",
        archive_endpoint=f"/projects/{project_id}/repository/archive.zip?sha={{ref}}",
    )


def get_api_endpoints(config: AppConfig) -> tuple[str, str, str]:
    """Get API endpoints from config, inferring from repository URL if needed.

    Args:
        config: Application configuration

    Returns:
        Tuple of (api_base, releases_endpoint, archive_endpoint)

    Raises:
        ValueError: If endpoints cannot be determined
    """
    # If all endpoints are explicitly provided, use them
    if config.api and config.releases_endpoint and config.archive_endpoint:
        return config.api.rstrip("/"), config.releases_endpoint, config.archive_endpoint

    # If repository URL is provided, parse it
    if config.repository:
        repo_info = parse_repository_url(config.repository)

        # Allow explicit overrides
        api_base = config.api.rstrip("/") if config.api else repo_info.api_base
        releases_endpoint = config.releases_endpoint or repo_info.releases_endpoint
        archive_endpoint = config.archive_endpoint or repo_info.archive_endpoint

        return api_base, releases_endpoint, archive_endpoint

    raise ValueError("Cannot determine API endpoints: neither repository nor api/releases_endpoint/archive_endpoint provided")
