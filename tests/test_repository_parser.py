"""Tests for repository URL parser."""

import pytest
from repository_parser import parse_repository_url, merge_endpoints


class TestRepositoryParser:
    """Test repository URL parsing."""

    def test_parse_github_ssh_url(self):
        """Test parsing GitHub SSH URL."""
        url = "git@github.com:arthursw/galaxy.git"
        result = parse_repository_url(url)

        assert result["api"] == "https://api.github.com/"
        assert result["tags_endpoint"] == "/repos/arthursw/galaxy/git/tags"
        assert result["archive_endpoint"] == "/repos/arthursw/galaxy/zipball/{ref}"

    def test_parse_github_ssh_url_without_git_suffix(self):
        """Test parsing GitHub SSH URL without .git suffix."""
        url = "git@github.com:arthursw/galaxy"
        result = parse_repository_url(url)

        assert result["api"] == "https://api.github.com/"
        assert result["tags_endpoint"] == "/repos/arthursw/galaxy/git/tags"
        assert result["archive_endpoint"] == "/repos/arthursw/galaxy/zipball/{ref}"

    def test_parse_github_https_url(self):
        """Test parsing GitHub HTTPS URL."""
        url = "https://github.com/arthursw/galaxy.git"
        result = parse_repository_url(url)

        assert result["api"] == "https://api.github.com/"
        assert result["tags_endpoint"] == "/repos/arthursw/galaxy/git/tags"
        assert result["archive_endpoint"] == "/repos/arthursw/galaxy/zipball/{ref}"

    def test_parse_github_https_url_without_git_suffix(self):
        """Test parsing GitHub HTTPS URL without .git suffix."""
        url = "https://github.com/arthursw/galaxy"
        result = parse_repository_url(url)

        assert result["api"] == "https://api.github.com/"
        assert result["tags_endpoint"] == "/repos/arthursw/galaxy/git/tags"
        assert result["archive_endpoint"] == "/repos/arthursw/galaxy/zipball/{ref}"

    def test_parse_github_https_url_with_trailing_slash(self):
        """Test parsing GitHub HTTPS URL with trailing slash."""
        url = "https://github.com/arthursw/galaxy.git/"
        result = parse_repository_url(url)

        assert result["api"] == "https://api.github.com/"
        assert result["tags_endpoint"] == "/repos/arthursw/galaxy/git/tags"
        assert result["archive_endpoint"] == "/repos/arthursw/galaxy/zipball/{ref}"

    def test_parse_gitlab_inria_ssh_url(self):
        """Test parsing GitLab INRIA SSH URL."""
        url = "git@gitlab.inria.fr:arthursw/galaxy.git"
        result = parse_repository_url(url)

        assert result["api"] == "https://gitlab.inria.fr/api/v4/"
        assert result["tags_endpoint"] == "/projects/arthursw%2Fgalaxy/repository/tags"
        assert result["archive_endpoint"] == "/projects/arthursw%2Fgalaxy/repository/archive.zip"

    def test_parse_gitlab_inria_https_url(self):
        """Test parsing GitLab INRIA HTTPS URL."""
        url = "https://gitlab.inria.fr/arthursw/galaxy.git"
        result = parse_repository_url(url)

        assert result["api"] == "https://gitlab.inria.fr/api/v4/"
        assert result["tags_endpoint"] == "/projects/arthursw%2Fgalaxy/repository/tags"
        assert result["archive_endpoint"] == "/projects/arthursw%2Fgalaxy/repository/archive.zip"

    def test_parse_gitlab_com_ssh_url(self):
        """Test parsing GitLab.com SSH URL."""
        url = "git@gitlab.com:owner/project.git"
        result = parse_repository_url(url)

        assert result["api"] == "https://gitlab.com/api/v4/"
        assert result["tags_endpoint"] == "/projects/owner%2Fproject/repository/tags"
        assert result["archive_endpoint"] == "/projects/owner%2Fproject/repository/archive.zip"

    def test_parse_invalid_url(self):
        """Test parsing invalid URL raises ValueError."""
        invalid_urls = [
            "not-a-valid-url",
            "ssh://git@github.com/arthursw/galaxy",
            "ftp://github.com/arthursw/galaxy",
        ]

        for url in invalid_urls:
            with pytest.raises(ValueError):
                parse_repository_url(url)


class TestMergeEndpoints:
    """Test merging inferred and explicit endpoints."""

    def test_explicit_overrides_inferred(self):
        """Test that explicit endpoints override inferred ones."""
        inferred = {
            "api": "https://api.github.com/",
            "tags_endpoint": "/repos/owner/repo/git/tags",
            "archive_endpoint": "/repos/owner/repo/zipball/{ref}",
        }
        explicit = {
            "api": "https://custom.api.com/",
            "tags_endpoint": None,
            "archive_endpoint": None,
        }

        result = merge_endpoints(inferred, explicit)

        assert result["api"] == "https://custom.api.com/"
        assert result["tags_endpoint"] == "/repos/owner/repo/git/tags"
        assert result["archive_endpoint"] == "/repos/owner/repo/zipball/{ref}"

    def test_all_explicit_override_inferred(self):
        """Test that all explicit endpoints override inferred ones."""
        inferred = {
            "api": "https://api.github.com/",
            "tags_endpoint": "/repos/owner/repo/git/tags",
            "archive_endpoint": "/repos/owner/repo/zipball/{ref}",
        }
        explicit = {
            "api": "https://custom.api.com/",
            "tags_endpoint": "/custom/tags",
            "archive_endpoint": "/custom/archive/{ref}",
        }

        result = merge_endpoints(inferred, explicit)

        assert result["api"] == "https://custom.api.com/"
        assert result["tags_endpoint"] == "/custom/tags"
        assert result["archive_endpoint"] == "/custom/archive/{ref}"

    def test_no_explicit_uses_inferred(self):
        """Test that inferred endpoints are used when no explicit ones provided."""
        inferred = {
            "api": "https://api.github.com/",
            "tags_endpoint": "/repos/owner/repo/git/tags",
            "archive_endpoint": "/repos/owner/repo/zipball/{ref}",
        }
        explicit = {
            "api": None,
            "tags_endpoint": None,
            "archive_endpoint": None,
        }

        result = merge_endpoints(inferred, explicit)

        assert result == inferred
