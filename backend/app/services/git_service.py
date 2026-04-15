"""Git operations service: branch, commit, push, create PR."""

from __future__ import annotations

import logging
import os
from typing import Optional

from git import Repo
from github import Auth, Github

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class GitService:
    """Manages Git and GitHub operations for project repositories."""

    def __init__(self) -> None:
        self._github: Optional[Github] = None

    @property
    def github(self) -> Github:
        """Lazy-initialize the GitHub client."""
        if self._github is None:
            auth = Auth.Token(settings.github_token)
            self._github = Github(auth=auth)
        return self._github

    def _set_remote_auth(self, repo: Repo) -> None:
        """Ensure the origin remote URL includes the token for auth."""
        if not settings.github_token:
            return
        origin = repo.remotes.origin
        current_url = origin.url
        if "github.com" in current_url and f"{settings.github_token}@" not in current_url:
            authed_url = current_url.replace(
                "https://", f"https://{settings.github_token}@"
            )
            origin.set_url(authed_url)

    def clone_repo(self, repo_url: str, local_path: str) -> Repo:
        """Clone a repository to the local filesystem.

        Args:
            repo_url: Git repository URL.
            local_path: Destination directory.

        Returns:
            The cloned Repo object.
        """
        if os.path.exists(local_path) and os.path.isdir(os.path.join(local_path, ".git")):
            logger.info("Repository already exists at %s, pulling latest", local_path)
            repo = Repo(local_path)
            self._set_remote_auth(repo)
            repo.remotes.origin.pull()
            return repo

        logger.info("Cloning %s to %s", repo_url, local_path)
        # Inject token for private repos
        if settings.github_token and "github.com" in repo_url:
            repo_url = repo_url.replace(
                "https://",
                f"https://{settings.github_token}@",
            )
        return Repo.clone_from(repo_url, local_path)

    def create_branch(self, repo_path: str, branch_name: str, base_branch: str = "main") -> str:
        """Create and checkout a new branch.

        Args:
            repo_path: Path to the local repository.
            branch_name: Name for the new branch.
            base_branch: Branch to base off of.

        Returns:
            The branch name.
        """
        repo = Repo(repo_path)
        self._set_remote_auth(repo)

        # Ensure we're on the base branch and up to date
        repo.git.checkout(base_branch)
        try:
            repo.remotes.origin.pull()
        except Exception as e:
            logger.warning("Could not pull latest: %s", e)

        # Create and checkout new branch
        if branch_name in [b.name for b in repo.branches]:
            repo.git.checkout(branch_name)
            logger.info("Checked out existing branch: %s", branch_name)
        else:
            repo.git.checkout("-b", branch_name)
            logger.info("Created and checked out branch: %s", branch_name)

        return branch_name

    def commit_changes(
        self,
        repo_path: str,
        message: str,
        files: Optional[list[str]] = None,
    ) -> str:
        """Stage and commit changes.

        Args:
            repo_path: Path to the local repository.
            message: Commit message.
            files: Specific files to stage; stages all if None.

        Returns:
            The commit SHA.
        """
        repo = Repo(repo_path)

        if files:
            repo.index.add(files)
        else:
            repo.git.add(A=True)

        if not repo.index.diff("HEAD") and not repo.untracked_files:
            logger.info("No changes to commit")
            return repo.head.commit.hexsha

        commit = repo.index.commit(message)
        logger.info("Committed: %s (%s)", message, commit.hexsha[:8])
        return commit.hexsha

    def push_branch(self, repo_path: str, branch_name: str) -> None:
        """Push a branch to the remote origin.

        Args:
            repo_path: Path to the local repository.
            branch_name: Branch to push.
        """
        repo = Repo(repo_path)
        self._set_remote_auth(repo)
        repo.remotes.origin.push(branch_name, set_upstream=True)
        logger.info("Pushed branch: %s", branch_name)

    def create_pull_request(
        self,
        repo_name: str,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
    ) -> dict:
        """Create a GitHub pull request.

        Args:
            repo_name: Repository name (e.g., "owner/repo" or just "repo").
            title: PR title.
            body: PR description in markdown.
            head_branch: Source branch.
            base_branch: Target branch.

        Returns:
            Dict with pr_url and pr_number.
        """
        if "/" not in repo_name:
            repo_name = f"{settings.github_owner}/{repo_name}"

        repo = self.github.get_repo(repo_name)
        pr = repo.create_pull(
            title=title,
            body=body,
            head=head_branch,
            base=base_branch,
        )
        logger.info("Created PR #%d: %s", pr.number, pr.html_url)
        return {
            "pr_url": pr.html_url,
            "pr_number": pr.number,
        }

    def get_repo_summary(self, repo_path: str) -> dict:
        """Get a summary of the repository structure.

        Args:
            repo_path: Path to the local repository.

        Returns:
            Dict with file tree and basic stats.
        """
        file_tree: list[str] = []
        total_files = 0

        for root, dirs, files in os.walk(repo_path):
            # Skip hidden and common ignored directories
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".") and d not in ("node_modules", "__pycache__", "venv", ".git")
            ]

            level = root.replace(repo_path, "").count(os.sep)
            indent = "  " * level
            folder_name = os.path.basename(root)
            if level == 0:
                folder_name = "."
            file_tree.append(f"{indent}{folder_name}/")

            sub_indent = "  " * (level + 1)
            for file in sorted(files):
                if not file.startswith("."):
                    file_tree.append(f"{sub_indent}{file}")
                    total_files += 1

        return {
            "tree": "\n".join(file_tree[:200]),  # Cap at 200 lines
            "total_files": total_files,
        }


# Module-level singleton
git_service = GitService()
