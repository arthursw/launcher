"""Tests for the repository module."""

import pytest
from urllib.parse import quote_plus

from launcher.repository import (
    parse_repository_url,
    get_api_endpoints,
    RepositoryInfo,
)
from launcher.config import AppConfig


class TestParseRepositoryUrl:
    """Tests for parse_repository_url function."""

    def test_github_ssh_url(self):
        """Test parsing GitHub SSH URL."""
        result = parse_repository_url("git@github.com:owner/repo.git")
        assert result.host == "github.com"
        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.api_base == "https://api.github.com"
        assert result.tags_endpoint == "/repos/owner/repo/tags"
        assert result.archive_endpoint == "/repos/owner/repo/zipball/{ref}"

    def test_github_ssh_url_no_git_suffix(self):
        """Test parsing GitHub SSH URL without .git suffix."""
        result = parse_repository_url("git@github.com:owner/repo")
        assert result.host == "github.com"
        assert result.owner == "owner"
        assert result.repo == "repo"

    def test_github_https_url(self):
        """Test parsing GitHub HTTPS URL."""
        result = parse_repository_url("https://github.com/owner/repo.git")
        assert result.host == "github.com"
        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.api_base == "https://api.github.com"

    def test_github_https_url_no_git_suffix(self):
        """Test parsing GitHub HTTPS URL without .git suffix."""
        result = parse_repository_url("https://github.com/owner/repo")
        assert result.host == "github.com"
        assert result.owner == "owner"
        assert result.repo == "repo"

    def test_gitlab_ssh_url(self):
        """Test parsing GitLab SSH URL."""
        result = parse_repository_url("git@gitlab.com:owner/repo.git")
        assert result.host == "gitlab.com"
        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.api_base == "https://gitlab.com/api/v4"

        # GitLab uses URL-encoded project path
        project_id = quote_plus("owner/repo")
        assert result.tags_endpoint == f"/projects/{project_id}/repository/tags"
        assert result.archive_endpoint == f"/projects/{project_id}/repository/archive.zip?sha={{ref}}"

    def test_gitlab_https_url(self):
        """Test parsing GitLab HTTPS URL."""
        result = parse_repository_url("https://gitlab.com/owner/repo.git")
        assert result.host == "gitlab.com"
        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.api_base == "https://gitlab.com/api/v4"

    def test_github_enterprise_ssh(self):
        """Test parsing GitHub Enterprise SSH URL."""
        result = parse_repository_url("git@github.mycompany.com:team/project.git")
        assert result.host == "github.mycompany.com"
        assert result.owner == "team"
        assert result.repo == "project"
        # GitHub Enterprise uses /api/v3 endpoint
        assert result.api_base == "https://github.mycompany.com/api/v3"

    def test_self_hosted_gitlab(self):
        """Test parsing self-hosted GitLab URL."""
        result = parse_repository_url("git@gitlab.mycompany.com:team/project.git")
        assert result.host == "gitlab.mycompany.com"
        assert result.owner == "team"
        assert result.repo == "project"
        assert result.api_base == "https://gitlab.mycompany.com/api/v4"

    def test_invalid_url_raises_error(self):
        """Test that invalid URLs raise ValueError."""
        with pytest.raises(ValueError, match="Unrecognized repository URL format"):
            parse_repository_url("not-a-valid-url")

    def test_invalid_format_raises_error(self):
        """Test that invalid format raises ValueError."""
        with pytest.raises(ValueError):
            parse_repository_url("ftp://example.com/repo")


class TestGetApiEndpoints:
    """Tests for get_api_endpoints function."""

    def test_endpoints_from_repository(self):
        """Test getting endpoints from repository URL."""
        config = AppConfig(
            name="TestApp",
            main="main.py",
            path=".",
            repository="git@github.com:owner/repo.git"
        )
        api_base, tags_endpoint, archive_endpoint = get_api_endpoints(config)

        assert api_base == "https://api.github.com"
        assert tags_endpoint == "/repos/owner/repo/tags"
        assert archive_endpoint == "/repos/owner/repo/zipball/{ref}"

    def test_explicit_endpoints_override(self):
        """Test that explicit endpoints override inferred ones."""
        config = AppConfig(
            name="TestApp",
            main="main.py",
            path=".",
            repository="git@github.com:owner/repo.git",
            api="https://custom.api.com",
            tags_endpoint="/custom/tags",
            archive_endpoint="/custom/archive/{ref}"
        )
        api_base, tags_endpoint, archive_endpoint = get_api_endpoints(config)

        assert api_base == "https://custom.api.com"
        assert tags_endpoint == "/custom/tags"
        assert archive_endpoint == "/custom/archive/{ref}"

    def test_partial_override(self):
        """Test partial endpoint override."""
        config = AppConfig(
            name="TestApp",
            main="main.py",
            path=".",
            repository="git@github.com:owner/repo.git",
            tags_endpoint="/custom/tags"
        )
        api_base, tags_endpoint, archive_endpoint = get_api_endpoints(config)

        # api_base from repository
        assert api_base == "https://api.github.com"
        # tags_endpoint from override
        assert tags_endpoint == "/custom/tags"
        # archive_endpoint from repository
        assert archive_endpoint == "/repos/owner/repo/zipball/{ref}"

    def test_explicit_endpoints_only(self):
        """Test config with only explicit endpoints."""
        config = AppConfig(
            name="TestApp",
            main="main.py",
            path=".",
            api="https://api.example.com/",
            tags_endpoint="/tags",
            archive_endpoint="/archive/{ref}"
        )
        api_base, tags_endpoint, archive_endpoint = get_api_endpoints(config)

        # Trailing slash should be stripped from api
        assert api_base == "https://api.example.com"
        assert tags_endpoint == "/tags"
        assert archive_endpoint == "/archive/{ref}"

    def test_missing_endpoints_raises_error(self):
        """Test that missing endpoints raise ValueError."""
        # This should fail at AppConfig creation due to validation
        with pytest.raises(ValueError):
            AppConfig(
                name="TestApp",
                main="main.py",
                path="."
            )
