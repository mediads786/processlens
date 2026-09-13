import unittest
import xml.etree.ElementTree as ET

import app
from analyzer import _graph_from_ai, _local_generate_to_be
from models import ProcessAnalysis


def approval_graph():
    rows = [
        (1, "Submit request", "activity", [(2, "")]),
        (2, "Complete?", "decision", [(4, "Yes"), (3, "No")]),
        (3, "Return for correction", "activity", [(1, "Resubmit")]),
        (4, "Approved?", "decision", [(5, "Yes"), (6, "No")]),
        (5, "Send approved order", "activity", []),
        (6, "Notify rejection", "activity", []),
    ]
    return [dict(node_id=i, name=name, type=kind,
                 transitions=[dict(target_id=target, label=label) for target, label in edges])
            for i, name, kind, edges in rows]


class WorkflowBranchTests(unittest.TestCase):
    def setUp(self):
        self.steps = _graph_from_ai(approval_graph())

    def test_terminal_outcomes_do_not_fall_through(self):
        by_id = {s.id: s for s in self.steps}
        self.assertEqual(by_id[6].next_step_ids, [8])
        self.assertEqual(by_id[7].next_step_ids, [8])
        self.assertEqual(by_id[4].next_step_ids, [2])
        self.assertEqual(by_id[4].next_step_labels, {2: "Resubmit"})
        self.assertEqual(by_id[5].next_step_labels, {6: "Yes", 7: "No"})

    def test_invalid_edges_are_not_replaced_with_sequential_edges(self):
        for transitions in (None, [{"target_id": 99}], [{"target_id": "bad"}]):
            rows = approval_graph()
            rows[0]["transitions"] = transitions
            with self.subTest(transitions=transitions), self.assertRaises(ValueError):
                _graph_from_ai(rows)

    def test_review_and_local_tobe_preserve_connections(self):
        analysis = ProcessAnalysis("test", "Purchase", "Example", "", "Test", self.steps)
        rows = [s for s in self.steps if s.type not in {"start", "end"}]
        form = {"count": [str(len(rows))]}
        for i, step in enumerate(rows):
            for field in ("name", "type", "actor", "system"):
                form[f"step_{i}_{field}"] = [getattr(step, field)]
            form[f"step_{i}_orig_id"] = [str(step.id)]
        expected = [(s.id, s.next_step_ids, s.next_step_labels) for s in self.steps]
        app.core.rebuild(form, analysis)
        self.assertEqual([(s.id, s.next_step_ids, s.next_step_labels) for s in analysis.steps], expected)
        tobe, _ = _local_generate_to_be(analysis)
        self.assertEqual([(s.id, s.next_step_ids, s.next_step_labels) for s in tobe], expected)

    def test_loop_diagram_has_distinct_levels_and_return_label(self):
        svg = ET.fromstring(app.core.workflow_svg(self.steps)).find("svg")
        self.assertIsNotNone(svg)
        self.assertIn("Resubmit", "".join(svg.itertext()))
        text_nodes = [node for node in svg.findall("text") if node.text in ("Submit request", "Return for correction")]
        self.assertEqual(len(text_nodes), 2)
        self.assertNotEqual(text_nodes[0].attrib["y"], text_nodes[1].attrib["y"])


if __name__ == "__main__":
    unittest.main()
