"""The glob of the tree's file search: KubeCoder's `find_files` syntax
(F150.5)."""

import pytest

from app.utils.path_glob import GlobSyntaxError, PathGlob


class TestPathGlob:
    @pytest.mark.parametrize(
        ("pattern", "path", "matched"),
        [
            ("reference.json", "reference.json", True),
            ("reference.json", "recipe-box/reference.json", False),
            ("reference.json", "reference.jsonx", False),
            pytest.param("*.json", "reference.json", True, id="star-in-a-name"),
            pytest.param(
                "*.json", "recipe-box/plan.json", False, id="star-stops-at-a-slash"
            ),
            pytest.param("*/*.json", "recipe-box/plan.json", True, id="star-per-name"),
            pytest.param(
                "*/*.json", "recipe-box/items/a.json", False, id="star-is-one-name"
            ),
            pytest.param("**/plan.json", "plan.json", True, id="no-directory"),
            pytest.param("**/plan.json", "recipe-box/plan.json", True, id="one"),
            pytest.param("**/plan.json", "a/b/c/plan.json", True, id="several"),
            pytest.param("**/plan.json", "a/myplan.json", False, id="whole-names"),
            pytest.param("recipe-box/**", "recipe-box/items/1-a.md", True, id="tail"),
            pytest.param("recipe-box/**", "bike-log/items/1-a.md", False, id="other"),
            pytest.param("**", "recipe-box/items/1-a.md", True, id="everything"),
            pytest.param(
                "recipe-box/**/*.md", "recipe-box/project.md", True, id="middle-none"
            ),
            pytest.param(
                "recipe-box/**/*.md", "recipe-box/items/1-a.md", True, id="middle-one"
            ),
            pytest.param("a**b", "a/x/y/b", True, id="double-star-crosses-slashes"),
            pytest.param("draft-?/plan.json", "draft-7/plan.json", True, id="one-char"),
            pytest.param(
                "draft-?/plan.json", "draft-12/plan.json", False, id="not-two"
            ),
            pytest.param("a?b", "a/b", False, id="question-is-no-slash"),
            pytest.param("**/{project.md,plan.json}", "x/plan.json", True, id="either"),
            pytest.param("**/{project.md,plan.json}", "x/project.md", True, id="or"),
            pytest.param("**/{project.md,plan.json}", "x/chat.md", False, id="neither"),
            pytest.param("x/{*.md,p?an.json}", "x/plan.json", True, id="wild-inside"),
            pytest.param("x/{a,}b", "x/b", True, id="an-empty-alternative"),
            pytest.param("a,b", "a,b", True, id="a-comma-outside-braces"),
            pytest.param("", "", True, id="the-empty-pattern"),
            pytest.param("", "a", False, id="the-empty-pattern-matches-nothing-else"),
        ],
    )
    def test_a_pattern_matches_a_whole_path(
        self, pattern: str, path: str, matched: bool
    ) -> None:
        assert PathGlob(pattern).matches(path) is matched

    @pytest.mark.parametrize(
        ("pattern", "fault"),
        [
            ("items/[0-9]*.md", "character class '[' at index 6"),
            ("items/0-9].md", "character class ']' at index 9"),
            ("items\\*.md", "backslash escape '\\' at index 5"),
            ("{a,{b,c}}", "nested braces '{' at index 3"),
            ("a}", "unbalanced '}' at index 1"),
            ("x/{a,b", "unbalanced '{' at index 2"),
        ],
    )
    def test_any_other_glob_syntax_is_refused_by_name(
        self, pattern: str, fault: str
    ) -> None:
        with pytest.raises(GlobSyntaxError) as raised:
            PathGlob(pattern)

        assert str(raised.value) == (
            f"Invalid glob pattern: {fault} is not supported"
            " (supported: *, **, ?, {a,b})"
        )

    def test_a_pattern_matches_path_after_path(self) -> None:
        glob = PathGlob("**/items/*.md")

        assert [
            path
            for path in ["a/items/1.md", "a/items/2.txt", "b/items/3.md", "items/4.md"]
            if glob.matches(path)
        ] == ["a/items/1.md", "b/items/3.md", "items/4.md"]
