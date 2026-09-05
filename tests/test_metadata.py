"""Consistency checks for the plugin manifest.

These run without QGIS. They exist because the 0.5.1 release was published to
the official QGIS plugin repository while `metadata.txt` in version control
still declared 0.5.0 and `experimental=True` — a released artefact that could
not be reproduced from the repository. This module makes that class of drift a
build failure instead of a discovery.
"""

import configparser
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Keys the QGIS plugin repository requires, plus the ones a scientific plugin
# should always carry so users can find the source and report problems.
REQUIRED_KEYS = [
    "name",
    "qgisMinimumVersion",
    "description",
    "version",
    "author",
    "email",
    "about",
    "repository",
    "tracker",
    "homepage",
    "license",
    "icon",
]

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def read_metadata():
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(ROOT / "metadata.txt", encoding="utf-8")
    return parser


def test_metadata_file_exists():
    assert (ROOT / "metadata.txt").is_file()


def test_required_keys_present_and_non_empty():
    general = read_metadata()["general"]
    missing = [key for key in REQUIRED_KEYS if not general.get(key, "").strip()]
    assert not missing, f"metadata.txt is missing or empty for: {missing}"


def test_version_is_semver():
    version = read_metadata()["general"]["version"].strip()
    assert SEMVER.match(version), f"version must be MAJOR.MINOR.PATCH, got {version!r}"


def test_plugin_version_constant_matches_metadata():
    """`PLUGIN_VERSION` is written into every diagnostic log, so a mismatch
    means logs from the field cannot be traced back to a release."""
    version = read_metadata()["general"]["version"].strip()
    source = (ROOT / "processing" / "algorithm.py").read_text(encoding="utf-8")
    match = re.search(r'^PLUGIN_VERSION\s*=\s*"([^"]+)"', source, re.MULTILINE)
    assert match, "PLUGIN_VERSION not found in processing/algorithm.py"
    assert match.group(1) == version, (
        f"PLUGIN_VERSION is {match.group(1)!r} but metadata.txt declares {version!r}"
    )


def test_citation_version_matches_metadata():
    version = read_metadata()["general"]["version"].strip()
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    match = re.search(r'^version:\s*"?([^"\n]+)"?', citation, re.MULTILINE)
    assert match, "no version field in CITATION.cff"
    assert match.group(1).strip() == version, (
        f"CITATION.cff declares {match.group(1).strip()!r}, metadata.txt declares {version!r}"
    )


def test_changelog_mentions_current_version():
    general = read_metadata()["general"]
    version = general["version"].strip()
    changelog = general.get("changelog", "")
    assert version in changelog, f"changelog does not mention version {version}"


def test_not_marked_experimental():
    general = read_metadata()["general"]
    assert general.get("experimental", "False").strip().lower() == "false"
    assert general.get("deprecated", "False").strip().lower() == "false"


def test_repository_and_tracker_point_at_this_project():
    general = read_metadata()["general"]
    for key in ("repository", "tracker", "homepage"):
        assert "github.com/LuanCortesM/Topotrail" in general[key], (
            f"{key} does not point at the project repository: {general[key]!r}"
        )


def test_icon_file_exists():
    icon = read_metadata()["general"]["icon"].strip()
    assert (ROOT / icon).is_file(), f"icon declared as {icon!r} but the file is missing"


def test_metadata_parses_with_interpolation_as_plugins_qgis_org_does():
    """plugins.qgis.org le metadata.txt com ConfigParser COM interpolacao: um '%'
    solto ("48%") derruba o upload inteiro com "'%' must be followed by '%' or '('".
    Aconteceu na primeira tentativa de publicar a 1.1.0."""
    import configparser
    text = (ROOT / "metadata.txt").read_text(encoding="utf-8")
    assert "%" not in text, "use 'percent' em vez de '%' no metadata.txt"
    parser = configparser.ConfigParser()          # interpolacao ligada, como no servidor
    parser.read_string(text)
    assert parser["general"]["version"]
