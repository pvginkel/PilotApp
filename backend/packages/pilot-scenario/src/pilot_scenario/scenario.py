"""The one invented scenario, in the dev seed's own world: the people `ada`
and `ben`, the projects `recipe-box` and `bike-log`.

Pilot is sent to halve the stew in the recipe box, an errand's first leg. Its
session reads the recipe, has a sub-agent count the servings, meets an API
error and a failing command, and carries on past a compaction; two of its
tools' outputs are too large and are saved to disk. Ada, by hand, looks at
the bike log's gear table, stops the command her second question started,
takes that question back and comes back after the cache has lapsed: one of
the first rides' conversations, a group of work done before Pilot ran any.

The model names are the public ones. Everything else is invented.
"""

from pilot_scenario.script import (
    Call,
    Carried,
    Compaction,
    Group,
    HookRun,
    Launch,
    Occurrence,
    Prompt,
    Scenario,
    Session,
    SubAgent,
    Tokens,
    ToolUse,
    Turn,
    Unit,
)

OPUS = "claude-opus-4-5"
HAIKU = "claude-haiku-4-5-20251001"

CLAUDE_CODE = ("claude-code", "2.1.317")
PANTRY = ("plugin:pantry", "0.3.1")

COUNTING = SubAgent(
    name="counting",
    type="Explore",
    steps=(
        Call(
            at=46,
            model=HAIKU,
            tokens=Tokens(input=2_140, cache_write_5m=6_020, output=96),
            carried=(
                Carried("system_prompt", 3_900),
                Carried("tool_schemas", 11_800),
            ),
            tools=(
                ToolUse(
                    "Bash",
                    "grep -rn servings recipes",
                    took=2,
                    characters=2_164,
                    saved=33_180,
                ),
            ),
        ),
        Call(
            at=58,
            model=HAIKU,
            tokens=Tokens(input=310, cache_read=6_020, output=72),
            tools=(ToolUse("Read", "recipes/stew.md", took=1, characters=2_210),),
        ),
        Call(
            at=74,
            model=HAIKU,
            tokens=Tokens(input=780, cache_read=6_020, output=268),
        ),
    ),
)

HALVING = Session(
    name="halving",
    directory="/work/RecipeBox",
    environment="ben-recipebox-51f0c2",
    repository="RecipeBox",
    turn=Turn(
        project="recipe-box",
        message="Halve the stew: it serves eight, and the pot holds four.",
        at=0,
        ended=224,
    ),
    unit="Halve the stew",
    launches=(
        Launch(
            versions=(CLAUDE_CODE, PANTRY),
            prompts=(
                Prompt(
                    at=4,
                    source="sdk",
                    characters=412,
                    steps=(
                        Call(
                            at=19,
                            effort="high",
                            thinking=188,
                            tokens=Tokens(
                                input=1_204, cache_write_1h=21_400, output=310
                            ),
                            carried=(
                                Carried("system_prompt", 9_100),
                                Carried("tool_schemas", 45_200),
                                Carried("instruction_file", 6_100, "CLAUDE.md"),
                            ),
                            tools=(
                                ToolUse(
                                    "Read", "recipes/stew.md", took=1, characters=2_210
                                ),
                            ),
                        ),
                        Call(
                            at=33,
                            effort="high",
                            tokens=Tokens(
                                input=12,
                                cache_write_1h=2_300,
                                cache_read=21_400,
                                output=540,
                            ),
                            tools=(
                                ToolUse(
                                    "Agent",
                                    "Find where the servings are counted",
                                    took=45,
                                    characters=1_900,
                                    spawns="counting",
                                ),
                            ),
                        ),
                        Call(
                            at=92,
                            effort="high",
                            skill="pantry:scaling",
                            plugin="pantry",
                            tokens=Tokens(
                                input=9,
                                cache_write_1h=2_480,
                                cache_read=23_700,
                                output=402,
                            ),
                            carried=(Carried("skill_body", 4_300, "pantry:scaling"),),
                            tools=(
                                ToolUse(
                                    "mcp__pantry__list_recipes",
                                    "stew",
                                    took=1,
                                    characters=1_240,
                                    server="pantry",
                                    saved=48_300,
                                ),
                                ToolUse(
                                    "Bash",
                                    "python scale.py stew 0.5",
                                    took=3,
                                    characters=420,
                                    failed=True,
                                    exit_code=2,
                                ),
                            ),
                            occurred=(
                                Occurrence(
                                    at=101,
                                    kind="api_error",
                                    is_error=True,
                                    detail="529",
                                ),
                            ),
                        ),
                        Call(
                            at=118,
                            effort="high",
                            tokens=Tokens(
                                input=14,
                                cache_write_1h=1_150,
                                cache_read=26_180,
                                output=655,
                            ),
                            tools=(
                                ToolUse(
                                    "Edit", "recipes/stew.md", took=1, characters=96
                                ),
                            ),
                        ),
                        Compaction(
                            at=150,
                            trigger="auto",
                            before=160_400,
                            after=21_300,
                            took_ms=38_000,
                        ),
                        Call(
                            at=204,
                            effort="high",
                            miss="compaction",
                            tokens=Tokens(input=30, cache_write_1h=21_300, output=480),
                            carried=(Carried("compact_summary", 8_400),),
                            tools=(
                                ToolUse(
                                    "Bash",
                                    "python scale.py stew 0.5",
                                    took=3,
                                    characters=388,
                                ),
                            ),
                        ),
                        Call(
                            at=221,
                            effort="high",
                            tokens=Tokens(
                                input=11,
                                cache_write_1h=910,
                                cache_read=21_300,
                                output=214,
                            ),
                        ),
                    ),
                    hooks=(HookRun("tidy_up.sh", took_ms=151),),
                ),
            ),
        ),
    ),
    sub_agents=(COUNTING,),
)

FIRST_RIDES = Group(
    key="bike-log-first-rides",
    name="Bike log: the first rides",
    summary="The gear tables and ride notes Ada kept by hand, before Pilot kept the log.",
)

GEARS = Session(
    name="gears",
    directory="/work/BikeLog",
    environment="ada-bikelog-3c9e1f",
    repository="BikeLog",
    person="ada",
    group=FIRST_RIDES,
    launches=(
        Launch(
            versions=(CLAUDE_CODE,),
            prompts=(
                Prompt(
                    at=300,
                    source="typed",
                    characters=188,
                    steps=(
                        Call(
                            at=311,
                            tokens=Tokens(input=940, cache_write_5m=18_700, output=205),
                            carried=(
                                Carried("system_prompt", 9_100),
                                Carried("tool_schemas", 45_200),
                            ),
                            tools=(
                                ToolUse(
                                    "Read", "rides/gears.md", took=1, characters=1_640
                                ),
                            ),
                        ),
                        Call(
                            at=326,
                            name="the ratios",
                            tokens=Tokens(
                                input=8,
                                cache_write_5m=1_700,
                                cache_read=18_700,
                                output=330,
                            ),
                        ),
                    ),
                ),
                Prompt(
                    at=350,
                    source="typed",
                    characters=54,
                    steps=(
                        Call(
                            at=362,
                            tokens=Tokens(
                                input=10,
                                cache_write_5m=380,
                                cache_read=20_400,
                                output=512,
                            ),
                            tools=(
                                ToolUse(
                                    "Bash",
                                    "python ratios.py --every-gear",
                                    took=9,
                                    characters=148,
                                    interrupted=True,
                                ),
                            ),
                        ),
                    ),
                ),
                Prompt(
                    at=390,
                    source="typed",
                    characters=71,
                    steps=(
                        Call(
                            at=401,
                            back_to="the ratios",
                            miss="rewind",
                            tokens=Tokens(
                                input=9,
                                cache_write_5m=1_920,
                                cache_read=20_400,
                                output=298,
                            ),
                        ),
                    ),
                ),
                Prompt(
                    at=960,
                    source="typed",
                    characters=37,
                    steps=(
                        Call(
                            at=972,
                            miss="ttl",
                            tokens=Tokens(input=12, cache_write_5m=20_660, output=140),
                        ),
                    ),
                ),
            ),
        ),
    ),
)

SCENARIO = Scenario(
    name="supper",
    people=("ada", "ben"),
    projects=("recipe-box", "bike-log"),
    kinds=("errand", "leg"),
    units=(
        Unit("errand", "Scale the recipes", project="recipe-box"),
        Unit("leg", "Halve the stew", within="Scale the recipes"),
        Unit("leg", "Halve the dumplings", within="Scale the recipes"),
    ),
    sessions=(HALVING, GEARS),
)
