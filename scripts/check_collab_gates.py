#!/usr/bin/env python3
"""Prerequisite gates for the Collaborative VR + web accounts track (docs/BUILD_PLAN.md steps
13-29) and the guided tour bot track (steps 30-34). Identity is two hardcoded accounts (SKETCHSCAPE_AUTH_MODE=demo) selected with an
in-app account switcher -- there is no Clerk or Meta account setup in this plan (decision
2026-09-26). Steps 14 and 18, which were Quest Meta-identity work, are retired.

Usage:
  python3 scripts/check_collab_gates.py <step>        # may I START this step? checks all prerequisites
  python3 scripts/check_collab_gates.py --done <step> # is this step itself finished?
  python3 scripts/check_collab_gates.py --status      # table of every step

Exit code 0 = all required checks pass, 1 = something is missing.
Offline and read-only: no network, no AWS, no Unity Editor, no writes.
Evidence is looked for in code and config; facts no script can see (dashboard
setup, on-device tests) come from config/collab-vr/gates.json, which only the
user may confirm. Every run also scans for leaked secrets.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
APP = ROOT / "web-app"
GATES_FILE = ROOT / "config" / "collab-vr" / "gates.json"
TOOLS_FILE = ROOT / "config" / "nemoclaw" / "sketchscape-tools.json"
UNITY = Path(os.environ.get("SKETCHSCAPE_UNITY_PROJECT", ROOT.parent / "HackGTUnity")).resolve()

SECRET_PATTERNS = {
    "Clerk secret key": re.compile(r"\bsk_(live|test)_[A-Za-z0-9]{10,}"),
    "Meta app access token (OC|app_id|app_secret)": re.compile(r"OC\|\d{6,}\|[0-9a-fA-F]{32}"),
    "xAI API key": re.compile(r"\bxai-[A-Za-z0-9]{20,}"),
    "secret assigned in a file": re.compile(
        r"\b(CLERK_SECRET_KEY|META_MODEL_API_KEY|XAI_API_KEY|NEBIUS_API_KEY|SKETCHSCAPE_META_APP_SECRET|"
        r"SKETCHSCAPE_ROOM_TOKEN_SECRET|SKETCHSCAPE_WORKER_TOKEN|SKETCHSCAPE_NEMOCLAW_TOKEN)[ \t]*[=:][ \t]*[\"']?(?!<|your|\$)[A-Za-z0-9_.\-/+]{16,}"
    ),
}
VITE_SECRET_VAR = re.compile(r"\bVITE_[A-Z0-9_]*SECRET[A-Z0-9_]*\b")
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".txt", ".cs", ".asset", ".xml",
                 ".yml", ".yaml", ".toml", ".sh", ".env", ".tf", ".tfvars", ".html", ".cfg", ".ini"}


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def manual(name: str) -> tuple[bool, str]:
    try:
        gate = json.loads(read(GATES_FILE))["gates"][name]
    except (KeyError, json.JSONDecodeError):
        return False, f"manual gate '{name}' missing from {rel(GATES_FILE)}"
    if gate.get("value") is True and gate.get("confirmed_by") and gate.get("confirmed_on"):
        return True, f"manual gate '{name}' confirmed by {gate['confirmed_by']} on {gate['confirmed_on']}"
    if gate.get("value") is True:
        return False, f"manual gate '{name}' is true but has no confirmed_by/confirmed_on"
    return False, f"manual gate '{name}' not confirmed by the user: {gate.get('meaning', '')}"


def contains(path: Path, needle: str, label: str) -> tuple[bool, str]:
    ok = needle in read(path)
    return ok, f"{rel(path)} {'contains' if ok else 'is missing'} {label}"


def count_at_least(path: Path, needle: str, n: int, label: str) -> tuple[bool, str]:
    found = read(path).count(needle)
    return found >= n, f"{rel(path)} has {found}/{n} {label}"


def exists(path: Path) -> tuple[bool, str]:
    return path.exists(), f"{rel(path)} {'exists' if path.exists() else 'does not exist'}"


def app_source_contains(needle: str, label: str) -> tuple[bool, str]:
    src = APP / "src"
    if not src.exists():
        return False, "web-app/src does not exist"
    for path in src.rglob("*"):
        if path.suffix in {".ts", ".tsx", ".js", ".jsx"} and needle in read(path):
            return True, f"{rel(path)} has {label}"
    return False, f"nothing under web-app/src has {label}"


def unity_cloud_linked() -> tuple[bool, str]:
    text = read(UNITY / "ProjectSettings" / "ProjectSettings.asset")
    if not text:
        return False, f"Unity project not found at {UNITY} (set SKETCHSCAPE_UNITY_PROJECT)"
    match = re.search(r"cloudProjectId:\s*(\S+)", text)
    return bool(match), "HackGTUnity is linked to a Unity Cloud project" if match else "HackGTUnity has no cloudProjectId"


def unity_deps() -> dict:
    try:
        return json.loads(read(UNITY / "Packages" / "manifest.json"))["dependencies"]
    except (KeyError, json.JSONDecodeError):
        return {}


def unity_has(package: str) -> tuple[bool, str]:
    ok = package in unity_deps()
    return ok, f"HackGTUnity {'has' if ok else 'does not have'} {package}"


def unity_package_major(package: str, major: int) -> tuple[bool, str]:
    version = unity_deps().get(package)
    if version is None:
        return False, f"HackGTUnity does not have {package}"
    ok = version.split(".")[0] == str(major)
    return ok, f"HackGTUnity has {package} {version} (need {major}.x)"


def unity_script_contains(needle: str) -> tuple[bool, str]:
    assets = UNITY / "Assets"
    if not assets.exists():
        return False, f"Unity Assets folder not found at {assets}"
    for script in assets.rglob("*.cs"):
        if needle in read(script):
            return True, f"{script.relative_to(UNITY)} references {needle}"
    return False, f"no C# script under HackGTUnity/Assets references {needle}"


def tool_implemented(tool_id: str) -> tuple[bool, str]:
    try:
        ops = json.loads(read(TOOLS_FILE))["http_operations"]
    except (KeyError, json.JSONDecodeError):
        return False, f"cannot read {rel(TOOLS_FILE)}"
    for op in ops:
        if op.get("id") == tool_id:
            status = op.get("implementation_status")
            return status == "implemented", f"registry {tool_id} status is '{status}' (need 'implemented')"
    return False, f"registry has no entry {tool_id}"


def _candidate_files() -> list[Path]:
    try:
        listed = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard"],
            capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        paths = [ROOT / f for f in listed]
    except (OSError, subprocess.CalledProcessError):
        paths = [p for p in ROOT.rglob("*") if not {".venv", ".git", "node_modules"} & set(p.parts)]
    # Vite bakes VITE_* variables from web-app/.env* into the public bundle even though .env is git-ignored.
    if APP.exists():
        paths += [p for p in APP.glob(".env*")]
    if UNITY.exists():
        paths += [p for p in (UNITY / "Assets").rglob("*") if p.suffix in {".cs", ".json", ".asset", ".txt", ".xml"}]
        paths += list((UNITY / "ProjectSettings").glob("*.asset"))
    return paths


def no_leaked_secrets() -> tuple[bool, str]:
    hits: list[str] = []
    for path in _candidate_files():
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        if path.suffix not in TEXT_SUFFIXES and not path.name.startswith(".env"):
            continue
        text = read(path)
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                hits.append(f"{label} in {path}")
        if path.is_relative_to(APP) and VITE_SECRET_VAR.search(text):
            hits.append(f"VITE_*SECRET* variable (would ship in the public bundle) in {path}")
    if hits:
        return False, "LEAKED SECRET: " + "; ".join(hits)
    return True, "no leaked secrets (Clerk/Meta/xAI keys, secret env assignments, VITE_*SECRET*)"


MAIN = BACKEND / "main.py"
STORAGE = BACKEND / "storage.py"
AUTH = BACKEND / "auth.py"
TEST_API = BACKEND / "test_api.py"

STEPS: dict[int, dict] = {
    1: {"title": "Contributor data model + storage", "skill": "contributor-data-model", "deps": [],
        "checks": [lambda: contains(MAIN, "class Contributor(", "Contributor model"),
                   lambda: contains(STORAGE, "def append_contributor", "append_contributor")]},
    2: {"title": "Contributor API endpoints", "skill": "contributor-api-endpoints", "deps": [1],
        "checks": [lambda: contains(MAIN, "/v1/projects/{project_id}/contributors", "contributors route"),
                   lambda: contains(MAIN, "/v1/projects/{project_id}/contributions", "contributions route")]},
    3: {"title": "NemoClaw agent + Unity MCP setup", "skill": "nemoclaw-agent-setup", "deps": [],
        "checks": [lambda: manual("nemoclaw_agent_ready")]},
    5: {"title": "connection/compose endpoint (mock path)", "skill": "connection-compose-endpoint", "deps": [1, 2],
        "checks": [lambda: contains(MAIN, "/v1/projects/{project_id}/connection/compose", "compose route")]},
    7: {"title": "Notability sketch assets (flat card + memory plaque)", "skill": "sketch-image-gen-backends", "deps": [],
        "checks": [lambda: contains(MAIN, "/sketch-assets", "sketch asset route")]},
    13: {"title": "Collaborative VR + web accounts: scope approval", "skill": "collab-vr-accounts-and-gates", "deps": [],
         "checks": [lambda: manual("scope_approved")]},
    15: {"title": "Backend revision safety (based_on_revision, conditional writes, LIVE pointer)", "skill": "backend-revision-concurrency", "deps": [],
         "checks": [lambda: count_at_least(STORAGE, "attribute_not_exists", 2, "conditional puts"),
                    lambda: contains(MAIN, "base_revision", "base_revision handling"),
                    lambda: contains(STORAGE, "set_live_revision", "LIVE pointer compare-and-set"),
                    lambda: contains(TEST_API, "base_revision", "base_revision tests")]},
    16: {"title": "Backend auth core (hardcoded demo accounts, mock mode, fail-fast)", "skill": "backend-auth-clerk", "deps": [15],
         "checks": [lambda: exists(AUTH),
                    lambda: contains(AUTH, "SKETCHSCAPE_AUTH_MODE", "SKETCHSCAPE_AUTH_MODE"),
                    lambda: contains(AUTH, "SKETCHSCAPE_DEMO_USERS", "hardcoded demo accounts"),
                    lambda: exists(BACKEND / "test_auth.py")]},
    17: {"title": "Membership, invites, contributor <-> account binding, object ownership", "skill": "room-api-and-ownership", "deps": [2, 16],
         "checks": [lambda: contains(MAIN, "clerk_user_id", "account id on Contributor"),
                    lambda: contains(MAIN, "invite_code", "project invite code"),
                    lambda: contains(TEST_API, "clerk_user_id", "membership/ownership tests")]},
    19: {"title": "Web app foundation (web-app/: React + Vite, hardcoded-account picker, API client)", "skill": "web-app-foundation", "deps": [16],
         "checks": [lambda: contains(APP / "package.json", "vite", "vite"),
                    lambda: app_source_contains("X-SketchScape-Dev-User", "account-picker header on every API call")]},
    20: {"title": "Web uploads with object-name entry, Notability sketches, optional text, invites", "skill": "web-uploads-and-linking", "deps": [7, 17, 19, 26],
         "checks": [lambda: app_source_contains("/uploads", "upload call"),
                    lambda: app_source_contains("/selections", "selection submit"),
                    lambda: app_source_contains("/jobs", "batch job polling"),
                    lambda: app_source_contains("/sketch-assets", "sketch upload call"),
                    lambda: app_source_contains("memory_text", "optional memory text")]},
    21: {"title": "Public room API (/v1/rooms/{project_id}/state, /edits), hardcoded-account switcher", "skill": "room-api-and-ownership", "deps": [15, 17],
         "checks": [lambda: contains(MAIN, "/v1/rooms/{project_id}/state", "room state route"),
                    lambda: contains(MAIN, "/v1/rooms/{project_id}/edits", "room edits route"),
                    lambda: contains(TEST_API, "/v1/rooms/", "room API tests")]},
    22: {"title": "Unity networking (anonymous sign-in + account switcher, Multiplayer Services, NGO 2.x, Distributed Authority)", "skill": "unity-cloud-collaborative-vr", "deps": [],
         "checks": [unity_cloud_linked,
                    lambda: unity_has("com.unity.services.multiplayer"),
                    lambda: unity_package_major("com.unity.netcode.gameobjects", 2),
                    lambda: unity_script_contains("WithDistributedAuthorityNetwork"),
                    lambda: unity_script_contains("AccountSwitcher"),
                    lambda: manual("account_switcher_verified")]},
    23: {"title": "Unity backprop client (save on settle, session-owner polling)", "skill": "vr-edit-cloud-backprop-sync", "deps": [21, 22],
         "checks": [lambda: unity_script_contains("v1/rooms/")]},
    24: {"title": "NemoClaw room tools", "skill": "top-tier-nemoclaw-tool-design", "deps": [3, 15, 16, 21],
         "checks": [lambda: tool_implemented("room.state.fetch"), lambda: tool_implemented("room.edit.draft")]},
    25: {"title": "Two-headset + web end-to-end verification", "skill": "collab-vr-device-verification", "deps": [20, 23, 29],
         "checks": [lambda: manual("two_headset_verified")]},
    26: {"title": "Durable jobs, shared uploads, upload -> selections -> refine -> generate API, batch polling", "skill": "durable-jobs-and-multi-object-upload", "deps": [15],
         "checks": [lambda: contains(STORAGE, "def claim_next_job", "lease-based job claim"),
                    lambda: contains(STORAGE, "def link_asset", "asset child items"),
                    lambda: contains(MAIN, "/v1/projects/{project_id}/uploads", "upload routes"),
                    lambda: contains(MAIN, "/selections", "person-chosen selection routes"),
                    lambda: contains(MAIN, "/generate", "generate-selected-objects route"),
                    lambda: contains(MAIN, "/v1/projects/{project_id}/jobs", "batch job polling route"),
                    lambda: no_memory_jobs_dict(),
                    lambda: exists(BACKEND / "test_jobs.py")]},
    27: {"title": "GPU worker: SAM 3.1 masks from person-chosen selections, dispatcher, benchmarked concurrency", "skill": "gpu-multi-object-worker", "deps": [26],
         "checks": [lambda: contains(ROOT / "worker" / "segment_sam31_local.py", "def segment_selections", "segment_selections (person-chosen prompts)"),
                    lambda: exists(ROOT / "worker" / "gpu_dispatcher.py"),
                    lambda: contains(ROOT / "worker" / "worker_server.py", "SKETCHSCAPE_GPU_CONCURRENCY", "configurable GPU concurrency"),
                    lambda: manual("gpu_multi_object_verified")]},
    28: {"title": "Letters: backend, recipient-only open, sealed access, scene schema, web form", "skill": "letters-backend-and-web", "deps": [17, 19, 21, 26],
         "checks": [lambda: contains(MAIN, "/v1/projects/{project_id}/letters", "letter upload route"),
                    lambda: contains(MAIN, "/v1/rooms/{project_id}/letters/{letter_id}/open", "recipient open route"),
                    lambda: contains(ROOT / "shared" / "scene.schema.json", '"letter"', "letter source in scene schema"),
                    lambda: app_source_contains("/letters", "letter web form")]},
    29: {"title": "Letters in VR: envelope, networked open animation, 3D paper page", "skill": "letters-vr-envelope", "deps": [22, 28],
         "checks": [lambda: unity_script_contains("/letters/"),
                    lambda: unity_script_contains("LetterEnvelope"),
                    lambda: unity_script_contains("NetworkVariable<")]},
    30: {"title": "Guided tour contract: schema, validation, storage, authoring + activation API, mock author", "skill": "guided-tour-contract", "deps": [5, 15, 17],
         "checks": [lambda: exists(ROOT / "shared" / "guided-tour.schema.json"),
                    lambda: contains(MAIN, "/v1/projects/{project_id}/tours", "tour routes"),
                    lambda: contains(MAIN, "def validate_guided_tour", "tour validator"),
                    lambda: contains(STORAGE, "def set_active_tour_version", "TOURLIVE compare-and-set"),
                    lambda: exists(BACKEND / "test_guided_tour.py")]},
    31: {"title": "NemoClaw author_guided_tour (live tour authoring)", "skill": "nemoclaw-tour-authoring", "deps": [3, 30],
         "checks": [lambda: contains(AUTH, "SKETCHSCAPE_NEMOCLAW_TOKEN", "NemoClaw service token (R14)"),
                    lambda: tool_implemented("tour.draft")]},
    32: {"title": "Guide runtime: room guide API, Muse Spark guide_turn, grounding validator, session memory, TTS", "skill": "muse-guide-runtime", "deps": [30],
         "checks": [lambda: contains(MAIN, "/v1/rooms/{project_id}/guide/sessions", "guide session routes"),
                    lambda: contains(BACKEND / "guide_tools.py", "guide_turn", "per-tour guide_turn tool schema"),
                    lambda: contains(BACKEND / "guide_validator.py", "def validate_turn", "grounding validator"),
                    lambda: exists(BACKEND / "test_guide.py"),
                    lambda: exists(ROOT / "scripts" / "guide_cli.py")]},
    33: {"title": "Unity guide bot (single headset)", "skill": "unity-guide-bot", "deps": [32],
         "checks": [lambda: unity_script_contains("class SketchScapeGuideBot"),
                    lambda: unity_script_contains("/guide/sessions"),
                    lambda: manual("guide_bot_verified")]},
    34: {"title": "Shared guide bot across headsets (session owner drives it)", "skill": "unity-guide-bot", "deps": [22, 33],
         "checks": [lambda: unity_script_contains("SubmitGuideEventRpc"),
                    lambda: manual("shared_guide_verified")]},
}


def no_memory_jobs_dict() -> tuple[bool, str]:
    gone = "jobs: dict[str, ReconstructionJob] = {}" not in read(MAIN)
    return gone, "backend/main.py " + ("no longer keeps jobs in memory" if gone else "still has the in-memory jobs dict")


def step_done(step: int) -> tuple[bool, list[tuple[bool, str]]]:
    results = [check() for check in STEPS[step]["checks"]]
    return all(ok for ok, _ in results), results


def prerequisites(step: int) -> list[int]:
    seen: list[int] = []
    stack = list(STEPS[step]["deps"])
    while stack:
        dep = stack.pop()
        if dep not in seen:
            seen.append(dep)
            stack.extend(STEPS[dep]["deps"])
    return sorted(seen)


def print_results(results: list[tuple[bool, str]], indent: str = "    ") -> None:
    for ok, message in results:
        print(f"{indent}[{'ok' if ok else 'MISSING'}] {message}")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1

    secrets_ok, secrets_msg = no_leaked_secrets()
    print(f"[{'ok' if secrets_ok else 'FAIL'}] {secrets_msg}")

    if argv[0] == "--status":
        for step, info in STEPS.items():
            done, _ = step_done(step)
            print(f"  step {step:>2}  {'done    ' if done else 'not done'}  {info['title']}  (skill: {info['skill']})")
        return 0 if secrets_ok else 1

    if argv[0] == "--done":
        step = int(argv[1])
        done, results = step_done(step)
        print(f"Step {step} ({STEPS[step]['title']}): {'DONE' if done else 'NOT DONE'}")
        print_results(results)
        return 0 if done and secrets_ok else 1

    step = int(argv[0])
    if step not in STEPS:
        print(f"Unknown step {step}. Known: {sorted(STEPS)}")
        return 1
    print(f"Can step {step} ({STEPS[step]['title']}) start?")
    blocked = False
    for dep in prerequisites(step):
        done, results = step_done(dep)
        print(f"  prerequisite step {dep} ({STEPS[dep]['title']}): {'done' if done else 'NOT DONE'}")
        if not done:
            blocked = True
            print_results(results)
            print(f"    -> finish it first with the '{STEPS[dep]['skill']}' skill")
    if blocked or not secrets_ok:
        print(f"BLOCKED: do not start step {step}. Do not stub, fake, or work around a missing prerequisite.")
        return 1
    print(f"READY: step {step} may start. Load the '{STEPS[step]['skill']}' skill.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
