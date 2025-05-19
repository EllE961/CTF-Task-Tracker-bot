#!/usr/bin/env python3
"""
GitHub Utilities Module for CTF Task-Tracker Bot

This module handles all interactions with GitHub repositories, including:
- Creating and managing CTF directory structures
- Scaffolding challenge folders and templates
- Creating claim branches for user workflows
- Managing solved markers and file operations
- Listing and deleting CTF resources

All GitHub API operations are run in a thread pool to prevent blocking the bot's
main asyncio event loop, as PyGithub is a synchronous library.

Directory Structure Created:
- ctf-name-year/
  - README.md
  - category/
    - challenge/
      - question/
        - README.md
      - answer/
        - Flag.md
        - writeup.md
        - SOLVED (marker file)

The module also manages claim branches with naming convention:
claim-{username}-{challenge}
"""
import os
import logging
import asyncio
import concurrent.futures
import re
from functools import partial
from typing import List, Dict, Any, Optional

from github import Github, GithubException, ContentFile, UnknownObjectException
from github.Repository import Repository
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger('bot.github')

# GitHub configuration
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPO = os.getenv('GITHUB_REPO')

# Initialize thread pool for GitHub operations
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)

def _get_repo() -> Repository:
    """Get the GitHub repository object."""
    g = Github(GITHUB_TOKEN)
    return g.get_repo(GITHUB_REPO)

async def set_repo_public() -> bool:
    """
    Set the repository visibility to public.
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Run GitHub operations in the thread pool
        loop = asyncio.get_event_loop()
        repo = await loop.run_in_executor(_executor, _get_repo)
        
        # Edit the repository to make it public
        await loop.run_in_executor(
            _executor,
            partial(repo.edit, private=False)
        )
        
        logger.info(f"Repository {GITHUB_REPO} set to public")
        return True
        
    except GithubException as e:
        logger.error(f"GitHub error setting repository to public: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error setting repository to public: {e}")
        return False

async def set_repo_private() -> bool:
    """
    Set the repository visibility to private.
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Run GitHub operations in the thread pool
        loop = asyncio.get_event_loop()
        repo = await loop.run_in_executor(_executor, _get_repo)
        
        # Edit the repository to make it private
        await loop.run_in_executor(
            _executor,
            partial(repo.edit, private=True)
        )
        
        logger.info(f"Repository {GITHUB_REPO} set to private")
        return True
        
    except GithubException as e:
        logger.error(f"GitHub error setting repository to private: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error setting repository to private: {e}")
        return False

async def create_file_if_not_exists(path: str, content: str, message: str) -> bool:
    """
    Create a file in GitHub if it doesn't already exist.
    
    Args:
        path: Path to the file
        content: Content of the file
        message: Commit message
        
    Returns:
        True if file was created, False if it already existed
    """
    try:
        # Run GitHub operations in the thread pool
        loop = asyncio.get_event_loop()
        repo = await loop.run_in_executor(_executor, _get_repo)
        
        try:
            # Check if the file already exists
            await loop.run_in_executor(
                _executor,
                partial(repo.get_contents, path)
            )
            logger.debug(f"File already exists: {path}")
            return False
        except UnknownObjectException:
            # File doesn't exist, create it
            await loop.run_in_executor(
                _executor,
                partial(
                    repo.create_file,
                    path=path,
                    message=message,
                    content=content
                )
            )
            logger.info(f"Created file: {path}")
            return True
            
    except GithubException as e:
        logger.error(f"GitHub error creating file {path}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating file {path}: {e}")
        raise

async def list_ctf_directories() -> List[str]:
    """
    List all CTF directories in the root of the GitHub repository.
    
    Returns:
        List of CTF directory names (e.g. ["dam-2025", "test-2024"])
    """
    try:
        # Run GitHub operations in the thread pool
        loop = asyncio.get_event_loop()
        repo = await loop.run_in_executor(_executor, _get_repo)
        
        # Get all contents at the root level
        contents = await loop.run_in_executor(
            _executor,
            partial(repo.get_contents, "")
        )
        
        # Filter for directories and follow CTF naming pattern (name-year)
        ctf_dirs = []
        
        for item in contents:
            if item.type == "dir":
                # Check if the directory name matches the CTF pattern (name-year)
                if re.match(r'^[a-z0-9_-]+-\d{4}$', item.name):
                    ctf_dirs.append(item.name)
        
        logger.debug(f"Found {len(ctf_dirs)} CTF directories: {ctf_dirs}")
        return ctf_dirs
        
    except GithubException as e:
        logger.error(f"GitHub error listing CTF directories: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error listing CTF directories: {e}")
        return []

async def create_scaffold(ctf_name: str, ctf_year: int, category: str, challenge_name: str) -> bool:
    """
    Create the folder structure for a new challenge in the GitHub repository.
    
    Args:
        ctf_name: Name of the CTF
        ctf_year: Year of the CTF
        category: Challenge category (e.g., 'pwn', 'web')
        challenge_name: Name of the challenge
        
    Returns:
        True if successful, False otherwise
    """
    
    # Format the CTF folder name: "CTF-YEAR"
    ctf_folder = f"{ctf_name.lower()}-{ctf_year}"
    
    # Define the paths
    question_path = f"{ctf_folder}/{category.lower()}/{challenge_name}/question/README.md"
    flag_path = f"{ctf_folder}/{category.lower()}/{challenge_name}/answer/Flag.md"
    writeup_path = f"{ctf_folder}/{category.lower()}/{challenge_name}/answer/writeup.md"
    
    # Define the initial content
    question_content = f"# {challenge_name}\n\nChallenge description goes here.\n"
    flag_content = "# Flag\n\nAdd the flag here once found.\n"
    writeup_content = f"# {challenge_name} Writeup\n\nAdd your solution approach here.\n"
    
    try:
        # Run GitHub operations in the thread pool
        loop = asyncio.get_event_loop()
        repo = await loop.run_in_executor(_executor, _get_repo)
        
        # Check if paths already exist
        for path, content in [
            (question_path, question_content),
            (flag_path, flag_content),
            (writeup_path, writeup_content)
        ]:
            try:
                # Try to get the file (check if it exists)
                await loop.run_in_executor(
                    _executor, 
                    partial(repo.get_contents, path)
                )
                logger.warning(f"File already exists: {path}")
            except UnknownObjectException:
                # File doesn't exist, create it
                commit_msg = f"Scaffold {ctf_folder}/{category}/{challenge_name}"
                await loop.run_in_executor(
                    _executor,
                    partial(
                        repo.create_file,
                        path=path,
                        message=commit_msg,
                        content=content
                    )
                )
                logger.info(f"Created file: {path}")
        
        return True
        
    except GithubException as e:
        logger.error(f"GitHub error creating scaffold: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error creating scaffold: {e}")
        return False

async def create_claim_branch(ctf_name: str, ctf_year: int, username: str, challenge_name: str) -> str:
    """
    Create a branch for a user claiming a challenge.
    
    Args:
        ctf_name: Name of the CTF
        ctf_year: Year of the CTF
        username: Discord username
        challenge_name: Name of the challenge
        
    Returns:
        Branch name if successful, empty string otherwise
    """
    # Format branch name: "claim-username-challenge"
    # Remove spaces and special characters from username and challenge
    safe_username = ''.join(c for c in username if c.isalnum() or c == '_' or c == '-')
    safe_challenge = ''.join(c for c in challenge_name if c.isalnum() or c == '_' or c == '-')
    branch_name = f"claim-{safe_username}-{safe_challenge}"
    
    try:
        # Run GitHub operations in the thread pool
        loop = asyncio.get_event_loop()
        repo = await loop.run_in_executor(_executor, _get_repo)
        
        # Get the main branch as base
        main_branch = await loop.run_in_executor(
            _executor,
            partial(repo.get_branch, "main")
        )
        
        # Create the branch from main
        await loop.run_in_executor(
            _executor,
            partial(
                repo.create_git_ref,
                ref=f"refs/heads/{branch_name}",
                sha=main_branch.commit.sha
            )
        )
        
        logger.info(f"Created branch: {branch_name}")
        return branch_name
        
    except GithubException as e:
        if e.status == 422:  # Branch already exists
            logger.warning(f"Branch already exists: {branch_name}")
            return branch_name
        else:
            logger.error(f"GitHub error creating branch: {e}")
            return ""
    except Exception as e:
        logger.error(f"Unexpected error creating branch: {e}")
        return ""

async def mark_challenge_solved(ctf_name: str, ctf_year: int, category: str, challenge_name: str) -> bool:
    """
    Mark a challenge as solved by creating an empty SOLVED file.
    
    Args:
        ctf_name: Name of the CTF
        ctf_year: Year of the CTF
        category: Challenge category
        challenge_name: Name of the challenge
        
    Returns:
        True if successful, False otherwise
    """
    # Format the CTF folder name: "CTF-YEAR"
    ctf_folder = f"{ctf_name.lower()}-{ctf_year}"
    
    # Define the path for the SOLVED marker file
    solved_path = f"{ctf_folder}/{category.lower()}/{challenge_name}/answer/SOLVED"
    
    try:
        # Run GitHub operations in the thread pool
        loop = asyncio.get_event_loop()
        repo = await loop.run_in_executor(_executor, _get_repo)
        
        # Create the SOLVED file (empty content)
        await loop.run_in_executor(
            _executor,
            partial(
                repo.create_file,
                path=solved_path,
                message=f"Mark {challenge_name} as solved",
                content=""
            )
        )
        
        logger.info(f"Marked as solved: {solved_path}")
        return True
        
    except GithubException as e:
        if e.status == 422:  # File already exists
            logger.warning(f"Already marked as solved: {solved_path}")
            return True
        else:
            logger.error(f"GitHub error marking as solved: {e}")
            return False
    except Exception as e:
        logger.error(f"Unexpected error marking as solved: {e}")
        return False

async def delete_path(path: str) -> bool:
    """
    Delete a file or directory from the GitHub repository.
    For directories, recursively deletes all contents.
    
    Args:
        path: Path to delete
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Run GitHub operations in the thread pool
        loop = asyncio.get_event_loop()
        repo = await loop.run_in_executor(_executor, _get_repo)
        
        # Get contents at the path
        contents = await loop.run_in_executor(
            _executor,
            partial(repo.get_contents, path)
        )
        
        # Handle directory (list of ContentFile objects) or single file
        if isinstance(contents, list):
            # It's a directory - recursively delete contents
            for item in contents:
                await delete_path(item.path)
        else:
            # It's a file - delete it
            await loop.run_in_executor(
                _executor,
                partial(
                    repo.delete_file,
                    path=contents.path,
                    message=f"Delete {contents.path}",
                    sha=contents.sha
                )
            )
            logger.info(f"Deleted file: {contents.path}")
        
        return True
        
    except UnknownObjectException:
        # Path doesn't exist
        logger.warning(f"Path not found for deletion: {path}")
        return True  # Consider this a success since the goal is for the path not to exist
    except GithubException as e:
        logger.error(f"GitHub error deleting path {path}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error deleting path {path}: {e}")
        return False

async def delete_claim_branches(ctf_name: str, ctf_year: int) -> int:
    """
    Delete all claim branches for a specific CTF.
    
    Args:
        ctf_name: Name of the CTF
        ctf_year: Year of the CTF
        
    Returns:
        Number of branches deleted
    """
    # Format the CTF folder name: "CTF-YEAR"
    ctf_folder = f"{ctf_name.lower()}-{ctf_year}"
    deleted_count = 0
    
    try:
        # Run GitHub operations in the thread pool
        loop = asyncio.get_event_loop()
        repo = await loop.run_in_executor(_executor, _get_repo)
        
        # Get all branches
        branches = await loop.run_in_executor(
            _executor,
            repo.get_branches
        )
        
        # Filter branches that start with "claim-" and are related to this CTF
        for branch in branches:
            if branch.name.startswith("claim-"):
                try:
                    # Get the commit message to check if it's related to this CTF
                    commit = await loop.run_in_executor(
                        _executor,
                        partial(repo.get_commit, branch.commit.sha)
                    )
                    
                    # If the commit message contains the CTF folder, it's related
                    if ctf_folder in commit.commit.message:
                        # Delete the branch
                        await loop.run_in_executor(
                            _executor,
                            partial(
                                repo.get_git_ref(f"heads/{branch.name}").delete
                            )
                        )
                        logger.info(f"Deleted branch: {branch.name}")
                        deleted_count += 1
                except GithubException as e:
                    logger.warning(f"Error checking/deleting branch {branch.name}: {e}")
        
        return deleted_count
        
    except GithubException as e:
        logger.error(f"GitHub error deleting claim branches: {e}")
        return deleted_count
    except Exception as e:
        logger.error(f"Unexpected error deleting claim branches: {e}")
        return deleted_count

async def get_repo_structure(path: str = "") -> dict:
    """
    Get the structure of the repository recursively.
    
    Args:
        path: Path to get the structure from (empty for root)
        
    Returns:
        A nested dictionary representing the repository structure
    """
    try:
        # Run GitHub operations in the thread pool
        loop = asyncio.get_event_loop()
        repo = await loop.run_in_executor(_executor, _get_repo)
        
        # Get contents at the path
        contents = await loop.run_in_executor(
            _executor,
            partial(repo.get_contents, path)
        )
        
        # Initialize structure
        structure = {}
        
        # If it's a single file, return its name
        if not isinstance(contents, list):
            return {"type": "file", "name": contents.name}
        
        # Process directory contents
        for item in contents:
            if item.type == "dir":
                # Recursively get structure of subdirectory
                sub_structure = await get_repo_structure(item.path)
                structure[item.name] = sub_structure
            else:
                # Add file to structure
                structure[item.name] = {"type": "file"}
        
        return {"type": "dir", "contents": structure}
        
    except GithubException as e:
        logger.error(f"GitHub error getting repo structure: {e}")
        return {"type": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Unexpected error getting repo structure: {e}")
        return {"type": "error", "message": str(e)}

def format_repo_structure(structure: dict, prefix: str = "") -> str:
    """
    Format the repository structure as a text-based tree.
    
    Args:
        structure: Repository structure dictionary
        prefix: Prefix for indentation
        
    Returns:
        Formatted string representation of the repository
    """
    if structure.get("type") == "error":
        return f"Error: {structure.get('message', 'Unknown error')}"
    
    if structure.get("type") == "file":
        return f"{prefix}📄 {structure.get('name', 'unnamed')}"
    
    result = []
    contents = structure.get("contents", {})
    
    # Sort items: directories first, then files, both alphabetically
    dirs = []
    files = []
    
    for name, item in contents.items():
        if item.get("type") == "dir":
            dirs.append((name, item))
        else:
            files.append((name, item))
    
    # Sort each list
    dirs.sort(key=lambda x: x[0])
    files.sort(key=lambda x: x[0])
    
    # Process directories
    for i, (name, item) in enumerate(dirs):
        is_last_dir = (i == len(dirs) - 1 and len(files) == 0)
        if is_last_dir:
            result.append(f"{prefix}└── 📁 {name}/")
            sub_prefix = f"{prefix}    "
        else:
            result.append(f"{prefix}├── 📁 {name}/")
            sub_prefix = f"{prefix}│   "
        
        # Add subdirectory contents
        sub_result = format_repo_structure(item, sub_prefix)
        if sub_result:
            result.append(sub_result)
    
    # Process files
    for i, (name, _) in enumerate(files):
        if i == len(files) - 1:
            result.append(f"{prefix}└── 📄 {name}")
        else:
            result.append(f"{prefix}├── 📄 {name}")
    
    return "\n".join(result) 