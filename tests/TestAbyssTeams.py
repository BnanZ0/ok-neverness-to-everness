"""深渊固定队伍的真实 CombatPlanner 协作测试。"""

import unittest
from unittest.mock import Mock

from src.char.Baicang import Baicang
from src.char.BaseChar import Element
from src.char.core.CharRegistry import char_registry
from src.char.Chiz import Chiz
from src.char.custom.CustomCharManager import CustomCharManager
from src.char.Daphneel import SKILL_REUSE_GUARD as DAPHNEEL_SKILL_REUSE_GUARD
from src.char.Daphneel import Daphneel
from src.char.Hania import SKILL_REUSE_GUARD as HANIA_SKILL_REUSE_GUARD
from src.char.Hania import Hania
from src.char.Iloy import Iloy
from src.char.Mint import Mint
from src.char.Sakiri import Sakiri
from src.char.Shinku import Shinku
from src.char.Yi import Yi
from src.char.Zero import Zero
from src.combat.planner import ActionSlot, CombatPlanner, FieldPreference
from src.combat.team_strategies import is_999night_team, should_use_default_arc


class FakeTask:
    def __init__(self):
        self.chars = []
        self.cycle_full = False
        self.elapsed = 999

    def find_element_reaction_target(self, source_char):
        return None

    def time_elapsed_accounting_for_freeze(self, start, intro_motion_freeze=False):
        return self.elapsed

    def is_cycle_full(self):
        return self.cycle_full

    def wait_until(self, predicate, **kwargs):
        return predicate()


def make_team_char(task, char_cls, index, trace):
    char = char_cls(task, index, char_id=f"char_{index}")
    char.char_name = char_cls.__name__
    char.is_current_char = False
    char.is_dead = False
    char._test_skill_ready = True
    char._test_ultimate_ready = True
    char._last_skill_kwargs = {}
    char._sleep_calls = []

    def skill_available(*args, **kwargs):
        return char._test_skill_ready

    def ultimate_available(*args, **kwargs):
        return char._test_ultimate_ready

    def click_skill(*args, **kwargs):
        char._last_skill_kwargs = kwargs
        trace.append((char.name, "E"))
        was_ready = char._test_skill_ready
        char._test_skill_ready = False
        if isinstance(char, Zero) and was_ready:
            task.cycle_full = True
        return was_ready

    def click_ultimate(*args, **kwargs):
        trace.append((char.name, "Q"))
        was_ready = char._test_ultimate_ready
        char._test_ultimate_ready = False
        return was_ready

    char.skill_available = skill_available
    char.ultimate_available = ultimate_available
    char.click_skill = click_skill
    char.click_ultimate = click_ultimate
    char.sleep = lambda duration, *args, **kwargs: char._sleep_calls.append(duration)
    char.check_combat = lambda: None
    if isinstance(char, (Baicang, Daphneel, Shinku)):
        char._perform_burst = lambda *args, **kwargs: trace.append((char.name, "BURST"))
    if isinstance(char, Chiz):
        char.perform_in_ult = lambda *args, **kwargs: trace.append((char.name, "BURST")) or True
    if isinstance(char, Iloy):
        def heavy_attack_mock(duration):
            trace.append((char.name, "HEAVY"))
            char._fake_time = getattr(char, "_fake_time", 0.0) + duration

        char.heavy_attack = heavy_attack_mock
    return char


class TestBaicangAbyssTeam(unittest.TestCase):
    def setUp(self):
        self.trace = []
        self.task = FakeTask()
        self.sakiri = make_team_char(self.task, Sakiri, 0, self.trace)
        self.hania = make_team_char(self.task, Hania, 1, self.trace)
        self.daphneel = make_team_char(self.task, Daphneel, 2, self.trace)
        self.baicang = make_team_char(self.task, Baicang, 3, self.trace)
        self.task.chars = [self.sakiri, self.hania, self.daphneel, self.baicang]
        self.planner = CombatPlanner(self.task)
        self.planner.reset(self.task.chars)

    def _perform_and_switch(self, current):
        current.is_current_char = True
        self.planner.perform_current_char(current)
        return self._switch_only(current)

    def _switch_only(self, current):
        decision = self.planner.decide_switch(current)
        current.is_current_char = False
        decision.target.is_current_char = True
        self.planner.record_switch(decision.target)
        return decision.target

    def test_complete_team_starts_with_sakiri(self):
        decision = self.planner.decide_combat_start_char(self.baicang)

        self.assertIs(decision.target, self.sakiri)

    def test_sakiri_is_opener_only_in_baicang_abyss_team(self):
        profile = self.sakiri.describe_role()

        self.assertEqual(profile.field_preference, FieldPreference.SETUP_ONLY)
        self.assertEqual(profile.max_field_time, 0)

    def test_sakiri_holds_grouping_skill_and_waits_for_settle(self):
        self._perform_and_switch(self.sakiri)

        self.assertEqual(Sakiri.SKILL_SETTLE_DURATION, 1.2)
        self.assertEqual(
            self.sakiri._last_skill_kwargs["down_time"],
            Sakiri.SKILL_HOLD_DURATION,
        )
        self.assertEqual(
            self.sakiri._last_skill_kwargs["post_sleep"],
            Sakiri.SKILL_SETTLE_DURATION,
        )

    def test_sakiri_ultimate_marks_reuse_cooldown(self):
        self.sakiri._test_ultimate_ready = True
        base = self.sakiri._now()
        self.sakiri._now = lambda: base

        result = self.sakiri._execute_ultimate(None)

        self.assertTrue(result)
        self.assertIn(("Sakiri", "Q"), self.trace)
        # Right after casting, the reuse interval has not elapsed yet.
        self.assertFalse(self.sakiri._ult_reuse_ready())

    def test_sakiri_can_reult_in_loop_after_interval(self):
        # No active route: isolate the loop re-cast path (not the opener step).
        self.planner.state.locked_route = None
        ctx = self.planner.context_for(self.sakiri)
        plan = self.sakiri.combat_plan(ctx)
        ultimate = next(a for a in plan.actions if a.slot == ActionSlot.ULTIMATE)

        self.sakiri._test_ultimate_ready = True
        base = self.sakiri._now()
        self.sakiri._cooldowns.mark_used("ultimate", Sakiri.ULT_REUSE_INTERVAL, now=base)

        # Within the reuse interval the loop re-cast is gated off.
        self.sakiri._now = lambda: base + 1.0
        self.assertFalse(ultimate.is_priority_ready(ctx))

        # Once the interval has elapsed and the ultimate is off CD, it is attractive again.
        self.sakiri._now = lambda: base + Sakiri.ULT_REUSE_INTERVAL + 1.0
        self.assertTrue(ultimate.is_priority_ready(ctx))
        self.assertTrue(ultimate.is_allowed(ctx))

    def test_sakiri_actions_are_hidden_after_opener(self):
        current = self.sakiri
        current = self._perform_and_switch(current)
        current = self._perform_and_switch(current)
        current = self._perform_and_switch(current)
        self.assertIs(current, self.baicang)

        context = self.planner.context_for(self.sakiri)
        actions = self.sakiri.combat_plan(context).actions

        self.assertFalse(
            next(action for action in actions if action.slot == ActionSlot.SKILL).can_execute(
                context
            )
        )
        self.assertFalse(
            next(action for action in actions if action.slot == ActionSlot.ULTIMATE).can_execute(
                context
            )
        )

    def test_opener_routes_to_baicang_through_supports(self):
        current = self.sakiri
        current = self._perform_and_switch(current)
        self.assertIs(current, self.hania)

        current = self._perform_and_switch(current)
        self.assertIs(current, self.daphneel)

        current = self._perform_and_switch(current)
        self.assertIs(current, self.baicang)
        self.assertEqual(
            self.trace,
            [
                ("Sakiri", "E"),
                ("Sakiri", "Q"),
                ("Hania", "Q"),
                ("Hania", "E"),
                ("Daphneel", "E"),
                ("Daphneel", "Q"),
                ("Daphneel", "BURST"),
            ],
        )

    def test_hania_ultimate_is_optional_in_opener(self):
        self.hania._test_ultimate_ready = False

        current = self._perform_and_switch(self.sakiri)
        current = self._perform_and_switch(current)

        self.assertIs(current, self.daphneel)
        self.assertNotIn(("Hania", "Q"), self.trace)
        self.assertIn(("Hania", "E"), self.trace)

    def test_failed_support_actions_still_return_to_baicang(self):
        for char in (self.sakiri, self.hania, self.daphneel):
            char._test_skill_ready = False
            char._test_ultimate_ready = False

        current = self._perform_and_switch(self.sakiri)
        current = self._perform_and_switch(current)
        current = self._perform_and_switch(current)

        self.assertIs(current, self.baicang)
        self.assertIsNone(self.planner.state.locked_route)

    def test_hania_returns_to_baicang_while_baicang_skills_are_on_cooldown(self):
        current = self._perform_and_switch(self.sakiri)
        current = self._perform_and_switch(current)
        current = self._perform_and_switch(current)
        self.assertIs(current, self.baicang)

        self.baicang._test_skill_ready = False
        self.baicang._test_ultimate_ready = False
        self.sakiri._test_ultimate_ready = False
        self.daphneel._test_skill_ready = False
        self.daphneel._test_ultimate_ready = False
        self.hania._test_skill_ready = True
        self.hania._test_ultimate_ready = True

        current = self._switch_only(current)
        self.assertIs(current, self.hania)
        current = self._perform_and_switch(current)

        self.assertIs(current, self.baicang)

    def test_other_sakiri_team_keeps_default_start_priority(self):
        self.task.chars = [self.sakiri, self.hania]
        planner = CombatPlanner(self.task)
        planner.reset(self.task.chars)

        decision = planner.decide_combat_start_char(self.hania)

        self.assertIs(decision.target, self.hania)

    def test_opener_deadline_unlocks_route(self):
        self.baicang.ABYSS_OPENER_TIMEOUT = 0

        self.planner.context_for(self.sakiri)
        self.planner.context_for(self.sakiri)

        self.assertIsNone(self.planner.state.locked_route)


class TestChizAbyssTeam(unittest.TestCase):
    def setUp(self):
        self.trace = []
        self.task = FakeTask()
        self.chiz = make_team_char(self.task, Chiz, 0, self.trace)
        self.zero = make_team_char(self.task, Zero, 1, self.trace)
        self.iloy = make_team_char(self.task, Iloy, 2, self.trace)
        self.yi = make_team_char(self.task, Yi, 3, self.trace)
        self.iloy.element = Element.GREEN
        self.yi.element = Element.YELLOW
        self.zero.element = Element.WHITE
        self.chiz.element = Element.WHITE
        self.task.chars = [self.chiz, self.zero, self.iloy, self.yi]
        self.planner = CombatPlanner(self.task)
        self.planner.reset(self.task.chars)

    def _perform_and_switch(self, current):
        current.is_current_char = True
        self.planner.perform_current_char(current)
        return self._switch_only(current)

    def _switch_only(self, current):
        decision = self.planner.decide_switch(current)
        current.is_current_char = False
        decision.target.is_current_char = True
        if decision.has_intro and self._can_record_reaction(current, decision.target):
            self.planner.record_entry_reaction(current, decision.target)
            self.task.cycle_full = False
        self.planner.record_switch(decision.target)
        return decision.target

    def _can_record_reaction(self, source, target):
        ring = (
            Element.WHITE,
            Element.GREEN,
            Element.RED,
            Element.PURPLE,
            Element.BLUE,
            Element.YELLOW,
        )
        source_index = ring.index(source.element)
        target_index = ring.index(target.element)
        return (source_index - target_index) % len(ring) in (1, len(ring) - 1)

    def test_yi_is_registered_as_aspect_setup_role(self):
        self.assertIs(char_registry.get("builtin:yi").char_cls, Yi)
        self.assertEqual(char_registry.get("builtin:yi").cn_name, "翳")
        self.assertEqual(char_registry.get("builtin:yi").element, Element.YELLOW)
        self.assertEqual(self.yi.describe_role().max_field_time, 0)

    def test_yi_unavailable_setup_actions_are_not_executable(self):
        self.yi._test_skill_ready = False
        self.yi._test_ultimate_ready = False
        context = self.planner.context_for(self.yi)
        actions = self.yi.combat_plan(context).actions

        self.assertTrue(actions)
        self.assertTrue(all(not action.is_allowed(context) for action in actions))

    def test_zero_is_setup_only_in_chiz_team(self):
        profile = self.zero.describe_role()

        self.assertEqual(profile.field_preference, FieldPreference.SETUP_ONLY)
        self.assertEqual(profile.max_field_time, 0)

    def test_yi_is_exposed_in_character_center_builtin_combos(self):
        combo_ids = {combo_id for _, combo_id in CustomCharManager.iter_builtin_impl_items()}

        self.assertIn("builtin:yi", combo_ids)

    def test_complete_team_starts_with_iloy(self):
        decision = self.planner.decide_combat_start_char(self.chiz)

        self.assertIs(decision.target, self.iloy)

    def test_iloy_skill_uses_short_timeout(self):
        self._perform_and_switch(self.iloy)

        self.assertEqual(Iloy.SKILL_REUSE_GUARD, 8.0)
        self.assertEqual(self.iloy._last_skill_kwargs["time_out"], 2.0)
        self.assertIn(Iloy.SKILL_SETTLE_DURATION, self.iloy._sleep_calls)

    def test_yi_skill_keeps_a_short_settle_window(self):
        plan = self.yi.combat_plan(Mock())
        skill = next(action for action in plan.actions if action.slot is ActionSlot.SKILL)

        self.assertTrue(skill.run(Mock()))
        self.assertEqual(
            self.yi._last_skill_kwargs["post_sleep"],
            Yi.SKILL_SETTLE_DURATION,
        )

    def test_other_iloy_team_keeps_default_start_priority(self):
        self.task.chars = [self.iloy, self.zero]
        planner = CombatPlanner(self.task)
        planner.reset(self.task.chars)

        decision = planner.decide_combat_start_char(self.zero)

        self.assertIs(decision.target, self.zero)

    def test_opener_deadline_unlocks_route(self):
        self.chiz.ABYSS_ROUTE_TIMEOUT = 0

        self.planner.context_for(self.iloy)
        self.planner.context_for(self.iloy)

        self.assertIsNone(self.planner.state.locked_route)

    def test_opener_sends_chiz_in_before_waiting_for_second_zero_skill(self):
        current = self._perform_and_switch(self.iloy)
        self.assertIs(current, self.zero)

        current = self._perform_and_switch(current)
        self.assertIs(current, self.chiz)
        self.planner.perform_current_char(current)

        self.assertEqual(
            self.trace,
            [
                ("Iloy", "E"),
                ("Zero", "Q"),
                ("Zero", "E"),
                ("Chiz", "Q"),
                ("Chiz", "BURST"),
            ],
        )
        self.assertEqual(self.planner.state.locked_route.reason, "Chiz Yingxu abyss cycle")

    def test_optional_support_ultimates_do_not_block_opener(self):
        self.zero._test_ultimate_ready = False

        current = self._perform_and_switch(self.iloy)
        current = self._perform_and_switch(current)

        self.assertIs(current, self.chiz)
        self.assertNotIn(("Zero", "Q"), self.trace)

    def test_completed_burst_publishes_and_executes_next_yingxu_cycle(self):
        current = self._perform_and_switch(self.iloy)
        current = self._perform_and_switch(current)
        self.assertIs(current, self.chiz)

        self.planner.perform_current_char(current)
        self.assertEqual(self.planner.state.locked_route.reason, "Chiz Yingxu abyss cycle")

        current = self._switch_only(current)
        self.assertIs(current, self.iloy)

        current = self._perform_and_switch(current)
        self.assertIs(current, self.zero)

        self.zero._test_skill_ready = True
        current = self._perform_and_switch(current)
        self.assertIs(current, self.yi)

        self.yi._test_ultimate_ready = True
        self.yi._test_skill_ready = True
        current = self._perform_and_switch(current)
        self.assertIs(current, self.iloy)

        self.iloy._test_skill_ready = True
        current = self._perform_and_switch(current)
        self.assertIs(current, self.chiz)

        self.chiz._test_ultimate_ready = True
        self.planner.perform_current_char(current)

        self.assertEqual(self.trace.count(("Chiz", "BURST")), 2)
        self.assertEqual(self.planner.state.locked_route.reason, "Chiz Yingxu abyss cycle")

    def test_chiz_can_use_skill_while_waiting_for_yingxu_entry_reaction(self):
        current = self._perform_and_switch(self.iloy)
        current = self._perform_and_switch(current)
        self.assertIs(current, self.chiz)

        self.planner.perform_current_char(current)
        route = self.planner.state.locked_route
        self.assertIsNotNone(route)
        self.assertTrue(route.current_step().requires_entry_reaction)

        self.chiz.perform_skill_chain = (
            lambda context=None: self.trace.append(("Chiz", "E_WAIT")) or True
        )
        result = self.planner.perform_current_char(current)

        self.assertEqual(result.name, "Chiz_skill_chain")
        self.assertIn(("Chiz", "E_WAIT"), self.trace)
        self.assertIs(self.planner.state.locked_route, route)
        self.assertTrue(route.current_step().requires_entry_reaction)


class TestChizBurstSafety(unittest.TestCase):
    def test_skill_chain_uses_up_to_three_charges(self):
        task = FakeTask()
        char = Chiz(task, 0, char_id="chiz")
        task.chars = [char]
        char.is_current_char = True
        char.is_dead = False
        attacks = []
        sleeps = []
        skills = []
        char.click_with_interval = lambda *args, **kwargs: attacks.append("A")
        char.sleep = lambda duration, *args, **kwargs: sleeps.append(duration)
        char.skill_available = lambda *args, **kwargs: True
        char.send_skill_key = lambda *args, **kwargs: skills.append("E") or True

        self.assertTrue(char.perform_skill_chain())
        self.assertEqual(skills, ["E", "E", "E"])
        self.assertEqual(attacks, ["A"] * 6)
        self.assertEqual(sleeps, [0.35] * 6)

    def test_burst_stops_casting_when_switched_out(self):
        task = FakeTask()
        task.box_of_screen = lambda *args, **kwargs: object()
        task.wait_ocr = lambda *args, **kwargs: None
        task.calculate_color_percentage = lambda color, box: (
            0.8 if color is not None and color["g"][0] > 150 else 0.1
        )
        trace = []
        char = Chiz(task, 0, char_id="chiz")
        task.chars = [char]
        char.is_current_char = True
        char.is_dead = False
        now = [0.0]
        attacks = [0]

        char._now = lambda: now[0]
        char.skill_available = lambda *args, **kwargs: True
        char.send_skill_key = lambda *args, **kwargs: trace.append("E") or True
        char.check_combat = lambda: None
        char.sleep = lambda duration, *args, **kwargs: now.__setitem__(0, now[0] + duration)

        def attack_once():
            attacks[0] += 1
            if len(trace) == 3:
                char.is_current_char = False

        char.click_with_interval = attack_once
        completed = char.perform_in_ult()

        self.assertEqual(trace, ["E", "E", "E"])
        self.assertGreaterEqual(attacks[0], 3)
        self.assertFalse(completed)

    def test_burst_casts_up_to_ult_skill_cap(self):
        """大招内 E 上限为 ULT_SKILL_MAX_USES(8): 闸门开、充能常就绪、不切人时放满 8 次。"""
        task = FakeTask()
        task.box_of_screen = lambda *args, **kwargs: object()
        task.wait_ocr = lambda *args, **kwargs: None
        task.calculate_color_percentage = lambda color, box: (
            0.8 if color is not None and color["g"][0] > 150 else 0.1
        )
        trace = []
        char = Chiz(task, 0, char_id="chiz")
        task.chars = [char]
        char.is_current_char = True
        char.is_dead = False
        now = [0.0]
        char._now = lambda: now[0]
        char.skill_available = lambda *args, **kwargs: True
        char.send_skill_key = lambda *args, **kwargs: trace.append("E") or True
        char.check_combat = lambda: None
        char.sleep = lambda duration, *args, **kwargs: now.__setitem__(0, now[0] + duration)
        char.click_with_interval = lambda *args, **kwargs: None

        completed = char.perform_in_ult()

        self.assertEqual(char.ULT_SKILL_MAX_USES, 8)
        self.assertEqual(trace, ["E"] * 8)
        self.assertTrue(completed)


class TestAbyssInputPolicies(unittest.TestCase):
    def test_both_abyss_main_dps_hold_when_support_has_no_executable_e_or_q(self):
        cases = (
            (Baicang, (Baicang, Daphneel, Sakiri, Hania)),
            (Chiz, (Chiz, Zero, Iloy, Yi)),
        )
        for main_cls, team_classes in cases:
            with self.subTest(main=main_cls.__name__):
                task = FakeTask()
                trace = []
                team = [
                    make_team_char(task, char_cls, index, trace)
                    for index, char_cls in enumerate(team_classes)
                ]
                task.chars = team
                planner = CombatPlanner(task)
                planner.reset(team)
                planner.state.locked_route = None
                planner.state.active_requests.clear()

                main = next(char for char in team if isinstance(char, main_cls))
                main.is_current_char = True
                main.last_perform = 1.0
                for char in team:
                    if char is not main:
                        char._test_skill_ready = False
                        char._test_ultimate_ready = False

                decision = planner.decide_switch(main)

                self.assertIs(decision.target, main)
                self.assertIn("main DPS", decision.reason)

    def test_abyss_element_reaction_waits_for_main_window_and_real_e_or_q(self):
        task = FakeTask()
        trace = []
        team = [
            make_team_char(task, char_cls, index, trace)
            for index, char_cls in enumerate((Chiz, Zero, Iloy, Yi))
        ]
        task.chars = team
        planner = CombatPlanner(task)
        planner.reset(team)
        planner.state.locked_route = None
        planner.state.active_requests.clear()
        main = team[0]
        target = team[1]
        main.is_current_char = True
        main.last_perform = 1.0
        task.cycle_full = True
        task.elapsed = 1.0
        task.find_element_reaction_target = lambda _source: target
        target._test_skill_ready = False
        target._test_ultimate_ready = False

        decision = planner.decide_switch(main)

        self.assertIs(decision.target, main)

    def test_main_dps_plain_support_switch_waits_for_minimum_field_time(self):
        cases = (
            (Baicang, (Baicang, Daphneel, Sakiri, Hania), 1),
            (Chiz, (Chiz, Zero, Iloy, Yi), 1),
        )
        for main_cls, team_classes, target_index in cases:
            with self.subTest(main=main_cls.__name__):
                task = FakeTask()
                trace = []
                team = [
                    make_team_char(task, char_cls, index, trace)
                    for index, char_cls in enumerate(team_classes)
                ]
                task.chars = team
                main = team[0]
                target = team[target_index]
                main.is_current_char = True
                main.last_perform = 10.0
                task.elapsed = 0.0
                context = Mock(chars=team)
                context.has_strict_route.return_value = False

                guard = target.switch_in_guard(context, main, has_intro=False)

                self.assertTrue(guard.should_delay())
                task.elapsed = main.MIN_FIELD_TIME
                self.assertFalse(guard.should_delay())

                task.elapsed = 0.0
                intro_guard = target.switch_in_guard(context, main, has_intro=True)
                self.assertFalse(intro_guard.should_delay())

    def test_target_teams_only_send_arc_for_baicang_and_daphneel(self):
        task = FakeTask()
        trace = []
        baicang_team = [
            make_team_char(task, Baicang, 0, trace),
            make_team_char(task, Daphneel, 1, trace),
            make_team_char(task, Sakiri, 2, trace),
            make_team_char(task, Hania, 3, trace),
        ]
        chiz_team = [
            make_team_char(task, Chiz, 0, trace),
            make_team_char(task, Zero, 1, trace),
            make_team_char(task, Iloy, 2, trace),
            make_team_char(task, Yi, 3, trace),
        ]

        self.assertTrue(should_use_default_arc(baicang_team[0], baicang_team))
        self.assertTrue(should_use_default_arc(baicang_team[1], baicang_team))
        self.assertFalse(should_use_default_arc(baicang_team[2], baicang_team))
        self.assertFalse(should_use_default_arc(baicang_team[3], baicang_team))
        self.assertTrue(all(not should_use_default_arc(char, chiz_team) for char in chiz_team))
        self.assertEqual(Baicang.ARC_CHECK_INTERVAL, 20.0)

    def test_failed_support_skill_is_suppressed_for_four_seconds(self):
        for char_cls in (Hania, Daphneel):
            with self.subTest(char_cls=char_cls.__name__):
                task = FakeTask()
                char = char_cls(task, 0, char_id=char_cls.__name__)
                now = [10.0]
                char._now = lambda: now[0]
                char.skill_available = lambda *args, **kwargs: True
                char.click_skill = lambda *args, **kwargs: False

                self.assertFalse(char._execute_skill())
                self.assertFalse(char._skill_ready())
                now[0] = 14.0
                self.assertTrue(char._skill_ready())

    def test_successful_support_skill_is_guarded_until_effect_can_expire(self):
        guards = {
            Hania: HANIA_SKILL_REUSE_GUARD,
            Daphneel: DAPHNEEL_SKILL_REUSE_GUARD,
        }
        for char_cls, guard in guards.items():
            with self.subTest(char_cls=char_cls.__name__):
                task = FakeTask()
                char = char_cls(task, 0, char_id=char_cls.__name__)
                now = [10.0]
                char._now = lambda: now[0]
                char.skill_available = lambda *args, **kwargs: True
                char.click_skill = lambda *args, **kwargs: True

                self.assertTrue(char._execute_skill())
                self.assertFalse(char._skill_ready())
                now[0] = 10.0 + guard
                self.assertTrue(char._skill_ready())

    def test_combat_end_clears_support_skill_guard(self):
        for char_cls in (Hania, Daphneel):
            with self.subTest(char_cls=char_cls.__name__):
                task = FakeTask()
                char = char_cls(task, 0, char_id=char_cls.__name__)
                char._skill_ready_after = 99.0
                char.on_combat_end([])
                self.assertEqual(char._skill_ready_after, 0.0)


class Test999NightTeam(unittest.TestCase):
    """999-night idle team: Iloy + Mint + Zero + Shinku."""

    def setUp(self):
        self.trace = []
        self.task = FakeTask()
        self.iloy = make_team_char(self.task, Iloy, 0, self.trace)
        self.mint = make_team_char(self.task, Mint, 1, self.trace)
        self.zero = make_team_char(self.task, Zero, 2, self.trace)
        self.shinku = make_team_char(self.task, Shinku, 3, self.trace)
        # Override _now for deterministic cooldowns
        self._fake_time = [0.0]
        for c in (self.iloy, self.mint, self.zero, self.shinku):
            c._now = lambda ft=self._fake_time: ft[0]
            c.sleep = lambda sec, *a, **kw: self._fake_time.__setitem__(0, self._fake_time[0] + sec)
            c.normal_attack = lambda name=c.name, *a, **kw: self.trace.append((name, "A"))
        self.task.chars = [self.iloy, self.mint, self.zero, self.shinku]
        self.planner = CombatPlanner(self.task)
        self.planner.reset(self.task.chars)

    def _perform_and_switch(self, current):
        current.is_current_char = True
        self.planner.perform_current_char(current)
        return self._switch_only(current)

    def _switch_only(self, current):
        decision = self.planner.decide_switch(current)
        current.is_current_char = False
        decision.target.is_current_char = True
        self.planner.record_switch(decision.target)
        return decision.target

    def test_team_detection(self):
        self.assertTrue(is_999night_team(self.task.chars))

    def test_team_detection_rejects_partial(self):
        self.assertFalse(is_999night_team([self.iloy, self.mint, self.shinku]))

    def test_team_detection_rejects_non_zero_fourth(self):
        """Fourth slot must be Zero, not another char type."""
        self.assertFalse(
            is_999night_team([self.iloy, self.mint, self.shinku, self.mint])
        )

    def test_iloy_has_high_start_priority(self):
        decision = self.planner.decide_combat_start_char(self.shinku)
        self.assertIs(decision.target, self.iloy)

    def test_opener_routes_through_full_team(self):
        current = self.iloy
        current = self._perform_and_switch(current)
        self.assertIs(current, self.mint)

        current = self._perform_and_switch(current)
        self.assertIs(current, self.zero)

        current = self._perform_and_switch(current)
        self.assertIs(current, self.shinku)

        self.planner.perform_current_char(current)

        # heavy_attack is skipped during opener: planner switches to Mint
        # immediately after Iloy Q (route step 2). heavy_attack runs in cycles.
        self.assertEqual(
            self.trace,
            [
                ("Iloy", "E"),
                ("Iloy", "Q"),
                ("Mint", "Q"),
                ("Mint", "E"),
                ("Zero", "Q"),
                ("Zero", "E"),
                ("Shinku", "E"),
                ("Shinku", "Q"),
                ("Shinku", "BURST"),
            ],
        )

    def test_shinku_is_strategy_source(self):
        from src.combat.team_strategies import team_strategy_source

        self.assertIs(team_strategy_source(self.task.chars), self.shinku)

    def test_request_switch_chain_after_opener(self):
        """After opener, request_switch chain: Shinku -> Iloy -> Mint -> Zero -> Shinku."""
        # Complete opener
        current = self.iloy
        current = self._perform_and_switch(current)
        current = self._perform_and_switch(current)
        current = self._perform_and_switch(current)
        self.planner.perform_current_char(current)

        # Reset skill/ultimate availability for cycle
        for c in (self.iloy, self.mint, self.zero, self.shinku):
            c._test_skill_ready = True
            c._test_ultimate_ready = True

        # Shinku should request Iloy
        current = self._switch_only(current)
        self.assertIs(current, self.iloy)

        # Iloy should request Mint
        current = self._perform_and_switch(current)
        self.assertIs(current, self.mint)

        # Mint should request Zero
        current = self._perform_and_switch(current)
        self.assertIs(current, self.zero)

        # Zero should request Shinku
        current = self._perform_and_switch(current)
        self.assertIs(current, self.shinku)

    def test_failed_opener_still_cycles(self):
        """All skills fail: opener steps are optional, team still cycles."""
        for c in (self.iloy, self.mint, self.zero, self.shinku):
            c._test_skill_ready = False
            c._test_ultimate_ready = False

        current = self.iloy
        current = self._perform_and_switch(current)
        self.assertIs(current, self.mint)
        current = self._perform_and_switch(current)
        self.assertIs(current, self.zero)
        current = self._perform_and_switch(current)
        self.assertIs(current, self.shinku)
        self.planner.perform_current_char(current)

        # No E/Q/HEAVY/BURST in trace - all skills were unavailable
        skill_traces = [
            t for t in self.trace if t[1] in ("E", "Q", "HEAVY", "BURST")
        ]
        self.assertEqual(skill_traces, [])

    def test_opener_deadline_unlocks_route(self):
        self.iloy.ABYSS_OPENER_TIMEOUT = 0

        self.planner.context_for(self.iloy)
        self.planner.context_for(self.iloy)

        self.assertIsNone(self.planner.state.locked_route)


if __name__ == "__main__":
    unittest.main()
