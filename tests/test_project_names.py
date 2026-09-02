"""Project names from the URL are validated on every path (issue #11).

``ProjectState.name`` is injected by Reflex from ``/project/[name]``, so it is
raw user input on every read path, not only at creation. Before this, a name
like ``../..`` resolved to a directory outside ``projects/`` that the app would
then upload into and launch a full-permissions coding agent in.
"""

from __future__ import annotations

import pytest

from groundhog.lib import fs

# Names that are already their own slug, so the app could have created them.
VALID = ["churn-model", "a", "a_b", "project-1", "under_score", "9"]

# Everything else: traversal, separators, absolute paths, the empty string
# (which is its own slug but resolves to PROJECTS_DIR itself), and names that
# merely differ from their slug.
INVALID = [
    "..",
    "../..",
    "../../..",
    "a/../..",
    "foo/bar",
    "/etc",
    "/",
    ".",
    "",
    "   ",
    "My Project",
    "UPPER",
    "trailing-",
    "café",
    "\x00evil",
    "project.name",
    "~",
]


# --- the name check ---------------------------------------------------------

@pytest.mark.parametrize("name", VALID)
def test_valid_names_are_accepted(name):
    assert fs.is_valid_project_name(name)
    assert fs.validate_project_name(name) == name


@pytest.mark.parametrize("name", INVALID)
def test_invalid_names_are_rejected(name):
    assert not fs.is_valid_project_name(name)
    with pytest.raises(fs.InvalidProjectName):
        fs.validate_project_name(name)


def test_none_is_rejected_rather_than_raising_attribute_error():
    assert not fs.is_valid_project_name(None)


def test_slugify_is_idempotent():
    """The check relies on this: a name equal to its own slug is one that
    create_project could have produced."""
    for raw in INVALID + VALID + ["Mixed Case Name!!", "a  b", "--x--"]:
        assert fs.slugify(fs.slugify(raw)) == fs.slugify(raw)


# --- the path helpers -------------------------------------------------------

@pytest.mark.parametrize("name", INVALID)
def test_project_dir_refuses_to_build_a_path(sandbox, name):
    with pytest.raises(fs.InvalidProjectName):
        fs.project_dir(name)


def test_empty_name_does_not_resolve_to_the_projects_directory(sandbox):
    """PROJECTS_DIR / "" is PROJECTS_DIR, and "" is its own slug, so an
    is-it-inside-projects check alone would let it through."""
    with pytest.raises(fs.InvalidProjectName):
        fs.project_dir("")


@pytest.mark.parametrize(
    "helper",
    ["data_dir", "experiments_dir", "results_path", "analysis_path", "metadata_path"],
)
def test_every_path_helper_inherits_the_check(sandbox, helper):
    with pytest.raises(fs.InvalidProjectName):
        getattr(fs, helper)("../..")


def test_project_dir_returns_the_unresolved_path_for_valid_names(sandbox):
    fs.create_project("Churn Model")
    assert fs.project_dir("churn-model") == fs.PROJECTS_DIR / "churn-model"


def test_symlink_out_of_the_projects_dir_is_rejected(sandbox, tmp_path):
    """A valid slug can still escape if a symlink is planted inside
    projects/, which the name check alone cannot see."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (fs.PROJECTS_DIR / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(fs.InvalidProjectName):
        fs.project_dir("escape")
    assert not fs.project_exists("escape")


# --- the read paths that used to accept anything ----------------------------

def test_project_exists_reports_false_instead_of_raising(sandbox):
    assert fs.project_exists("../..") is False
    assert fs.project_exists("") is False


def test_stage_is_forbidden_for_a_traversal_name(sandbox):
    """The traversal target exists on disk, so the old code reported a real
    stage and the UI rendered a working project page for it. After the fix
    the name is rejected as forbidden (Access denied), not a missing slug."""
    assert fs.project_stage("../..") == "forbidden"
    assert fs.project_stage("..") == "forbidden"


@pytest.mark.parametrize(
    "reader",
    ["list_data_files", "read_metadata", "parse_results", "list_experiments",
     "has_analysis", "read_analysis", "has_experiments", "dataset_preview"],
)
def test_readers_refuse_a_traversal_name(sandbox, reader):
    with pytest.raises(fs.InvalidProjectName):
        getattr(fs, reader)("../..")


# --- the write paths --------------------------------------------------------

def test_upload_cannot_write_outside_the_projects_dir(sandbox):
    """The traversal name lands on the upload stage, so this was an
    unauthenticated arbitrary file write before the agent was even involved."""
    with pytest.raises(fs.InvalidProjectName):
        fs.save_data_file("../..", "pwned.csv", b"x")
    assert not (fs.PROJECTS_DIR.parent / "pwned.csv").exists()


def test_metadata_cannot_be_written_outside_the_projects_dir(sandbox):
    with pytest.raises(fs.InvalidProjectName):
        fs.write_metadata("../..", {"eval_metric": "AUC"})


def test_analysis_cannot_be_written_outside_the_projects_dir(sandbox):
    with pytest.raises(fs.InvalidProjectName):
        fs.write_analysis("../..", "# owned")


def test_filename_that_strips_to_nothing_does_not_target_the_data_dir(sandbox):
    slug = fs.create_project("Churn")
    fs.save_data_file(slug, "..", b"col\n1\n")
    assert fs.list_data_files(slug) == ["dataset.csv"]


# --- create_project still works --------------------------------------------

def test_create_project_slugifies_and_the_slug_passes_validation(sandbox):
    slug = fs.create_project("My New Project")
    assert slug == "my-new-project"
    assert fs.is_valid_project_name(slug)
    assert fs.project_exists(slug)


def test_create_project_still_rejects_a_name_with_no_usable_characters(sandbox):
    with pytest.raises(ValueError):
        fs.create_project("...")


# --- the listing ------------------------------------------------------------

def test_listing_skips_directories_the_app_could_not_have_created(sandbox):
    """Hand-made directories would otherwise produce links that 404."""
    fs.create_project("Good One")
    (fs.PROJECTS_DIR / "Hand Made").mkdir()
    assert fs.list_project_names() == ["good-one"]


def test_every_listed_name_round_trips_through_project_dir(sandbox):
    fs.create_project("One")
    fs.create_project("Two")
    (fs.PROJECTS_DIR / "Bad Name").mkdir()
    for name in fs.list_project_names():
        assert fs.project_dir(name).is_dir()
