"""The one invented scenario, in the dev seed's own world: the people `ada`
and `ben`, the projects `recipe-box` and `bike-log`.

Pilot is sent to halve the stew in the recipe box, an errand's first leg. Its
session reads the recipe, has a sub-agent count the servings while it loads
the pantry's scaling skill, meets a failing command and an API error its
request is sent again after, halves the recipe, writes the shopping list and
commits both, and carries on past a compaction, missing the
cache, a Stop hook tidying up at its end; two of its tools' outputs are too
large and are saved to disk. The sub-agent asks for Opus once and Haiku
answers in its place, while a hook keeps it from the pantry's token and a
permission rule from the pantry's stock, and its last answer runs out of
tokens. Ada, by hand, looks at the bike log's gear table, which loads the
rides' own instruction file, one of her two Stop hooks failing, stops the
command her second question started, takes that question back and turns
down the edit Claude then asks for, and comes back after the cache has
lapsed, each time missing it: one of the first rides' conversations, a group
of work done before Pilot ran any.

The model names are the public ones. Everything else is invented.
"""

from pilot_scenario.script import (
    Call,
    Carried,
    Committed,
    Compaction,
    Group,
    HookRun,
    Launch,
    Prompt,
    Retry,
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

CLAUDE_CODE = ("claude-code", "2.1.317")
PANTRY = ("plugin:pantry", "0.3.1")

COUNTING = SubAgent(
    name="counting",
    type="Explore",
    steps=(
        Call(
            at=46,
            sent=34,
            model=HAIKU,
            tokens=Tokens(input=2_140, cache_write_5m=6_020, output=96),
            carried=(
                Carried("system_prompt", 3_900),
                Carried("tool_schemas", 11_800),
                Carried("instruction_file", 2_350, MANAGED),
                Carried("instruction_file", 3_750, "/work/RecipeBox/CLAUDE.md"),
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
            sent=49,
            model=HAIKU,
            requested=OPUS,
            tokens=Tokens(input=310, cache_read=6_020, output=72),
            tools=(
                ToolUse("Read", "recipes/stew.md", took=1, characters=2_210),
                ToolUse(
                    "Bash",
                    "cat ~/.pantry/token",
                    took=1,
                    characters=260,
                    failed=True,
                    denied="hook",
                ),
                ToolUse(
                    "Bash",
                    "curl pantry.local/stock",
                    took=1,
                    characters=120,
                    failed=True,
                    denied="rule",
                ),
            ),
        ),
        Call(
            at=74,
            sent=60,
            model=HAIKU,
            stop="max_tokens",
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
                            sent=5,
                            effort="high",
                            thinking=188,
                            tokens=Tokens(
                                input=1_204, cache_write_1h=21_400, output=310
                            ),
                            carried=(
                                Carried("system_prompt", 9_100),
                                Carried("tool_schemas", 45_200),
                                Carried("instruction_file", 2_350, MANAGED),
                                Carried(
                                    "instruction_file",
                                    3_750,
                                    "/work/RecipeBox/CLAUDE.md",
                                ),
                                Carried("reminder", 2_870, "skill_listing"),
                                Carried("reminder", 96, "date"),
                            ),
                            tools=(
                                ToolUse(
                                    "Read", "recipes/stew.md", took=1, characters=2_210
                                ),
                            ),
                        ),
                        Call(
                            at=33,
                            sent=21,
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
                                ToolUse(
                                    "Skill", "pantry:scaling", took=1, characters=31
                                ),
                            ),
                        ),
                        Call(
                            at=92,
                            sent=79,
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
                        ),
                        Call(
                            at=118,
                            sent=102,
                            retried=(Retry(sent=96, failed=101, status=529),),
                            effort="high",
                            carried=(
                                Carried("reminder", 186, "bash_output_audience_note"),
                            ),
                            tokens=Tokens(
                                input=14,
                                cache_write_1h=1_150,
                                cache_read=26_180,
                                output=655,
                            ),
                            tools=(
                                ToolUse(
                                    "Edit",
                                    "recipes/stew.md",
                                    took=1,
                                    characters=96,
                                    added=4,
                                    removed=4,
                                ),
                                ToolUse(
                                    "Write",
                                    "/work/RecipeBox/recipes/shopping.md",
                                    took=2,
                                    characters=88,
                                    added=6,
                                    created=True,
                                ),
                                ToolUse(
                                    "Bash",
                                    'git add recipes && git commit -m "Halve the stew"',
                                    took=3,
                                    characters=120,
                                    commits=(Committed("Halve the stew", "4be1d2c"),),
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
                            sent=151,
                            effort="high",
                            miss="compaction",
                            tokens=Tokens(
                                input=4_630, cache_write_1h=21_300, output=480
                            ),
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
                            sent=208,
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
                            sent=301,
                            tokens=Tokens(input=940, cache_write_5m=18_700, output=205),
                            carried=(
                                Carried("system_prompt", 9_100),
                                Carried("tool_schemas", 45_200),
                                Carried("instruction_file", 2_350, MANAGED),
                                Carried(
                                    "instruction_file", 1_480, "/work/BikeLog/CLAUDE.md"
                                ),
                                Carried("reminder", 412, "environment"),
                            ),
                            tools=(
                                ToolUse(
                                    "Read", "rides/gears.md", took=1, characters=1_640
                                ),
                            ),
                        ),
                        Call(
                            at=326,
                            sent=313,
                            name="the ratios",
                            carried=(
                                Carried(
                                    "instruction_file",
                                    620,
                                    "/work/BikeLog/rides/CLAUDE.md",
                                ),
                            ),
                            tokens=Tokens(
                                input=8,
                                cache_write_5m=1_700,
                                cache_read=18_700,
                                output=330,
                            ),
                        ),
                    ),
                    hooks=(
                        HookRun("log_ride.sh", took_ms=40),
                        HookRun("sync_notes.sh", took_ms=1_210, failed=True),
                    ),
                ),
                Prompt(
                    at=350,
                    source="typed",
                    characters=54,
                    steps=(
                        Call(
                            at=362,
                            sent=351,
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
                            sent=391,
                            back_to="the ratios",
                            miss="rewind",
                            tokens=Tokens(
                                input=9,
                                cache_write_5m=20_400,
                                cache_read=1_920,
                                output=298,
                            ),
                            tools=(
                                ToolUse(
                                    "Edit",
                                    "rides/gears.md",
                                    took=6,
                                    characters=160,
                                    failed=True,
                                    denied="person",
                                ),
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
                            sent=961,
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
