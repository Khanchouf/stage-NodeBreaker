from pddl.generator import build_problem_text

from .helpers import double_busbar_problem


def test_enriched_pddl_contains_structure_and_detailed_goal():
    text = build_problem_text(double_busbar_problem())
    assert "(endpoint-1 SA_B1 B1)" in text
    assert "(busbar-at BBS1 B1)" in text
    assert "(source-equipment LINE)" in text
    assert "(not (closed SA_B1))" in text
    assert "(closed SA_B2)" in text
    assert "reachable" not in text.lower()
