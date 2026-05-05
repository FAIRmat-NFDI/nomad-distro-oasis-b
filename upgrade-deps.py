#!/usr/bin/env python3
import re
import subprocess
import sys
import tomllib
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
    deps_pattern = [r'"(pynxtools[^"=<>!~\s]*)', r'"(nomad-north-[^"=<>!~\s]*)']
    for dep_pattern in deps_pattern:
        pynx_matches = re.findall(dep_pattern, toml_content)
        pynx_deps.extend(pynx_matches)

    return pynx_deps


def extract_exact_pinned_dependencies(toml_content, allowed_packages=None):
    """
    Extract dependencies pinned with == from TOML content.
    Returns a list of package names.
    """
    pinned_pattern = r'"([A-Za-z0-9_.-]+)==[^\"]+"'
    pinned_deps = re.findall(pinned_pattern, toml_content)

    if allowed_packages is None:
        return pinned_deps

    allowed_names = {normalize_name(package) for package in allowed_packages}
    return [
        package
        for package in pinned_deps
        if normalize_name(package) in allowed_names
    ]


def normalize_name(package_name):
    """Normalize package names using PEP 503 style semantics."""
    return re.sub(r"[-_.]+", "-", package_name).lower()


def load_lock_versions(lock_file):
    """
    Load resolved package versions from uv.lock.
    Returns a mapping from normalized package name to resolved version.
    """
    try:
        lock_data = tomllib.loads(lock_file.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"Error reading {lock_file}: {e}")
        sys.exit(1)

    versions = {}
    for package in lock_data.get("package", []):
        name = package.get("name")
        version = package.get("version")
        if not name or not version:
            continue
        versions.setdefault(normalize_name(name), version)

    return versions


def update_exact_pins_in_pyproject(toml_file, package_versions, allowed_packages=None):
    """
    Rewrite exact pins in pyproject.toml using resolved versions from uv.lock.
    Returns True if any replacements were made.
    """
    try:
        content = toml_file.read_text(encoding="utf-8")
    except OSError as e:
        print(f"Error reading {toml_file}: {e}")
        sys.exit(1)

    changed = False
    allowed_names = None
    if allowed_packages is not None:
        allowed_names = {normalize_name(package) for package in allowed_packages}

    def replace_pin(match):
        nonlocal changed

        package_name = match.group("name")
        current_version = match.group("version")

        if allowed_names is not None and normalize_name(package_name) not in allowed_names:
            return match.group(0)

        resolved_version = package_versions.get(normalize_name(package_name))

        if not resolved_version:
            return match.group(0)

        if current_version == resolved_version:
            return match.group(0)

        changed = True
        if current_version is None:
            print(f"Pinning {package_name} to {resolved_version}")
        else:
            print(f"Updating {package_name}: {current_version} -> {resolved_version}")
        return f'"{package_name}=={resolved_version}"'

    updated_content = re.sub(
        r'"(?P<name>[A-Za-z0-9_.-]+)(?:==(?P<version>[^\"]+))?"',
        replace_pin,
        content,
    )

    if changed:
        try:
            toml_file.write_text(updated_content, encoding="utf-8")
        except OSError as e:
            print(f"Error writing {toml_file}: {e}")
            sys.exit(1)

    return changed


def relax_exact_pins_in_pyproject(toml_file, allowed_packages):
    """
    Temporarily remove exact pins for selected packages so uv can resolve newer
    versions. Returns True if any replacements were made.
    """
    try:
        content = toml_file.read_text(encoding="utf-8")
    except OSError as e:
        print(f"Error reading {toml_file}: {e}")
        sys.exit(1)

    allowed_names = {normalize_name(package) for package in allowed_packages}
    changed = False

    def replace_pin(match):
        nonlocal changed

        package_name = match.group("name")
        if normalize_name(package_name) not in allowed_names:
            return match.group(0)

        changed = True
        print(f"Relaxing exact pin for {package_name}")
        return f'"{package_name}"'

    updated_content = re.sub(
        r'"(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\"]+)"',
        replace_pin,
        content,
    )

    if changed:
        try:
            toml_file.write_text(updated_content, encoding="utf-8")
        except OSError as e:
            print(f"Error writing {toml_file}: {e}")
            sys.exit(1)

    return changed


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
        raise RuntimeError("uv lock failed") from e
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Error: 'uv' command not found. Make sure uv is installed and in your PATH."
        ) from exc


def main():
    # Read from pyproject.toml or any TOML file
    toml_file = Path("pyproject.toml")

    if not toml_file.exists():
        print(f"Error: {toml_file} not found in current directory")
        sys.exit(1)

    try:
        content = toml_file.read_text(encoding="utf-8")
    except OSError as e:
        print(f"Error reading {toml_file}: {e}")
        sys.exit(1)

    # Extract git dependencies
    git_deps = extract_git_branch_dependencies(content)
    raw_pynx_deps = extract_pynxtools_dependencies(content)
    pinned_deps = extract_exact_pinned_dependencies(content, raw_pynx_deps)

    pynx_deps = [
        pkg for pkg in raw_pynx_deps if not any(pkg.startswith(g) for g in git_deps)
    ]

    packages_to_pin = list(dict.fromkeys(pynx_deps))

    packages_to_upgrade = list(dict.fromkeys(git_deps + pynx_deps + pinned_deps))

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

    if pinned_deps:
        print(f"Found {len(pinned_deps)} exact pinned dependencies:")
        for dep in pinned_deps:
            print(f"  - {dep}")
    else:
        print("No exact pinned dependencies found in the TOML file.")

    lock_file = Path("uv.lock")
    original_content = content

    try:
        if packages_to_pin and relax_exact_pins_in_pyproject(toml_file, packages_to_pin):
            print("Temporarily relaxed exact pins in pyproject.toml.")

        run_uv_lock_upgrade(packages_to_upgrade)

        lock_versions = load_lock_versions(lock_file)
        if update_exact_pins_in_pyproject(toml_file, lock_versions, packages_to_pin):
            print(
                "Updated exact pins in pyproject.toml from resolved versions; relocking to keep uv.lock in sync."
            )
            run_uv_lock_upgrade(packages_to_upgrade)
        else:
            print("No exact pins in pyproject.toml needed updating.")
    except RuntimeError as e:
        try:
            toml_file.write_text(original_content, encoding="utf-8")
        except OSError:
            pass
        print(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
