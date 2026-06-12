import unittest
from pathlib import Path

from src.char.BaseChar import BaseChar
from src.combat.planner import (
    NEVER_EXPIRES,
    ActionIntent,
    ActionReservation,
    ActionResult,
    ActionSlot,
    ActionTag,
    CombatPlanner,
    EntryChainPolicy,
    ExpectedEntry,
    FieldClaim,
    FieldPreference,
    FollowupStep,
    Role,
    RoleProfile,
    SwitchInGuard,
)


class FakeTask:
    def __init__(self):
        self.chars = []
        self.reaction_target = None

    def time_elapsed_accounting_for_freeze(self, start, intro_motion_freeze=False):
        return 999

    def find_element_ring_reaction_target(self, source_char):
        return self.reaction_target


class FakeChar:
    def __init__(
        self,
        index,
        name,
        field_preference=FieldPreference.SUB_DPS,
        tags=None,
        intents=None,
        policies=None,
        claims=None,
        can_execute=None,
        priority_ready=None,
        switch_in_guard=None,
        max_field_time=1.5,
        combat_start_priority=0,
        cycle_full=False,
    ):
        self.index = index
        self.name = name
        self.char_name = name
        self.last_perform = 0
        self.last_switch_time = -1
        self.is_current_char = False
        self._field_preference = field_preference
        self._tags = set(tags or {ActionTag.DAMAGE})
        self._intents = intents
        self._policies = policies
        self._claims = claims or []
        self._can_execute = can_execute
        self._priority_ready = priority_ready
        self._switch_in_guard = switch_in_guard
        self._max_field_time = max_field_time
        self._combat_start_priority = combat_start_priority
        self._cycle_full = cycle_full
        self.waited = 0
        self.intent_calls = 0

    def __repr__(self):
        return self.name

    def __eq__(self, other):
        return isinstance(other, FakeChar) and self.index == other.index

    def describe_role(self):
        role = (
            Role.MAIN_DPS
            if self._field_preference == FieldPreference.MAIN_DPS
            else Role.SUB_DPS
        )
        return RoleProfile(
            role=role,
            field_preference=self._field_preference,
            max_field_time=self._max_field_time,
            combat_start_priority=self._combat_start_priority,
        )

    def combat_intents(self, context):
        self.intent_calls += 1
        if callable(self._intents):
            return self._intents(context)
        if self._intents is not None:
            return list(self._intents)

        claims = self._claims(context) if callable(self._claims) else self._claims
        slot = None
        if ActionTag.SKILL_ACTION in self._tags:
            slot = ActionSlot.SKILL
        elif ActionTag.ULTIMATE_ACTION in self._tags:
            slot = ActionSlot.ULTIMATE
        return [
            ActionIntent(
                name=f"{self.name}_action",
                tags=set(self._tags),
                execute=lambda _: ActionResult(
                    name=f"{self.name}_action",
                    success=True,
                    tags=set(self._tags),
                    slot=slot,
                ),
                slot=slot,
                reason=f"{self.name} available",
                can_execute=self._can_execute,
                priority_ready=self._priority_ready,
            )
        ] + list(claims)

    def combat_policies(self, context):
        if self._policies is not None:
            self._policies(context)

    def is_cycle_full(self):
        return self._cycle_full

    def continues_normal_attack(self, duration):
        self.waited = duration

    def switch_in_guard(self, context, from_char, has_intro):
        if self._switch_in_guard is None:
            return SwitchInGuard.allow()
        return self._switch_in_guard(context, from_char, has_intro)


class PublicApiChar(BaseChar):
    def __init__(self, task, index, name, intents_factory, max_field_time=0):
        super().__init__(task, index, char_name=name)
        self.char_name = name
        self._intents_factory = intents_factory
        self._max_field_time = max_field_time
        self.skill_clicked = 0
        self.ultimate_clicked = 0
        self.arc_clicked = 0
        self.normal_attack_time = 0

    def __repr__(self):
        return self.char_name

    def __str__(self):
        return self.char_name

    def combat_intents(self, context):
        return self._intents_factory(self, context)

    def describe_role(self):
        return RoleProfile(max_field_time=self._max_field_time)

    def skill_available(self, wait_if_cd_ready=0):
        return True

    def ultimate_available(self, wait_if_cd_ready=0):
        return True

    def click_skill(self, *args, **kwargs):
        self.skill_clicked += 1
        return True

    def click_ultimate(self, *args, **kwargs):
        self.ultimate_clicked += 1
        return True

    def click_arc(self, *args, **kwargs):
        self.arc_clicked += 1
        return True

    def continues_normal_attack(self, duration):
        self.normal_attack_time = duration


class TestCombatPlanner(unittest.TestCase):
    def _char(self, index, name, **kwargs):
        return FakeChar(index, name, **kwargs)

    def _main_dps(self, index, name="dps", **kwargs):
        return self._char(
            index,
            name,
            field_preference=FieldPreference.MAIN_DPS,
            **kwargs,
        )

    def _support(self, index, name="support", **kwargs):
        return self._char(
            index,
            name,
            field_preference=FieldPreference.SUPPORT,
            **kwargs,
        )

    def _setup_char(self, index, name="setup", **kwargs):
        return self._char(
            index,
            name,
            field_preference=FieldPreference.SETUP_ONLY,
            **kwargs,
        )

    def _planner(self, chars):
        task = FakeTask()
        task.chars = chars
        planner = CombatPlanner(task)
        planner.reset(chars)
        return planner

    def _publish(self, planner, source, publish):
        original_combat_intents = source.combat_intents

        def execute(context):
            publish(context)
            return True

        def combat_intents(_):
            return [
                ActionIntent(
                    name="publish_test_request",
                    tags={ActionTag.DEFAULT_ACTION},
                    execute=execute,
                    reason="publish test request",
                    chain_policy=EntryChainPolicy.STOP,
                )
            ]

        source.combat_intents = combat_intents
        try:
            planner.perform_current_char(source)
        finally:
            source.combat_intents = original_combat_intents

    def _action(
        self,
        name,
        tags,
        slot=None,
        calls=None,
        success=True,
        priority_ready=None,
        chain_policy=EntryChainPolicy.CONTINUE,
    ):
        def execute(_):
            if calls is not None:
                calls.append(name)
            return ActionResult(
                name=name,
                success=success,
                tags=set(tags),
                slot=slot,
            )

        return ActionIntent(
            name=name,
            tags=set(tags),
            slot=slot,
            execute=execute,
            reason=f"{name} ready",
            priority_ready=priority_ready,
            chain_policy=chain_policy,
        )

    def test_main_dps_field_preference_boosts_entry(self):
        current = self._support(0, "current")
        dps = self._main_dps(1)
        support = self._support(2)
        planner = self._planner([current, dps, support])

        decision = planner.decide_switch(current)

        self.assertEqual(decision.target, dps)
        self.assertIn("dps", decision.reason)

    def test_normal_switch_excludes_current_from_scoring(self):
        dps = self._main_dps(0)
        support = self._support(1)
        planner = self._planner([dps, support])

        decision = planner.decide_switch(dps)

        self.assertEqual(decision.target, support)

    def test_decide_switch_caches_combat_intents_per_char(self):
        current = FakeChar(0, "current")
        claimed = FakeChar(
            1,
            "claimed",
            claims=lambda _: [FieldClaim.high("claim also scans intents")],
        )
        planner = self._planner([current, claimed])

        planner.decide_switch(current)

        self.assertEqual(claimed.intent_calls, 1)

    def test_field_claim_can_request_entry_without_ready_action(self):
        current = FakeChar(0, "current")
        claimed = FakeChar(
            1,
            "claimed",
            priority_ready=lambda _: False,
            max_field_time=0,
            claims=lambda _: [FieldClaim.critical("check mechanism")],
        )
        planner = self._planner([current, claimed])

        decision = planner.decide_switch(current)

        self.assertEqual(decision.target, claimed)
        self.assertIn("field claim", decision.reason)

    def test_combat_start_uses_role_profile_priority(self):
        current = FakeChar(0, "current")
        low = FakeChar(1, "low", combat_start_priority=20)
        high = FakeChar(2, "high", combat_start_priority=100)
        planner = self._planner([current, low, high])

        decision = planner.decide_combat_start_char(current)

        self.assertEqual(decision.target, high)
        self.assertEqual(decision.reason, "combat start priority")

    def test_action_intent_auto_builds_result(self):
        action = ActionIntent(
            name="simple_skill",
            tags={ActionTag.SKILL_ACTION},
            slot=ActionSlot.SKILL,
            execute=lambda _: True,
        )

        result = action.run(None)

        self.assertEqual(result.name, "simple_skill")
        self.assertTrue(result.success)
        self.assertEqual(result.tags, {ActionTag.SKILL_ACTION})
        self.assertEqual(result.slot, ActionSlot.SKILL)

    def test_anonymous_action_keeps_empty_name_but_is_not_repeated(self):
        calls = []
        char = FakeChar(
            0,
            "anonymous",
            intents=lambda _: [
                ActionIntent(
                    tags={ActionTag.SKILL_ACTION},
                    slot=ActionSlot.CUSTOM,
                    execute=lambda _: calls.append("ran") or True,
                    reason="anonymous action",
                )
            ],
        )
        planner = self._planner([char])

        result = planner.perform_current_char(char)

        self.assertEqual(result.name, "")
        self.assertEqual(calls, ["ran"])

    def test_action_intent_none_result_is_not_success(self):
        action = ActionIntent(
            name="forgot_return",
            tags={ActionTag.SKILL_ACTION},
            execute=lambda _: None,
        )

        result = action.run(None)

        self.assertFalse(result.success)

    def test_planner_falls_back_to_field_time_when_actions_fail(self):
        char = FakeChar(
            0,
            "lacrimosa",
            field_preference=FieldPreference.MAIN_DPS,
            intents=lambda _: [
                ActionIntent(
                    name="lacrimosa_skill",
                    tags={ActionTag.SKILL_ACTION},
                    execute=lambda _: False,
                    reason="skill declared",
                    priority_ready=lambda _: True,
                )
            ],
            max_field_time=1.25,
        )
        planner = self._planner([char])

        result = planner.perform_current_char(char)

        self.assertEqual(result.name, "planner_field_time")
        self.assertEqual(result.tags, {ActionTag.FIELD_TIME, ActionTag.DAMAGE})
        self.assertEqual(char.waited, 1.25)

    def test_perform_current_char_can_chain_ultimate_and_skill(self):
        calls = []
        char = FakeChar(
            0,
            "combo",
            intents=lambda _: [
                self._action(
                    "combo_ultimate",
                    {ActionTag.ULTIMATE_ACTION},
                    ActionSlot.ULTIMATE,
                    calls,
                ),
                self._action(
                    "combo_skill",
                    {ActionTag.SKILL_ACTION},
                    ActionSlot.SKILL,
                    calls,
                ),
            ],
        )
        planner = self._planner([char])

        result = planner.perform_current_char(char)

        self.assertEqual(calls, ["combo_ultimate", "combo_skill"])
        self.assertEqual(result.name, "combo_skill")

    def test_reservation_does_not_stop_entry_action_chain(self):
        calls = []
        source = FakeChar(0, "hotori")
        reserved = FakeChar(1, "zero")
        char = FakeChar(
            2,
            "nanally",
            intents=lambda _: [
                self._action("nanally_skill", {ActionTag.SKILL_ACTION}, ActionSlot.SKILL, calls),
                self._action(
                    "nanally_ultimate",
                    {ActionTag.ULTIMATE_ACTION},
                    ActionSlot.ULTIMATE,
                    calls,
                ),
            ],
        )
        planner = self._planner([source, reserved, char])
        self._publish(
            planner,
            source,
            lambda context: context.reserve_actions(
                [ActionReservation.for_action(reserved, ActionSlot.SKILL)],
                reason="reserve teammate skill",
                until=NEVER_EXPIRES,
            ),
        )

        result = planner.perform_current_char(char)

        self.assertEqual(calls, ["nanally_skill", "nanally_ultimate"])
        self.assertEqual(result.name, "nanally_ultimate")

    def test_reservation_does_not_stop_failure_entry_action_chain(self):
        calls = []
        source = FakeChar(0, "hotori")
        reserved = FakeChar(1, "zero")
        char = FakeChar(
            2,
            "jiuyuan",
            intents=lambda _: [
                ActionIntent(
                    name="jiuyuan_ultimate",
                    tags={ActionTag.ULTIMATE_ACTION},
                    slot=ActionSlot.ULTIMATE,
                    execute=lambda _: calls.append("ultimate") or False,
                ),
                self._action(
                    "jiuyuan_skill",
                    {ActionTag.SKILL_ACTION},
                    ActionSlot.SKILL,
                    calls,
                ),
                self._action(
                    "jiuyuan_bullets",
                    {ActionTag.DEFAULT_ACTION},
                    None,
                    calls,
                ),
            ],
        )
        planner = self._planner([source, reserved, char])
        self._publish(
            planner,
            source,
            lambda context: context.reserve_actions(
                [ActionReservation.for_action(reserved, ActionSlot.SKILL)],
                reason="reserve teammate skill",
                until=NEVER_EXPIRES,
            ),
        )

        result = planner.perform_current_char(char)

        self.assertEqual(calls, ["ultimate", "jiuyuan_skill", "jiuyuan_bullets"])
        self.assertEqual(result.name, "jiuyuan_bullets")

    def test_switch_request_does_not_stop_failure_entry_action_chain(self):
        calls = []
        source = FakeChar(0, "hotori")
        target = FakeChar(1, "zero")
        current = FakeChar(
            2,
            "jiuyuan",
            intents=lambda _: [
                ActionIntent(
                    name="jiuyuan_ultimate",
                    tags={ActionTag.ULTIMATE_ACTION},
                    slot=ActionSlot.ULTIMATE,
                    execute=lambda _: calls.append("ultimate") or False,
                ),
                self._action(
                    "jiuyuan_skill",
                    {ActionTag.SKILL_ACTION},
                    ActionSlot.SKILL,
                    calls,
                ),
            ],
        )
        planner = self._planner([source, target, current])
        self._publish(
            planner,
            source,
            lambda context: context.request_switch(target, reason="switch later"),
        )

        result = planner.perform_current_char(current)

        self.assertEqual(calls, ["ultimate", "jiuyuan_skill"])
        self.assertEqual(result.name, "jiuyuan_skill")

    def test_tag_request_stops_failure_entry_action_chain(self):
        calls = []
        source = FakeChar(0, "source")
        current = FakeChar(
            1,
            "jiuyuan",
            intents=lambda _: [
                ActionIntent(
                    name="jiuyuan_ultimate",
                    tags={ActionTag.ULTIMATE_ACTION},
                    slot=ActionSlot.ULTIMATE,
                    execute=lambda _: calls.append("ultimate") or False,
                ),
                self._action(
                    "jiuyuan_skill",
                    {ActionTag.SKILL_ACTION},
                    ActionSlot.SKILL,
                    calls,
                ),
            ],
        )
        planner = self._planner([source, current])
        self._publish(
            planner,
            source,
            lambda context: context.request_tags(
                {ActionTag.SUPPORT},
                reason="needs support",
            ),
        )

        result = planner.perform_current_char(current)

        self.assertEqual(calls, ["ultimate"])
        self.assertEqual(result.name, "jiuyuan_ultimate")

    def test_normal_entry_executes_declared_order_not_highest_score_first(self):
        calls = []
        char = FakeChar(
            0,
            "nanally",
            intents=lambda _: [
                self._action(
                    "nanally_skill",
                    {ActionTag.SKILL_ACTION},
                    ActionSlot.SKILL,
                    calls,
                ),
                self._action(
                    "nanally_ultimate",
                    {ActionTag.ULTIMATE_ACTION},
                    ActionSlot.ULTIMATE,
                    calls,
                ),
            ],
        )
        planner = self._planner([char])

        result = planner.perform_current_char(char)

        self.assertEqual(calls, ["nanally_skill", "nanally_ultimate"])
        self.assertEqual(result.name, "nanally_ultimate")

    def test_normal_switch_does_not_force_best_scoring_action_as_expected_entry(self):
        current = FakeChar(0, "current", field_preference=FieldPreference.SUPPORT)
        nanally = FakeChar(
            1,
            "nanally",
            intents=lambda _: [
                self._action("nanally_skill", {ActionTag.SKILL_ACTION}, ActionSlot.SKILL),
                self._action(
                    "nanally_ultimate",
                    {ActionTag.ULTIMATE_ACTION},
                    ActionSlot.ULTIMATE,
                ),
            ],
        )
        planner = self._planner([current, nanally])

        decision = planner.decide_switch(current)

        self.assertEqual(decision.target, nanally)
        self.assertIn("nanally_ultimate", decision.reason)
        self.assertIsNone(decision.expected_entry)

    def test_switch_decision_includes_debug_score_explanation(self):
        current = self._support(0, "current")
        target = self._char(1, "target", tags={ActionTag.SKILL_ACTION})
        planner = self._planner([current, target])

        decision = planner.decide_switch(current)

        self.assertEqual(decision.target, target)
        self.assertEqual(decision.priority, 115)
        self.assertTrue(decision.score_breakdown)

    def test_request_bonus_raises_switch_priority(self):
        source = self._setup_char(0, "source")
        support = self._char(1, "support", tags={ActionTag.SUPPORT})
        baseline = self._planner([source, support]).decide_switch(source)
        planner = self._planner([source, support])
        self._publish(
            planner,
            source,
            lambda context: context.request_tags(
                {ActionTag.SUPPORT},
                reason="needs support",
            ),
        )

        decision = planner.decide_switch(source)

        self.assertEqual(decision.target, support)
        self.assertGreater(decision.priority, baseline.priority)
        self.assertIn("fulfill request", decision.reason)

    def test_stop_on_success_prevents_following_ready_action(self):
        calls = []
        char = FakeChar(
            0,
            "fadia",
            intents=lambda _: [
                self._action(
                    "fadia_ultimate",
                    {ActionTag.ULTIMATE_ACTION},
                    ActionSlot.ULTIMATE,
                    calls,
                    chain_policy=EntryChainPolicy.STOP_ON_SUCCESS,
                ),
                self._action(
                    "fadia_skill",
                    {ActionTag.SKILL_ACTION},
                    ActionSlot.SKILL,
                    calls,
                ),
            ],
        )
        planner = self._planner([char])

        result = planner.perform_current_char(char)

        self.assertEqual(calls, ["fadia_ultimate"])
        self.assertEqual(result.name, "fadia_ultimate")

    def test_stop_on_success_allows_next_action_when_first_fails(self):
        calls = []
        char = FakeChar(
            0,
            "fadia",
            intents=lambda _: [
                self._action(
                    "fadia_ultimate",
                    {ActionTag.ULTIMATE_ACTION},
                    ActionSlot.ULTIMATE,
                    calls,
                    success=False,
                    chain_policy=EntryChainPolicy.STOP_ON_SUCCESS,
                ),
                self._action(
                    "fadia_skill",
                    {ActionTag.SKILL_ACTION},
                    ActionSlot.SKILL,
                    calls,
                ),
            ],
        )
        planner = self._planner([char])

        result = planner.perform_current_char(char)

        self.assertEqual(calls, ["fadia_ultimate", "fadia_skill"])
        self.assertEqual(result.name, "fadia_skill")

    def test_action_result_tags_do_not_control_entry_chain(self):
        calls = []
        char = FakeChar(
            0,
            "chain",
            intents=lambda _: [
                ActionIntent(
                    name="first",
                    tags={ActionTag.SKILL_ACTION},
                    slot=ActionSlot.SKILL,
                    execute=lambda _: calls.append("first")
                    or ActionResult(
                        name="first",
                        success=True,
                        tags={ActionTag.DEFAULT_ACTION},
                        slot=ActionSlot.SKILL,
                    ),
                ),
                self._action(
                    "second",
                    {ActionTag.ULTIMATE_ACTION},
                    ActionSlot.ULTIMATE,
                    calls,
                ),
            ],
        )
        planner = self._planner([char])

        result = planner.perform_current_char(char)

        self.assertEqual(calls, ["first", "second"])
        self.assertEqual(result.name, "second")

    def test_basechar_helpers_are_public_planner_api(self):
        calls = []
        task = FakeTask()
        char = PublicApiChar(
            task,
            0,
            "api_char",
            lambda source, _: source.intents(
                source.click_skill_action(
                    reason="skill first",
                    can_execute=lambda context: calls.append("skill_allowed") or True,
                ),
                source.click_ultimate_action(reason="ultimate second"),
            ),
        )
        task.chars = [char]
        planner = CombatPlanner(task)
        planner.reset([char])

        result = planner.perform_current_char(char)

        self.assertEqual(calls, ["skill_allowed"])
        self.assertEqual(char.skill_clicked, 1)
        self.assertEqual(char.ultimate_clicked, 1)
        self.assertEqual(result.name, "api_char_ultimate")

    def test_basechar_arc_helper_is_zero_priority_arc_slot(self):
        task = FakeTask()
        char = PublicApiChar(
            task,
            0,
            "api_char",
            lambda source, _: source.intents(source.click_arc_action()),
        )
        context = CombatPlanner(task).context_for(char)

        action = char.combat_intents(context)[0]
        result = action.run(context)

        self.assertEqual(action.slot, ActionSlot.ARC)
        self.assertEqual(action.tags, {ActionTag.ARC_ACTION})
        self.assertFalse(action.is_priority_ready(context))
        self.assertTrue(result.success)
        self.assertEqual(result.slot, ActionSlot.ARC)
        self.assertEqual(result.tags, {ActionTag.ARC_ACTION})
        self.assertEqual(char.arc_clicked, 1)

    def test_basechar_click_helpers_run_after_execute_hooks(self):
        calls = []
        task = FakeTask()
        char = PublicApiChar(
            task,
            0,
            "api_char",
            lambda source, _: source.intents(
                source.click_skill_action(
                    reason="skill first",
                    after_execute=lambda context, success: calls.append(
                        ("skill_after", context.current_char.char_name, success)
                    ),
                ),
                source.click_ultimate_action(
                    reason="ultimate second",
                    after_execute=lambda context, success: calls.append(
                        ("ultimate_after", context.current_char.char_name, success)
                    ),
                ),
            ),
        )
        task.chars = [char]
        planner = CombatPlanner(task)
        planner.reset([char])

        result = planner.perform_current_char(char)

        self.assertEqual(
            calls,
            [
                ("skill_after", "api_char", True),
                ("ultimate_after", "api_char", True),
            ],
        )
        self.assertEqual(char.skill_clicked, 1)
        self.assertEqual(char.ultimate_clicked, 1)
        self.assertEqual(result.name, "api_char_ultimate")

    def test_basechar_click_helper_after_execute_can_override_success(self):
        task = FakeTask()
        char = PublicApiChar(
            task,
            0,
            "api_char",
            lambda source, _: source.intents(
                source.click_skill_action(
                    after_execute=lambda context, success: False,
                )
            ),
        )
        task.chars = [char]
        planner = CombatPlanner(task)
        planner.reset([char])

        self.assertFalse(planner.perform_current_char(char).success)
        self.assertEqual(char.skill_clicked, 1)

    def test_basechar_skill_helper_respects_slot_reservation(self):
        expired = {"value": False}
        task = FakeTask()
        source = PublicApiChar(task, 0, "source", lambda source, _: [])
        target = PublicApiChar(
            task,
            1,
            "target",
            lambda source, _: source.intents(source.click_skill_action()),
        )
        task.chars = [source, target]
        planner = CombatPlanner(task)
        planner.reset([source, target])
        self._publish(
            planner,
            source,
            lambda context: context.reserve_actions(
                [ActionReservation.for_action(target, ActionSlot.SKILL)],
                reason="public API slot reservation",
                until=lambda: expired["value"],
            ),
        )

        result = planner.perform_current_char(target)

        self.assertIsNone(result)
        self.assertEqual(target.skill_clicked, 0)

        expired["value"] = True
        planner.state.prune()
        result = planner.perform_current_char(target)

        self.assertEqual(target.skill_clicked, 1)
        self.assertEqual(result.name, "target_skill")

    def test_planner_action_slot_respects_reservation(self):
        expired = {"value": False}
        calls = []
        task = FakeTask()
        source = PublicApiChar(task, 0, "source", lambda source, _: [])
        target = PublicApiChar(
            task,
            1,
            "target",
            lambda source, _: source.intents(
                source.planner_action(
                    tags={ActionTag.DEFAULT_ACTION},
                    slot=ActionSlot.SKILL,
                    execute=lambda _: calls.append("custom_skill") or True,
                    reason="custom skill slot",
                )
            ),
        )
        task.chars = [source, target]
        planner = CombatPlanner(task)
        planner.reset([source, target])
        self._publish(
            planner,
            source,
            lambda context: context.reserve_actions(
                [ActionReservation.for_action(target, ActionSlot.SKILL)],
                reason="slot reservation",
                until=lambda: expired["value"],
            ),
        )

        self.assertIsNone(planner.perform_current_char(target))
        self.assertEqual(calls, [])

        expired["value"] = True
        planner.state.prune()

        self.assertTrue(planner.perform_current_char(target).success)
        self.assertEqual(calls, ["custom_skill"])

    def test_perform_current_char_caches_intents_once_per_loop(self):
        calls = []
        char = FakeChar(
            0,
            "combo",
            intents=lambda _: [
                self._action(
                    "combo_ultimate",
                    {ActionTag.ULTIMATE_ACTION},
                    ActionSlot.ULTIMATE,
                    calls,
                ),
                self._action(
                    "combo_skill",
                    {ActionTag.SKILL_ACTION},
                    ActionSlot.SKILL,
                    calls,
                ),
            ],
        )
        planner = self._planner([char])

        planner.perform_current_char(char)

        self.assertEqual(calls, ["combo_ultimate", "combo_skill"])
        self.assertEqual(char.intent_calls, 3)

    def test_pending_entry_action_runs_before_replanning_field_time(self):
        calls = []
        char = FakeChar(
            0,
            "jiuyuan",
            intents=lambda _: [
                self._action(
                    "jiuyuan_ultimate",
                    {ActionTag.ULTIMATE_ACTION},
                    ActionSlot.ULTIMATE,
                    calls,
                    priority_ready=lambda _: False,
                )
            ],
            max_field_time=1.0,
        )
        planner = self._planner([char])
        planner.expect_entry_action(char, ExpectedEntry(action_name="jiuyuan_ultimate"))

        result = planner.perform_current_char(char)

        self.assertEqual(calls, ["jiuyuan_ultimate"])
        self.assertEqual(result.name, "jiuyuan_ultimate")

    def test_request_tags_selects_matching_teammate(self):
        source = FakeChar(0, "source", field_preference=FieldPreference.SETUP_ONLY)
        support = FakeChar(1, "support", tags={ActionTag.SUPPORT})
        dps = FakeChar(2, "dps", tags={ActionTag.DAMAGE})
        planner = self._planner([source, support, dps])
        self._publish(
            planner,
            source,
            lambda context: context.request_tags(
                {ActionTag.SUPPORT},
                reason="needs support",
            ),
        )

        decision = planner.decide_switch(source)

        self.assertEqual(decision.target, support)
        self.assertIn("needs support", decision.reason)

    def test_request_tags_can_return_to_source_after_completion(self):
        source = FakeChar(0, "source", tags={ActionTag.ULTIMATE_ACTION})
        recorder = FakeChar(1, "recorder", tags={ActionTag.SKILL_ACTION})
        planner = self._planner([source, recorder])
        self._publish(
            planner,
            source,
            lambda context: context.request_tags(
                {ActionTag.SKILL_ACTION},
                reason="record skill",
                return_to_source=True,
            ),
        )

        planner.perform_current_char(recorder)
        decision = planner.decide_switch(recorder)

        self.assertEqual(decision.target, source)
        self.assertIn("return to requester", decision.reason)

        planner.perform_current_char(source)

        self.assertEqual(planner.state.active_requests, [])

    def test_request_route_forces_declared_switch_order(self):
        hotori = FakeChar(0, "hotori", field_preference=FieldPreference.SETUP_ONLY)
        jiuyuan = FakeChar(1, "jiuyuan", tags={ActionTag.SKILL_ACTION})
        zero = FakeChar(2, "zero", tags={ActionTag.SKILL_ACTION})
        planner = self._planner([hotori, jiuyuan, zero])
        self._publish(
            planner,
            hotori,
            lambda context: context.request_route(
                [
                    FollowupStep.for_action(jiuyuan, ActionSlot.SKILL, reason="Jiuyuan E"),
                    FollowupStep.for_action(zero, ActionSlot.SKILL, reason="Zero E"),
                ],
                reason="hotori record route",
            ),
        )

        decision = planner.decide_switch(hotori)

        self.assertEqual(decision.target, jiuyuan)

        planner.perform_current_char(jiuyuan)
        decision = planner.decide_switch(jiuyuan)

        self.assertEqual(decision.target, zero)

    def test_request_route_chains_same_target_steps_in_one_entry(self):
        calls = []
        char = FakeChar(
            1,
            "jiuyuan",
            intents=lambda _: [
                self._action(
                    "jiuyuan_ultimate",
                    {ActionTag.ULTIMATE_ACTION},
                    ActionSlot.ULTIMATE,
                    calls,
                ),
                self._action(
                    "jiuyuan_skill",
                    {ActionTag.SKILL_ACTION},
                    ActionSlot.SKILL,
                    calls,
                ),
            ],
        )
        planner = self._planner([char])
        self._publish(
            planner,
            char,
            lambda context: context.request_route(
                [
                    FollowupStep.for_action(char, ActionSlot.ULTIMATE, reason="Q"),
                    FollowupStep.for_action(char, ActionSlot.SKILL, reason="E"),
                ],
                reason="same target route",
            ),
        )

        result = planner.perform_current_char(char)

        self.assertEqual(calls, ["jiuyuan_ultimate", "jiuyuan_skill"])
        self.assertEqual(result.name, "jiuyuan_skill")

    def test_request_route_skips_optional_prepare_step_when_not_ready(self):
        calls = []
        char = FakeChar(
            1,
            "zero",
            intents=lambda _: [
                self._action(
                    "zero_ultimate",
                    {ActionTag.ULTIMATE_ACTION},
                    ActionSlot.ULTIMATE,
                    calls,
                    priority_ready=lambda _: False,
                ),
                self._action(
                    "zero_skill",
                    {ActionTag.SKILL_ACTION},
                    ActionSlot.SKILL,
                    calls,
                ),
            ],
        )
        planner = self._planner([char])
        self._publish(
            planner,
            char,
            lambda context: context.request_route(
                [
                    FollowupStep.for_action(
                        char,
                        ActionSlot.ULTIMATE,
                        reason="Q if ready",
                        optional=True,
                    ),
                    FollowupStep.for_action(char, ActionSlot.SKILL, reason="E"),
                ],
                reason="optional prepare route",
            ),
        )

        result = planner.perform_current_char(char)

        self.assertEqual(calls, ["zero_skill"])
        self.assertEqual(result.name, "zero_skill")

    def test_request_route_skips_failed_optional_prepare_step(self):
        calls = []
        char = FakeChar(
            1,
            "zero",
            intents=lambda _: [
                self._action(
                    "zero_ultimate",
                    {ActionTag.ULTIMATE_ACTION},
                    ActionSlot.ULTIMATE,
                    calls,
                    success=False,
                ),
                self._action(
                    "zero_skill",
                    {ActionTag.SKILL_ACTION},
                    ActionSlot.SKILL,
                    calls,
                ),
            ],
        )
        planner = self._planner([char])
        self._publish(
            planner,
            char,
            lambda context: context.request_route(
                [
                    FollowupStep.for_action(
                        char,
                        ActionSlot.ULTIMATE,
                        reason="Q if ready",
                        optional=True,
                    ),
                    FollowupStep.for_action(char, ActionSlot.SKILL, reason="E"),
                ],
                reason="optional prepare route",
            ),
        )

        result = planner.perform_current_char(char)

        self.assertEqual(calls, ["zero_ultimate", "zero_skill"])
        self.assertEqual(result.name, "zero_skill")
        self.assertIsNone(planner.state.locked_route)

    def test_request_route_no_longer_accepts_holds(self):
        hotori = FakeChar(0, "hotori", field_preference=FieldPreference.SETUP_ONLY)
        zero = FakeChar(1, "zero", tags={ActionTag.SKILL_ACTION})
        nanally = FakeChar(2, "nanally")
        planner = self._planner([hotori, zero, nanally])

        with self.assertRaises(TypeError):
            self._publish(
                planner,
                hotori,
                lambda context: context.request_route(
                    [FollowupStep.for_action(zero, ActionSlot.SKILL, reason="Zero E")],
                    reason="hotori record route",
                    holds=[ActionReservation.for_action(nanally, ActionSlot.SKILL)],
                ),
            )

    def test_combat_policies_publish_long_lived_reservation_on_reset(self):
        target = FakeChar(1, "target")
        source = FakeChar(
            0,
            "source",
            policies=lambda context: context.reserve_actions(
                [ActionReservation.for_action(target, ActionSlot.SKILL)],
                reason="policy reservation",
                until=NEVER_EXPIRES,
            ),
        )

        planner = self._planner([source, target])
        context = planner.context_for(source)

        self.assertFalse(context.can_execute_action(target, slot=ActionSlot.SKILL))

    def test_combat_intents_published_requests_are_ignored(self):
        target = FakeChar(1, "target")
        source = FakeChar(
            0,
            "source",
            intents=lambda context: (
                context.reserve_actions(
                    [ActionReservation.for_action(target, ActionSlot.SKILL)],
                    reason="invalid intent side effect",
                    until=NEVER_EXPIRES,
                )
                or []
            ),
        )

        planner = self._planner([source, target])
        planner.decide_switch(source)
        context = planner.context_for(source)

        self.assertTrue(context.can_execute_action(target, slot=ActionSlot.SKILL))

    def test_reserve_actions_blocks_until_condition_releases(self):
        source = FakeChar(0, "source")
        nanally = FakeChar(1, "nanally")
        expired = {"value": False}
        planner = self._planner([source, nanally])
        self._publish(
            planner,
            source,
            lambda context: context.reserve_actions(
                [ActionReservation.for_action(nanally, ActionSlot.SKILL)],
                reason="hold Nanally E",
                until=lambda: expired["value"],
            ),
        )
        context = planner.context_for(source)

        self.assertFalse(context.can_execute_action(nanally, slot=ActionSlot.SKILL))

        expired["value"] = True
        planner.state.prune()

        self.assertTrue(context.can_execute_action(nanally, slot=ActionSlot.SKILL))

    def test_reserve_actions_requires_explicit_lifetime(self):
        source = FakeChar(0, "source")
        nanally = FakeChar(1, "nanally")
        planner = self._planner([source, nanally])

        with self.assertRaises(TypeError):
            self._publish(
                planner,
                source,
                lambda context: context.reserve_actions(
                    [ActionReservation.for_action(nanally, ActionSlot.SKILL)],
                    reason="missing lifetime",
                ),
            )

    def test_permanent_reservation_rejects_on_expired_callback(self):
        source = FakeChar(0, "source")
        nanally = FakeChar(1, "nanally")
        planner = self._planner([source, nanally])

        with self.assertRaises(ValueError):
            self._publish(
                planner,
                source,
                lambda context: context.reserve_actions(
                    [ActionReservation.for_action(nanally, ActionSlot.SKILL)],
                    reason="bad permanent reservation",
                    until=NEVER_EXPIRES,
                    on_expired=lambda: None,
                ),
            )

    def test_reserve_actions_supports_never_expires(self):
        source = FakeChar(0, "source")
        nanally = FakeChar(1, "nanally")
        planner = self._planner([source, nanally])
        self._publish(
            planner,
            source,
            lambda context: context.reserve_actions(
                [ActionReservation.for_action(nanally, ActionSlot.SKILL)],
                reason="permanent hold",
                until=NEVER_EXPIRES,
            ),
        )

        planner.state.prune()
        context = planner.context_for(source)

        self.assertFalse(context.can_execute_action(nanally, slot=ActionSlot.SKILL))

    def test_request_route_window_hold_survives_route_completion_until_window_expires(self):
        hotori = FakeChar(0, "hotori", field_preference=FieldPreference.SETUP_ONLY)
        zero = FakeChar(1, "zero", tags={ActionTag.SKILL_ACTION})
        nanally = FakeChar(2, "nanally")
        expired = {"value": False}
        planner = self._planner([hotori, zero, nanally])
        self._publish(
            planner,
            hotori,
            lambda context: context.request_route_window(
                [FollowupStep.for_action(zero, ActionSlot.SKILL, reason="Zero E")],
                [ActionReservation.for_action(nanally, ActionSlot.SKILL)],
                reason="hotori record window",
                until=lambda: expired["value"],
            ),
        )
        context = planner.context_for(hotori)

        planner.perform_current_char(zero)

        self.assertIsNone(planner.state.locked_route)
        self.assertFalse(context.can_execute_action(nanally, slot=ActionSlot.SKILL))

        expired["value"] = True
        planner.state.prune()

        self.assertTrue(context.can_execute_action(nanally, slot=ActionSlot.SKILL))

    def test_request_route_window_requires_until(self):
        hotori = FakeChar(0, "hotori", field_preference=FieldPreference.SETUP_ONLY)
        zero = FakeChar(1, "zero", tags={ActionTag.SKILL_ACTION})
        nanally = FakeChar(2, "nanally")
        planner = self._planner([hotori, zero, nanally])

        with self.assertRaises(TypeError):
            self._publish(
                planner,
                hotori,
                lambda context: context.request_route_window(
                    [FollowupStep.for_action(zero, ActionSlot.SKILL, reason="Zero E")],
                    [ActionReservation.for_action(nanally, ActionSlot.SKILL)],
                    reason="hotori record window",
                ),
            )

    def test_request_route_can_request_entry_reaction(self):
        zero = FakeChar(0, "zero", cycle_full=True)
        nanally = FakeChar(1, "nanally")
        planner = self._planner([zero, nanally])
        self._publish(
            planner,
            zero,
            lambda context: context.request_route(
                [
                    FollowupStep.for_entry_reaction(
                        nanally,
                        reason="Nanally entry reaction",
                    )
                ],
                reason="entry reaction route",
            ),
        )

        decision = planner.decide_switch(zero)

        self.assertEqual(decision.target, nanally)
        self.assertIn("entry reaction", decision.reason)

        planner.record_entry_reaction(zero, nanally)

        self.assertIsNone(planner.state.locked_route)

    def test_request_switch_prefers_target_without_expected_action(self):
        source = FakeChar(0, "source")
        zero = FakeChar(1, "zero")
        dps = FakeChar(2, "dps", field_preference=FieldPreference.MAIN_DPS)
        planner = self._planner([source, zero, dps])
        self._publish(
            planner,
            source,
            lambda context: context.request_switch(
                zero,
                reason="return Zero after Hotori",
            ),
        )

        decision = planner.decide_switch(source)

        self.assertEqual(decision.target, zero)
        self.assertIsNone(decision.expected_entry)
        self.assertIn("switch request", decision.reason)

    def test_request_switch_does_not_stop_current_entry_chain(self):
        calls = []
        source = PublicApiChar(
            FakeTask(),
            0,
            "source",
            lambda char, context: char.intents(
                char.planner_action(
                    tags={ActionTag.DEFAULT_ACTION},
                    execute=lambda ctx: (
                        calls.append("request")
                        or ctx.request_switch(target, reason="switch after chain")
                        or True
                    ),
                    reason="publish switch request",
                ),
                char.planner_action(
                    tags={ActionTag.DEFAULT_ACTION},
                    execute=lambda _: calls.append("second") or True,
                    reason="continue current chain",
                ),
            ),
        )
        target = FakeChar(1, "target")
        task = source.task
        task.chars = [source, target]
        planner = CombatPlanner(task)
        planner.reset(task.chars)

        planner.perform_current_char(source)

        self.assertEqual(calls, ["request", "second"])

    def test_request_switch_waits_when_strict_route_preempts_it(self):
        source = FakeChar(0, "source")
        zero = FakeChar(1, "zero")
        jiuyuan = FakeChar(2, "jiuyuan", tags={ActionTag.SKILL_ACTION})
        planner = self._planner([source, zero, jiuyuan])
        self._publish(
            planner,
            source,
            lambda context: context.request_switch(
                zero,
                reason="switch to Zero after hard route",
            ),
        )
        self._publish(
            planner,
            source,
            lambda context: context.request_route(
                [FollowupStep.for_action(jiuyuan, ActionSlot.SKILL, reason="Jiuyuan E")],
                reason="hard route",
            ),
        )

        first_decision = planner.decide_switch(source)
        self.assertEqual(first_decision.target, jiuyuan)

        planner.perform_current_char(jiuyuan)
        second_decision = planner.decide_switch(jiuyuan)

        self.assertEqual(second_decision.target, zero)
        self.assertIn("switch request", second_decision.reason)

    def test_record_switch_consumes_matching_switch_request(self):
        source = FakeChar(0, "source")
        zero = FakeChar(1, "zero")
        planner = self._planner([source, zero])
        self._publish(
            planner,
            source,
            lambda context: context.request_switch(zero, reason="one shot switch"),
        )

        planner.record_switch(zero)
        decision = planner.decide_switch(source)

        self.assertNotIn("switch request", decision.reason)

    def test_strict_route_wants_action_query_supports_slots(self):
        source = FakeChar(0, "source")
        zero = FakeChar(1, "zero")
        planner = self._planner([source, zero])
        self._publish(
            planner,
            source,
            lambda context: context.request_route(
                [FollowupStep.for_action(zero, ActionSlot.SKILL, reason="Zero E")],
                reason="zero skill route",
            ),
        )
        context = planner.context_for(zero)

        self.assertTrue(context.strict_route_wants_action(zero, slot=ActionSlot.SKILL))
        self.assertFalse(context.strict_route_wants_action(zero, slot=ActionSlot.ULTIMATE))

    def test_has_strict_route_only_reports_locked_route(self):
        source = FakeChar(0, "source")
        zero = FakeChar(1, "zero")
        planner = self._planner([source, zero])
        context = planner.context_for(zero)
        self._publish(
            planner,
            source,
            lambda context: context.request_tags(
                {ActionTag.SUPPORT},
                reason="needs support",
            ),
        )

        self.assertTrue(context.has_active_request())
        self.assertFalse(context.has_strict_route())

        self._publish(
            planner,
            source,
            lambda context: context.request_route(
                [FollowupStep.for_action(zero, ActionSlot.SKILL, reason="Zero E")],
                reason="zero skill route",
            ),
        )

        self.assertTrue(context.has_strict_route())
        self.assertTrue(planner.has_strict_route(zero))

    def test_switch_in_guard_is_exposed_through_planner(self):
        waiting_calls = []
        current = FakeChar(0, "current")
        target = FakeChar(
            1,
            "target",
            switch_in_guard=lambda *_: SwitchInGuard.delay_until_ready(
                lambda: False,
                timeout=0.2,
                reason="wait target entry",
                while_waiting=lambda: waiting_calls.append("wait"),
            ),
        )
        planner = self._planner([current, target])

        guard = planner.switch_in_guard(current, target, has_intro=True)

        self.assertTrue(guard.should_delay())
        self.assertEqual(guard.reason, "wait target entry")
        self.assertIsNotNone(guard.while_waiting)
        guard.while_waiting()
        self.assertEqual(waiting_calls, ["wait"])

    def test_switch_in_guard_belongs_to_target_char(self):
        calls = []
        current = FakeChar(0, "current")
        target = FakeChar(
            1,
            "target",
            switch_in_guard=lambda context, from_char, has_intro: calls.append(
                (context.current_char, from_char, has_intro)
            )
            or SwitchInGuard.allow(),
        )
        planner = self._planner([current, target])

        guard = planner.switch_in_guard(current, target, has_intro=True)

        self.assertFalse(guard.should_delay())
        self.assertEqual(calls, [(target, current, True)])

    def test_core_does_not_use_active_requests_as_boolean_gate(self):
        core_path = Path("src/combat/planner/core.py")
        source = core_path.read_text(encoding="utf-8")

        self.assertNotIn("if self.state.active_requests:", source)
        self.assertNotIn("if context._state.active_requests:", source)

    def test_characters_do_not_read_planner_internal_state(self):
        forbidden = [
            "context.state",
            "context._state",
            ".locked_route",
            ".active_requests",
            "src.combat.planner.requests",
            "src.combat.planner.state",
        ]
        offenders = []
        for path in Path("src/char").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for pattern in forbidden:
                if pattern in source:
                    offenders.append(f"{path}:{pattern}")

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
