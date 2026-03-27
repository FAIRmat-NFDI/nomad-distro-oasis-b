#!/usr/bin/env python3
import re
import subprocess
import sys
from pathlib import Path


def extract_git_branch_dependencies(toml_content):
    """
    Extract git dependencies that target a specific branch from TOML content.
    Returns a list of package names.
    """
    git_deps = []

    git_pattern = r'"([^"]+?)\s*@\s*git\+https://[^"]*?(?:@([^"]+))?"'

    matches = re.findall(git_pattern, toml_content)
    for package_spec, _ in matches:
        package_name = package_spec.split("@")[0].strip()
        print(package_name, package_spec)
        git_deps.append(package_name)

    return git_deps


def extract_pynxtools_dependencies(toml_content):
    """
    Extract pynxtools* dependencies  from TOML content.
    Returns a list of matching package names.
    """
    pynx_deps = []
    pynx_pattern = r'"(pynxtools[^"]*)"'
    pynx_matches = re.findall(pynx_pattern, toml_content)
    pynx_deps.extend(pynx_matches)

    return pynx_deps


def run_uv_lock_upgrade(packages):
    """
    Run uv lock with --upgrade-package flags for each package.
    If no packages provided, just runs uv lock.
    """
    # Build the command
    cmd = [
        "uv",
        "lock",
        "--upgrade-package",
        "nomad-lab",
        "--upgrade-package",
        "nomad-plugin-gui",
    ]

    # Add --upgrade-package flag for each dependency
    for pkg in packages:
        cmd.extend(["--upgrade-package", pkg])

    print(f"Running command: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("Command executed successfully!")
        print("STDOUT:", result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
    except subprocess.CalledProcessError as e:
        print(f"Command failed with return code {e.returncode}")
        print("STDOUT:", e.stdout)
        print("STDERR:", e.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(
            "Error: 'uv' command not found. Make sure uv is installed and in your PATH."
        )
        sys.exit(1)


def main():
    # Read from pyproject.toml or any TOML file
    toml_file = Path("pyproject.toml")

    if not toml_file.exists():
        print(f"Error: {toml_file} not found in current directory")
        sys.exit(1)

    try:
        with open(toml_file, "r") as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {toml_file}: {e}")
        sys.exit(1)

    # Extract git dependencies
    git_deps = extract_git_branch_dependencies(content)
    raw_pynx_deps = extract_pynxtools_dependencies(content)

    pynx_deps = [
        pkg for pkg in raw_pynx_deps if not any(pkg.startswith(g) for g in git_deps)
    ]

    if git_deps:
        print(f"Found {len(git_deps)} git dependencies with branch targets:")
        for dep in git_deps:
            print(f"  - {dep}")
    else:
        print("No git dependencies with branch targets found in the TOML file.")

    if pynx_deps:
        print(f"Found {len(pynx_deps)} pynxtools dependencies:")
        for dep in pynx_deps:
            print(f"  - {dep}")
    else:
        print("No pynxtools dependencies found in the TOML file.")

    # Always run uv lock (with upgrade flags if git deps found)
    run_uv_lock_upgrade(git_deps + pynx_deps)


if __name__ == "__main__":
    main()
