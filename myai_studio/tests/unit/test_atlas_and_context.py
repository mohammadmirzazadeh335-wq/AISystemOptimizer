"""Atlas (project imports) and the context map measured from the real prompt."""

from __future__ import annotations

import pytest

from myai.services.atlas import build_atlas, layout
from myai.services.projects import ProjectService


@pytest.fixture()
def projects(ctx) -> ProjectService:  # noqa: ANN001
    return ProjectService(ctx.paths, ctx.settings)


def make_project(projects: ProjectService, name: str = "atlas-demo", files: dict[str, str] | None = None):
    from myai.core.paths import get_paths

    root = get_paths(projects._paths.home).projects_dir / name  # noqa: SLF001 - test helper
    root.mkdir(parents=True, exist_ok=True)
    payload = files or {
        "main.py": "from pkg.core import run\nimport os\n",
        "pkg/__init__.py": "",
        "pkg/core.py": "from .util import helper\n\ndef run():\n    return helper()\n",
        "pkg/util.py": "def helper():\n    return 1\n",
        "web/app.js": "import { x } from './helpers';\n",
        "web/helpers.js": "export const x = 1;\n",
    }
    for relative, text in payload.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return projects.open_folder(root)


# --------------------------------------------------------------------- atlas
def test_python_and_relative_js_imports_become_edges(projects: ProjectService) -> None:
    project = make_project(projects)
    atlas = build_atlas(projects, project)
    edges = {(edge.source, edge.target) for edge in atlas.edges}
    assert ("main.py", "pkg/core.py") in edges
    assert ("pkg/core.py", "pkg/util.py") in edges
    assert ("web/app.js", "web/helpers.js") in edges


def test_stats_describe_the_real_files(projects: ProjectService) -> None:
    project = make_project(projects)
    atlas = build_atlas(projects, project)
    assert atlas.stats["files"] == 6
    assert atlas.stats["edges"] == 3
    assert atlas.stats["languages"]["python"] == 4
    assert atlas.stats["languages"]["javascript"] == 2
    hub_ids = {hub["id"] for hub in atlas.stats["hubs"]}
    assert "pkg/core.py" in hub_ids
    assert any(node.id == "pkg/__init__.py" for node in atlas.nodes)


def test_comments_and_third_party_imports_do_not_create_edges(projects: ProjectService) -> None:
    project = make_project(
        projects,
        files={
            "a.py": "import os\nimport requests\n# import b\n",
            "b.py": "",
            "c.js": "// import './b'\nimport React from 'react';\n",
        },
    )
    atlas = build_atlas(projects, project)
    assert atlas.edges == ()


def test_atlas_never_leaves_the_project(projects: ProjectService) -> None:
    project = make_project(
        projects,
        files={"a.py": "from ..outside import x\nfrom . import b\n", "b.py": "", "outside.py": ""},
    )
    atlas = build_atlas(projects, project)
    assert all(not node.id.startswith("..") for node in atlas.nodes)
    assert all(not edge.target.startswith("..") for edge in atlas.edges)


def test_nodes_are_ordered_and_layout_is_deterministic(projects: ProjectService) -> None:
    project = make_project(projects)
    first = build_atlas(projects, project)
    second = build_atlas(projects, project)
    assert [node.id for node in first.nodes] == [node.id for node in second.nodes]
    assert [(node.x, node.y) for node in first.nodes] == [(node.x, node.y) for node in second.nodes]
    for node in first.nodes:
        assert 0.0 <= node.x <= 1.0 and 0.0 <= node.y <= 1.0


def test_layout_groups_folders_and_keeps_root_near_the_centre() -> None:
    positions = layout(["main.py", "pkg/a.py", "pkg/b.py", "tests/c.py"])
    root = positions["main.py"]
    assert root == layout(["main.py", "pkg/a.py", "pkg/b.py", "tests/c.py"])["main.py"]
    distance = ((root[0] - 0.5) ** 2 + (root[1] - 0.5) ** 2) ** 0.5
    assert distance < 0.25
    assert positions["pkg/a.py"] != positions["pkg/b.py"]
    assert layout([]) == {}


def test_file_cap_is_reported(projects: ProjectService) -> None:
    from myai.core.paths import get_paths

    root = get_paths(projects._paths.home).projects_dir / "many"  # noqa: SLF001
    root.mkdir(parents=True)
    for index in range(12):
        (root / f"f{index}.py").write_text("x = 1\n", encoding="utf-8")
    atlas = build_atlas(projects, projects.open_folder(root), max_files=5)
    assert len(atlas.nodes) == 5
    assert atlas.stats["truncated"] is True


def test_atlas_handles_an_empty_project(projects: ProjectService) -> None:
    from myai.core.paths import get_paths

    root = get_paths(projects._paths.home).projects_dir / "empty"  # noqa: SLF001
    root.mkdir(parents=True)
    atlas = build_atlas(projects, projects.open_folder(root))
    assert atlas.empty and atlas.stats["files"] == 0


# -------------------------------------------------------------- context map
def test_context_map_measures_the_real_blocks(ctx, sample_conversation) -> None:  # noqa: ANN001
    conversation = sample_conversation
    report = ctx.chat.context_map(conversation)
    categories = [segment.category for segment in report.segments]
    assert categories[0] == "system"
    assert categories.count("history") == 2
    assert report.history_messages == 2
    assert report.total_tokens == sum(segment.tokens for segment in report.segments)
    assert report.window > 0
    assert 0.0 <= report.ratio <= 1.0
    # The measured total equals the diagnostics the sender builds.
    _messages, diagnostics = ctx.chat.build_messages(conversation)
    assert report.total_tokens == diagnostics.total_tokens


def test_memory_and_persona_appear_only_when_enabled(ctx, sample_conversation) -> None:  # noqa: ANN001
    ctx.memory.add("The user prefers concise answers.", conversation_id=None)
    ctx.settings.set("ai.persona_enabled", True)
    ctx.settings.set("ai.persona_text", "Be precise.")
    report = ctx.chat.context_map(sample_conversation)
    categories = {segment.category for segment in report.segments}
    assert {"memory", "persona"} <= categories
    ctx.settings.set("memory.enabled", False)
    without_memory = ctx.chat.context_map(sample_conversation)
    assert "memory" not in {segment.category for segment in without_memory.segments}


def test_context_map_flags_the_largest_segment(ctx, sample_conversation) -> None:  # noqa: ANN001
    ctx.conversations.add_message(
        sample_conversation.id, "user", "x" * 4000
    )
    report = ctx.chat.context_map(ctx.conversations.get(sample_conversation.id))
    largest = report.largest()
    assert largest is not None and largest.category == "history"
    assert largest.chars >= 4000


def test_history_segments_are_capped_but_counted(ctx, sample_conversation) -> None:  # noqa: ANN001
    for index in range(30):
        ctx.conversations.add_message(sample_conversation.id, "user", f"turn {index}")
    conversation = ctx.conversations.get(sample_conversation.id)
    report = ctx.chat.context_map(conversation, max_history_segments=5)
    history = [segment for segment in report.segments if segment.category == "history"]
    assert len(history) == 6  # five shown + one "older" aggregate
    assert history[-1].label.startswith("older")
    assert report.history_messages == 32


def test_context_map_handles_an_empty_conversation(ctx) -> None:  # noqa: ANN001
    conversation = ctx.conversations.create("Empty", select=False)
    report = ctx.chat.context_map(conversation)
    assert report.history_messages == 0
    assert report.segments[0].category == "system"
    assert report.total_tokens == report.segments[0].tokens


def test_by_category_totals_match_segments(ctx, sample_conversation) -> None:  # noqa: ANN001
    report = ctx.chat.context_map(sample_conversation)
    totals = report.by_category()
    assert sum(totals.values()) == report.total_tokens
    assert totals.get("system", 0) > 0


def test_donut_can_draw_a_tiny_share_without_hiding_it(qapp) -> None:  # noqa: ANN001
    from myai.ui.widgets.charts import DonutChart, Slice

    chart = DonutChart()
    chart.resize(200, 200)
    chart.set_data(
        [Slice("a", 35, "#2563EB"), Slice("b", 35, "#10B981"), Slice("c", 30, "#7457E0")],
        "0.1%",
        "of 128,000 tokens",
        fill=0.0013,
    )
    assert chart._fill == pytest.approx(0.0013)  # noqa: SLF001
    # Without a fill the whole ring is used again.
    chart.set_data([Slice("a", 1, "#2563EB")], "100%", "")
    assert chart._fill is None  # noqa: SLF001


def test_gauge_keeps_its_caption_inside_the_widget(qapp) -> None:  # noqa: ANN001
    from myai.ui.widgets.charts import GaugeScore

    gauge = GaugeScore()
    gauge.resize(230, 160)
    gauge.set_score(86, "attention")
    gauge.set_score(100, "healthy")
    assert gauge.score() == 100
    gauge.set_score(0, "needs_care")
    assert gauge.score() == 0
    gauge.set_score(140, "healthy")
    assert gauge.score() == 100
