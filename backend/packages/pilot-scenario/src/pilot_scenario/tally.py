"""The tally: a scenario for exact figures, in the dev seed's own world, all
of it Pilot's work, so that the projects a load puts it on hold it whole.

Pilot sorts the spices in the recipe box, a work item's run of two Turns:
its brief, in which a sub-agent finds where the jars are counted and the
context is compacted, the Call after it missing the cache; and, more than an
hour later, its continuation, whose first Call waits past the hour its cache
lives and misses it. Between the two, Ada and then Ben ask the recipe box's
chat about the spices, a Turn each; and a job tidies the bike log's ride
notes, its first Call reading the whole log, the one expensive Call of the
scenario.

Its Calls and Turns give each figure of the dashboard a case: 16 Calls over
5 Turns of Pilot's, three Sessions of Pilot's, five threads, each seeded
quick filter something to count, and one Call costing more than a dollar
among Calls that cost cents. The model names are the public ones. Everything
else is invented.
"""

from pilot_scenario.script import (
    Call,
    Carried,
    Compaction,
    HookRun,
    Launch,
    Prompt,
    Ran,
    Scenario,
    Session,
    SubAgent,
    Tokens,
    ToolUse,
    Turn,
    Unit,
)
from pilot_scenario.transcript import MANAGED

OPUS = "claude-opus-4-5"
HAIKU = "claude-haiku-4-5-20251001"

CLAUDE_CODE = ("claude-code", "2.1.318")

RECIPES = "/work/RecipeBox/CLAUDE.md"
LARDER = "/work/Larder/CLAUDE.md"
"""The instruction file of Pilot's store, by its invented name."""

STORE = "/work/Larder"
STORE_REPOSITORY = "Larder"
STORE_ENVIRONMENT = "pilot-larder-4b7d21"


def _opening(system: int, tools: int, own: tuple[str, int]) -> tuple[Carried, ...]:
    """What a Launch's first Call carries: its system prompt, its tools, the
    managed instruction file and the checkout's own."""
    return (
        Carried("system_prompt", system),
        Carried("tool_schemas", tools),
        Carried("instruction_file", 2_350, MANAGED),
        Carried("instruction_file", own[1], own[0]),
    )


JARS = SubAgent(
    name="jars",
    type="Explore",
    steps=(
        Call(
            at=44,
            sent=33,
            model=HAIKU,
            tokens=Tokens(input=1_900, cache_write_5m=5_800, output=90),
            carried=_opening(3_900, 11_800, (RECIPES, 3_750)),
            tools=(ToolUse("Grep", "jars", took=1, characters=1_420),),
        ),
        Call(
            at=56,
            sent=46,
            model=HAIKU,
            tokens=Tokens(input=240, cache_read=5_800, output=130),
            tools=(ToolUse("Read", "pantry/jars.md", took=1, characters=980),),
        ),
        Call(
            at=66,
            sent=57,
            model=HAIKU,
            tokens=Tokens(input=310, cache_read=5_800, output=150),
        ),
    ),
)

SPICES = Session(
    name="spices",
    directory="/work/RecipeBox",
    environment="pilot-recipebox-7a2e90",
    repository="RecipeBox",
    ran=Ran(
        project="recipe-box",
        kind="work",
        title="Sort the spices",
        turns=(
            Turn(
                message="Sort the spices by how often the recipes use them.",
                at=0,
                ended=190,
            ),
            Turn(
                message="Carry on: label the jars that are left.",
                at=3_990,
                ended=4_040,
                cause="continuation",
            ),
        ),
    ),
    unit="Sort the spices",
    launches=(
        Launch(
            versions=(CLAUDE_CODE,),
            prompts=(
                Prompt(
                    at=4,
                    source="sdk",
                    characters=380,
                    steps=(
                        Call(
                            at=18,
                            sent=5,
                            effort="high",
                            tokens=Tokens(
                                input=1_320, cache_write_1h=20_600, output=280
                            ),
                            carried=(
                                *_opening(9_100, 45_200, (RECIPES, 3_750)),
                                Carried("reminder", 96, "date"),
                            ),
                            tools=(
                                ToolUse(
                                    "Read", "spices/list.md", took=1, characters=1_860
                                ),
                            ),
                        ),
                        Call(
                            at=31,
                            sent=20,
                            effort="high",
                            tokens=Tokens(
                                input=10,
                                cache_write_1h=1_900,
                                cache_read=20_600,
                                output=460,
                            ),
                            tools=(
                                ToolUse(
                                    "Agent",
                                    "Find where the jars are counted",
                                    took=40,
                                    characters=1_500,
                                    spawns="jars",
                                ),
                            ),
                        ),
                        Call(
                            at=84,
                            sent=72,
                            effort="high",
                            tokens=Tokens(
                                input=12,
                                cache_write_1h=2_100,
                                cache_read=22_500,
                                output=520,
                            ),
                            tools=(
                                ToolUse(
                                    "Edit", "spices/list.md", took=1, characters=90
                                ),
                            ),
                        ),
                        Compaction(
                            at=110,
                            trigger="auto",
                            before=158_000,
                            after=22_400,
                            took_ms=31_000,
                        ),
                        Call(
                            at=160,
                            sent=142,
                            effort="high",
                            miss="compaction",
                            tokens=Tokens(
                                input=2_900, cache_write_1h=22_400, output=430
                            ),
                            carried=(Carried("compact_summary", 8_100),),
                        ),
                        Call(
                            at=178,
                            sent=162,
                            effort="high",
                            tokens=Tokens(
                                input=9,
                                cache_write_1h=650,
                                cache_read=22_400,
                                output=240,
                            ),
                        ),
                    ),
                    hooks=(HookRun("tidy_up.sh", took_ms=140),),
                ),
            ),
        ),
        Launch(
            versions=(CLAUDE_CODE,),
            prompts=(
                Prompt(
                    at=3_994,
                    source="sdk",
                    characters=210,
                    steps=(
                        Call(
                            at=4_008,
                            sent=3_995,
                            effort="high",
                            miss="ttl",
                            tokens=Tokens(
                                input=1_150, cache_write_1h=23_100, output=300
                            ),
                            carried=_opening(9_100, 45_200, (RECIPES, 3_750)),
                        ),
                        Call(
                            at=4_024,
                            sent=4_010,
                            effort="high",
                            tokens=Tokens(
                                input=8,
                                cache_write_1h=520,
                                cache_read=23_100,
                                output=260,
                            ),
                            tools=(
                                ToolUse(
                                    "Edit", "pantry/jars.md", took=1, characters=80
                                ),
                            ),
                        ),
                    ),
                    hooks=(HookRun("tidy_up.sh", took_ms=120),),
                ),
            ),
        ),
    ),
    sub_agents=(JARS,),
)

PANTRY_CHAT = Session(
    name="pantry-chat",
    directory=STORE,
    environment=STORE_ENVIRONMENT,
    repository=STORE_REPOSITORY,
    ran=Ran(
        project="recipe-box",
        kind="chat",
        chat="project",
        turns=(
            Turn(
                message="Which spices run out first?",
                at=600,
                ended=650,
                cause="person",
                author="ada",
            ),
            Turn(
                message="And which do we buy most?",
                at=1_900,
                ended=1_920,
                cause="person",
                author="ben",
            ),
        ),
    ),
    launches=(
        Launch(
            versions=(CLAUDE_CODE,),
            prompts=(
                Prompt(
                    at=603,
                    source="sdk",
                    characters=120,
                    steps=(
                        Call(
                            at=616,
                            sent=604,
                            tokens=Tokens(
                                input=1_480, cache_write_1h=16_900, output=340
                            ),
                            carried=_opening(9_100, 38_400, (LARDER, 4_200)),
                            tools=(
                                ToolUse(
                                    "Read",
                                    "projects/recipe-box/notes.md",
                                    took=1,
                                    characters=2_400,
                                ),
                            ),
                        ),
                        Call(
                            at=644,
                            sent=618,
                            tokens=Tokens(
                                input=9,
                                cache_write_1h=760,
                                cache_read=16_900,
                                output=410,
                            ),
                        ),
                    ),
                ),
            ),
        ),
        Launch(
            versions=(CLAUDE_CODE,),
            prompts=(
                Prompt(
                    at=1_903,
                    source="sdk",
                    characters=96,
                    steps=(
                        Call(
                            at=1_915,
                            sent=1_904,
                            tokens=Tokens(
                                input=1_420,
                                cache_write_1h=1_300,
                                cache_read=17_660,
                                output=300,
                            ),
                            carried=_opening(9_100, 38_400, (LARDER, 4_200)),
                        ),
                    ),
                ),
            ),
        ),
    ),
)

RIDE_NOTES = Session(
    name="ride-notes",
    directory=STORE,
    environment=STORE_ENVIRONMENT,
    repository=STORE_REPOSITORY,
    ran=Ran(
        project="bike-log",
        kind="job",
        title="Tidy the ride notes",
        trigger="item_done",
        turns=(
            Turn(
                message="Tidy the ride notes the last ride left.",
                at=2_400,
                ended=2_490,
            ),
        ),
    ),
    unit="Tidy the ride notes",
    launches=(
        Launch(
            versions=(CLAUDE_CODE,),
            prompts=(
                Prompt(
                    at=2_403,
                    source="sdk",
                    characters=260,
                    steps=(
                        Call(
                            at=2_430,
                            sent=2_404,
                            tokens=Tokens(
                                input=2_600, cache_write_1h=96_800, output=2_900
                            ),
                            carried=_opening(9_100, 38_400, (LARDER, 4_200)),
                            tools=(
                                ToolUse(
                                    "Read",
                                    "projects/bike-log/rides.md",
                                    took=2,
                                    characters=48_000,
                                ),
                            ),
                        ),
                        Call(
                            at=2_452,
                            sent=2_434,
                            tokens=Tokens(
                                input=11,
                                cache_write_1h=900,
                                cache_read=96_800,
                                output=380,
                            ),
                            tools=(
                                ToolUse(
                                    "Edit",
                                    "projects/bike-log/rides.md",
                                    took=1,
                                    characters=110,
                                ),
                            ),
                        ),
                        Call(
                            at=2_480,
                            sent=2_456,
                            tokens=Tokens(
                                input=8,
                                cache_write_1h=400,
                                cache_read=97_700,
                                output=210,
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ),
)

TALLY = Scenario(
    name="tally",
    people=("ada", "ben"),
    projects=("recipe-box", "bike-log"),
    kinds=("errand",),
    units=(
        Unit("errand", "Sort the spices", project="recipe-box"),
        Unit("errand", "Tidy the ride notes", project="bike-log"),
    ),
    sessions=(SPICES, PANTRY_CHAT, RIDE_NOTES),
)
