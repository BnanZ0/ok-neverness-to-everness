import unittest

from src.combat.AbyssLogAnalyzer import format_trace_report, parse_abyss_traces


class TestAbyssLogAnalyzer(unittest.TestCase):
    def test_parses_baicang_route_until_return_switch(self):
        traces = parse_abyss_traces(
            [
                "2026-07-16 10:00:00,000 INFO planner:strict route locked: "
                "Baicang abyss opener / Sakiri groups enemies",
                "2026-07-16 10:00:00,100 INFO planner:planner action Sakiri -> Sakiri_skill, "
                "tags [], reason test",
                "2026-07-16 10:00:01,000 INFO planner:strict route skips optional step: "
                "Baicang abyss opener / Hania Q",
                "2026-07-16 10:00:02,000 INFO planner:strict route fulfilled: Baicang abyss opener",
                "2026-07-16 10:00:02,100 INFO planner:planner switch Daphneel -> Baicang, "
                "priority 1, reason switch request: return Baicang",
            ]
        )

        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0].status, "fulfilled")
        self.assertEqual(traces[0].action_sequence(), ["Sakiri:Sakiri_skill"])
        self.assertEqual(sum(event.kind == "skip" for event in traces[0].events), 1)
        self.assertEqual(traces[0].diagnosis(), [])

    def test_parses_chiz_reactions_and_next_cycle(self):
        traces = parse_abyss_traces(
            [
                "2026-07-16 10:00:00,000 INFO planner:strict route locked: "
                "Chiz Yingxu abyss cycle / Iloy reaction",
                "2026-07-16 10:00:01,000 INFO planner:strict route completed entry reaction "
                "Chiz -> Iloy: Chiz Yingxu abyss cycle / Creation",
                "2026-07-16 10:00:02,000 INFO planner:strict route completed entry reaction "
                "Zero -> Yi: Chiz Yingxu abyss cycle / Delay",
                "2026-07-16 10:00:03,000 INFO planner:strict route fulfilled: "
                "Chiz Yingxu abyss cycle",
                "2026-07-16 10:00:03,100 INFO planner:strict route locked: "
                "Chiz Yingxu abyss cycle / Zero Q",
            ]
        )

        self.assertEqual(len(traces), 2)
        self.assertEqual(traces[0].status, "fulfilled")
        self.assertEqual(traces[0].reaction_sequence(), ["Chiz->Iloy", "Zero->Yi"])
        self.assertEqual(traces[0].diagnosis(), [])
        self.assertEqual(traces[1].route, "Chiz Yingxu abyss cycle")
        self.assertIn("route status is pending", traces[1].diagnosis())
        self.assertIn("missing reaction Chiz->Iloy", traces[1].diagnosis())

    def test_reports_zero_field_wait_and_repeated_unavailable_actions(self):
        lines = [
            "2026-07-16 10:00:00,000 INFO planner:strict route locked: "
            "Chiz Yingxu abyss opener / Zero setup",
            "2026-07-16 10:00:00,100 INFO planner:strict route completed entry reaction "
            "Chiz -> Iloy: Chiz Yingxu abyss opener / Creation",
            "2026-07-16 10:00:00,200 INFO planner:strict route completed entry reaction "
            "Zero -> Yi: Chiz Yingxu abyss opener / Delay",
        ]
        lines.extend(
            "2026-07-16 10:00:01,000 INFO planner:planner action "
            "Zero -> Zero_ultimate, tags [], reason unavailable"
            for _ in range(10)
        )
        lines.extend(
            "2026-07-16 10:00:02,000 INFO planner:planner keep Zero, priority 1, "
            "reason strict route waiting entry reaction: cycle / Yi"
            for _ in range(5)
        )
        lines.append(
            "2026-07-16 10:00:02,500 INFO SoundCombatContext:"
            "Sound action discarded after timeout: dodge"
        )
        lines.append(
            "2026-07-16 10:00:03,000 INFO planner:strict route fulfilled: Chiz Yingxu abyss opener"
        )

        diagnosis = parse_abyss_traces(lines)[0].diagnosis()

        self.assertIn("Zero:Zero_ultimate retried 10 times", diagnosis)
        self.assertIn("Zero held field for 5 strict-route wait ticks", diagnosis)
        self.assertIn("1 sound actions discarded after timeout", diagnosis)

    def test_expired_route_is_reported(self):
        traces = parse_abyss_traces(
            [
                "2026-07-16 10:00:00,000 INFO planner:strict route locked: "
                "Chiz Yingxu abyss cycle / Zero E",
                "2026-07-16 10:00:35,000 WARNING planner:strict route deadline expired, "
                "route unlocked: Chiz Yingxu abyss cycle / Zero E",
            ]
        )

        self.assertEqual(traces[0].status, "expired")
        self.assertIn("status: expired", format_trace_report(traces))
        self.assertIn("route status is expired", traces[0].diagnosis())

    def test_reports_team_ui_gap_during_a_locked_route(self):
        trace = parse_abyss_traces(
            [
                "2026-07-16 10:00:00,000 INFO planner:strict route locked: "
                "Chiz Yingxu abyss cycle / Zero E",
                "2026-07-16 10:00:01,000 INFO AutoCombatTask:planner switch_next_char "
                "(strict route) not in team 3.25s",
                "2026-07-16 10:00:02,000 INFO BaseCombatTask:队伍交接确认："
                "小吱盈蓄队 -> 白藏竞速队",
            ]
        )[0]

        self.assertIn("team UI unavailable for 3.25s during route", trace.diagnosis())
        self.assertEqual(
            [event.detail for event in trace.events if event.kind == "handoff"],
            ["小吱盈蓄队->白藏竞速队"],
        )

    def test_irrelevant_log_returns_empty_report(self):
        traces = parse_abyss_traces(["2026-07-16 10:00:00,000 INFO app:started"])

        self.assertEqual(format_trace_report(traces), "No abyss team route traces found.")


if __name__ == "__main__":
    unittest.main()
