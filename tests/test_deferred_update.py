"""Offline transaction guards for AF's deferred updater; no Fusion kernel."""
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock
from test_custom_feature import api_stub, load


class DeferredUpdateTests(unittest.TestCase):
    def setUp(self):
        adsk = api_stub()
        adsk.core.CustomEventHandler = type('CustomEventHandler', (), {})
        self.design = NS(timeline=NS(markerPosition=20))
        self.app = NS(activeProduct=self.design, fireCustomEvent=Mock(return_value=True),
                      userInterface=NS(activeCommand='SelectCommand'), log=Mock())
        adsk.core.Application = NS(get=lambda: self.app)
        adsk.fusion.Design = NS(cast=lambda p: p)
        self.m = load('af_deferred_test', 'logic/deferred_update.py',
                      {'adsk': adsk, 'adsk.core': adsk.core, 'adsk.fusion': adsk.fusion})
        self.update = Mock(return_value=True)
        self.busy = set()
        self.owner = self.m.DeferredUpdates(self.update, self.busy, lambda f: f)
        self.owner.command = NS(execute=Mock(return_value=True))

    def feature(self, name='A', index=2):
        def roll(before):
            self.design.timeline.markerPosition = index + 1
            return True
        return NS(name=name, entityToken=name, isValid=True,
                  parentComponent=NS(parentDesign=self.design),
                  timelineObject=NS(index=index, rollTo=Mock(side_effect=roll)))

    def test_batch_deduplicates_orders_and_restores_timeline(self):
        a, b = self.feature(), self.feature('B', 8)
        for f in (b, a, a):
            self.owner.queue(f)
        self.owner.execute()
        self.assertEqual([c.args[0].name for c in self.update.call_args_list], ['A', 'B', 'A', 'B'])
        self.assertEqual(self.design.timeline.markerPosition, 20)
        self.assertFalse(self.busy)
        self.assertFalse(self.owner.pending)

    def test_noop_does_not_roll_or_write(self):
        f = self.feature()
        self.owner.queue(f)
        self.update.return_value = False
        self.owner.execute()
        self.update.assert_called_once_with(f, apply=False)
        f.timelineObject.rollTo.assert_not_called()

    def test_failure_restores_marker_and_busy_without_retry(self):
        self.owner.queue(self.feature())
        self.busy.add('unrelated')
        self.update.side_effect = [True, RuntimeError('replacement failed')]
        args = NS(executeFailed=False)
        self.m.Execute(self.owner).notify(args)
        self.assertTrue(args.executeFailed)
        self.assertEqual(self.design.timeline.markerPosition, 20)
        self.assertEqual(self.busy, {'unrelated'})
        self.assertFalse(self.owner.running)
        self.assertFalse(self.owner.pending)

    def test_other_document_and_rolled_back_features_are_not_updated(self):
        a, b = self.feature(), self.feature('B', 21)
        a.parentComponent.parentDesign = object()
        self.owner.queue(a)
        self.owner.queue(b)
        self.owner.execute()
        self.update.assert_not_called()
        self.assertEqual(self.owner.pending, [a])

    def test_dispatch_waits_for_idle_and_false_event_return_can_deliver(self):
        self.owner.queue(self.feature())
        self.app.fireCustomEvent.return_value = False
        self.owner.request()
        self.assertFalse(self.owner.queued)
        self.app.userInterface.activeCommand = 'SketchEdit'
        self.m.Dispatch(self.owner).notify(None)
        self.owner.command.execute.assert_not_called()
        self.app.userInterface.activeCommand = 'SelectCommand'
        self.m.Dispatch(self.owner).notify(None)
        self.owner.command.execute.assert_called_once()
        self.app.log.assert_not_called()

    def test_nested_history_commands_keep_guard(self):
        self.owner.queue(self.feature())
        self.m.Starting(self.owner).notify(NS(commandId='UndoCommand'))
        self.m.Starting(self.owner).notify(NS(commandId='ActivateEnvironmentCommand'))
        self.m.Terminated(self.owner).notify(NS(commandId='ActivateEnvironmentCommand'))
        self.owner.queue(self.feature())
        self.assertTrue(self.owner.history_replay)
        self.assertFalse(self.owner.pending)
        self.app.fireCustomEvent.assert_not_called()
        self.m.Terminated(self.owner).notify(NS(commandId='UndoCommand'))
        self.assertFalse(self.owner.history_replay)

    def test_stopped_dispatch_does_nothing(self):
        self.owner.stopped = True
        self.owner.queue(self.feature())
        self.m.Dispatch(self.owner).notify(None)
        self.owner.command.execute.assert_not_called()
        self.assertFalse(self.owner.pending)
