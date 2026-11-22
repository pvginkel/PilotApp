"""A refusal of a view's state (F154.2): every fault at once, the nearest
names by edit distance, and a correct example of each kind of part refused,
in one text for the screen and a tool; and of a load of the workflow's views
and ratios, each fault named with its entry (F155.3)."""

from app.dashboard.refusal import (
    ENTRY,
    Fault,
    distance,
    in_entry,
    listed,
    nearest,
    refusal,
    refused,
    refused_load,
)
from app.exceptions import StateRefusedException


class TestDistance:
    def test_an_edit_is_an_insertion_a_deletion_or_a_change(self) -> None:
        assert distance("cost", "cost") == 0
        assert distance("cost", "costs") == 1
        assert distance("cost", "cst") == 1
        assert distance("cost", "cast") == 1
        assert distance("", "abc") == 3

    def test_a_swap_of_two_neighbours_is_one(self) -> None:
        assert distance("medain", "median") == 1
        assert distance("ab", "ba") == 1


class TestNearest:
    def test_the_names_a_third_of_its_length_away_nearest_first(self) -> None:
        assert nearest("medain", ["sum", "median", "mean", "max"]) == (
            "median",
            "mean",
        )
        assert nearest("modle", ["hod", "miss", "model"]) == ("model",)

    def test_one_edit_at_least_and_three_at_most(self) -> None:
        assert nearest("gte", ["ge", "gt", "lt"]) == ("ge", "gt")
        assert nearest("work_typesxyz", ["work_type"]) == ()
        assert nearest("work_typesxy", ["work_type"]) == ("work_type",)

    def test_a_name_no_nearer_than_its_length_is_none(self) -> None:
        assert nearest("x", ["t", "by"]) == ()

    def test_at_most_three_ties_in_their_own_order(self) -> None:
        assert nearest("l3", ["l2", "l4", "l8", "qw", "d2"]) == ("l2", "l4", "l8")

    def test_case_does_not_count(self) -> None:
        assert nearest("Project", ["project", "psession"]) == ("project",)

    def test_a_name_too_far_is_none(self) -> None:
        assert nearest("phases", ["project", "psession"]) == ()


class TestListed:
    def test_it_lists_one_two_and_more(self) -> None:
        assert listed(["a"]) == "a"
        assert listed(["a", "b"]) == "a and b"
        assert listed(["a", "b", "c"], "or") == "a, b or c"


class TestRefusal:
    def test_it_names_every_fault_and_ends_on_an_example_of_each_kind(
        self,
    ) -> None:
        faults = [
            Fault(
                "m=cost.medain",
                "m",
                '"medain" is no aggregate',
                ("median", "mean"),
                "cost takes sum, median, mean, max and p90",
            ),
            Fault("by=phases", "by", '"phases" is no dimension'),
        ]

        assert refusal(faults) == (
            "Cannot read the view because its state has 2 faults.\n"
            '- m=cost.medain: "medain" is no aggregate. Did you mean "median" or '
            '"mean"? cost takes sum, median, mean, max and p90.\n'
            '- by=phases: "phases" is no dimension.\n'
            "A By reads by=<dimension>, as in by=project.\n"
            "A measure reads m=<figure>.<aggregate>[.<grain>][(<filter>;…)], "
            "m=r:<ratio> or m=r:<name>:<measure>/<measure>, as in "
            "m=cost.median.conversation or m=cost.sum(miss=1)."
        )

    def test_one_fault(self) -> None:
        text = refusal([Fault("rel=2", "rel", '"2" is no switch')])

        assert text.splitlines()[0] == (
            "Cannot read the view because its state has 1 fault."
        )
        assert text.splitlines()[-1] == "Relative reads rel=1, as in rel=1."

    def test_its_exception_carries_the_text_and_the_faults(self) -> None:
        faults = [Fault("rel=2", "rel", '"2" is no switch')]

        exception = refused(faults)

        assert isinstance(exception, StateRefusedException)
        assert exception.message == refusal(faults)
        assert exception.faults == tuple(faults)
        assert exception.error_code == "STATE_REFUSED"


class TestRefusedLoad:
    def test_it_names_every_fault_with_its_entry_and_ends_on_an_example_of_each_kind(
        self,
    ) -> None:
        faults = [
            in_entry(
                'view "errands"',
                Fault("by=phases", "by", '"phases" is no dimension'),
            ),
            Fault(
                'view "legs", name "Projects"',
                ENTRY,
                "one of Pilot's own system views has the name",
            ),
        ]

        refused = refused_load(faults)

        assert refused.message == (
            "Cannot load the views and ratios because their entries have 2 "
            "faults.\n"
            '- view "errands", by=phases: "phases" is no dimension.\n'
            '- view "legs", name "Projects": one of Pilot\'s own system views has '
            "the name.\n"
            "A By reads by=<dimension>, as in by=project."
        )
        assert refused.faults == tuple(faults)
        assert refused.error_code == "STATE_REFUSED"

    def test_a_fault_of_an_entry_alone_ends_on_no_example(self) -> None:
        refused = refused_load(
            [Fault('ratio "person_x", key', ENTRY, "a person's key")]
        )

        assert refused.message == (
            "Cannot load the views and ratios because their entries have 1 "
            "fault.\n"
            '- ratio "person_x", key: a person\'s key.'
        )

    def test_in_entry_keeps_the_fault_but_its_part(self) -> None:
        fault = Fault(
            "m=cost.medain", "m", '"medain" is no aggregate', ("median",), "sum"
        )

        assert in_entry('ratio "per_serving"', fault) == Fault(
            'ratio "per_serving", m=cost.medain',
            "m",
            '"medain" is no aggregate',
            ("median",),
            "sum",
        )
