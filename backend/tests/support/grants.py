"""The store's grants file on the fake controller: an invented one, in the shape
a work item's brief reads its grants text from."""

from app.services.fake_controller import FakeController
from app.services.session_scope import GRANTS_FILE
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID

GRANTS_ON = (
    "Yours without asking: reads, commits, a push to this work's topic branch,\n"
    "`pilot/<project>/<task>`, and a push that deploys.\n"
    "Never on your own say: emptying the pantry."
)
GRANTS_OFF = (
    "Yours without asking: reads, commits, a push to this work's topic branch,\n"
    "`pilot/<project>/<task>`.\n"
    "Asked first: a push that deploys. Never on your own say: emptying the pantry."
)


def grants_file(on: str | None = GRANTS_ON, off: str | None = GRANTS_OFF) -> str:
    """The file, its worker's section holding the block of each position
    given."""
    blocks = "".join(
        f"\n{label}\n\n```text\n{text}\n```\n"
        for label, text in (("Auto pilot on:", on), ("Auto pilot off:", off))
        if text is not None
    )
    return (
        "# The grants\n\nWhat goes ahead unasked.\n\n"
        "## The table\n\n- reads\n\n"
        "## In a worker's brief\n\nThe text the switch selects.\n"
        f"{blocks}"
        "\n## After it\n\nNothing a brief takes.\n"
    )


def granted(text: str, branch: str) -> str:
    """The block `text` as a brief carries it, the topic branch `branch`
    written in."""
    return text.replace("pilot/<project>/<task>", branch)


def put_grants(fake_controller: FakeController, text: str | None = None) -> None:
    """The store's checkout holds `text` as its grants file, the whole file
    by default."""
    fake_controller.put_file(
        STORE_ENVIRONMENT_ID,
        GRANTS_FILE,
        (grants_file() if text is None else text).encode(),
    )


def store_grants(fake_controller: FakeController) -> None:
    """The store's environment on the fake controller, its checkout holding
    the grants file."""
    fake_controller.add_environment(STORE_ENVIRONMENT_ID, name="PilotProjects")
    put_grants(fake_controller)
