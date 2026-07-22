"""`.ccignore` matching and walk pruning."""

import os

from ingestion.ignore import is_ignored, load_patterns, walk


def test_load_patterns_strips_comments_blanks_and_slashes(tmp_path):
    (tmp_path / ".ccignore").write_text(
        "# deps\nvendor/\n\n  api/generated/*  # inline\n*.min.js\n"
    )
    assert load_patterns(str(tmp_path)) == ["vendor", "api/generated/*", "*.min.js"]


def test_load_patterns_missing_file():
    assert load_patterns("/nonexistent-repo") == []


def test_bare_pattern_matches_any_component():
    pats = ["vendor"]
    assert is_ignored("vendor", pats)
    assert is_ignored("api/vendor/acme/Foo.php", pats)
    assert not is_ignored("api/src/Vendored.php", pats)


def test_anchored_pattern_is_root_relative():
    pats = ["api/vendor"]
    assert is_ignored("api/vendor/acme/Foo.php", pats)
    assert not is_ignored("web/vendor/acme/Foo.php", pats)


def test_glob_pattern():
    assert is_ignored("static/app.min.js", ["*.min.js"])
    assert not is_ignored("static/app.js", ["*.min.js"])


def test_walk_prunes_ccignore_and_defaults(tmp_path):
    for rel in ["src/a.py", "api/vendor/dep/b.py", "node_modules/c.py",
                "static/app.min.js"]:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
    (tmp_path / ".ccignore").write_text("vendor/\n*.min.js\n")

    seen = {
        os.path.relpath(os.path.join(d, f), tmp_path)
        for d, _, files in walk(str(tmp_path)) for f in files
    }
    assert "src/a.py" in seen
    assert "api/vendor/dep/b.py" not in seen   # .ccignore
    assert "node_modules/c.py" not in seen     # DEFAULT_SKIP
    assert "static/app.min.js" not in seen     # glob on a file, not a dir
