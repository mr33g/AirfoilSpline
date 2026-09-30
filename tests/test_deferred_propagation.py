"""Event/transaction guards for the experimental probe, not Fusion kernel tests."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch


class Point:
    def __init__(self, x):
        self.x, self.y, self.z = x, 0, 0

    def distanceTo(self, other):
        return abs(self.x - other.x)


class DeferredPropagationTests(unittest.TestCase):
    def setUp(self):
        adsk = ModuleType('adsk')
        adsk.core = ModuleType('adsk.core')
        adsk.fusion = ModuleType('adsk.fusion')
        for name in ('CommandCreatedEventHandler', 'CommandEventHandler',
                     'ApplicationCommandEventHandler', 'CustomEventHandler'):
            setattr(adsk.core, name, type(name, (), {}))
        adsk.fusion.CustomFeatureEventHandler = type('CustomFeatureEventHandler', (), {})
        self.command = NS(execute=Mock(return_value=True))
        self.app = NS(fireCustomEvent=Mock(return_value=True), userInterface=NS(
            activeCommand='SelectCommand', commandDefinitions=NS(itemById=lambda _: self.command)))
        adsk.core.Application = NS(get=lambda: self.app)
        path = Path(__file__).parent / 'fusion/DeferredSketchPropagation/DeferredSketchPropagation.py'
        spec = importlib.util.spec_from_file_location('deferred_probe_test', path)
        self.m = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'adsk': adsk, 'adsk.core': adsk.core, 'adsk.fusion': adsk.fusion}):
            spec.loader.exec_module(self.m)
        self.m._report = {'events': []}
        self.m._ready = True
        self.m.active_test = lambda: True
        self.m.write_report = Mock()
        self.timeline = NS(markerPosition=20)
        self.m._design = NS(timeline=self.timeline)
        self.m.output = Mock(return_value=NS(revisionId='old', sketchCurves=NS(
            item=lambda _: NS(geometry=NS(startPoint=Point(0), endPoint=Point(10))))))
        self.m.replace = Mock()

    def feature(self, name='A', index=2, length=12):
        def roll(before):
            self.timeline.markerPosition = index + 1
            return True
        chord = NS(startSketchPoint=NS(geometry=Point(0)), endSketchPoint=NS(geometry=Point(length)))
        return NS(name=name, isValid=True, timelineObject=NS(index=index, rollTo=Mock(side_effect=roll)),
                  dependencies=NS(itemById=lambda _: NS(entity=chord)))

    def test_callback_queues_without_mutation_and_deduplicates(self):
        f = self.feature()
        args = NS(customFeature=f)
        self.m.Compute().notify(args)
        self.m.Compute().notify(args)
        self.assertEqual(list(self.m._pending), ['A'])
        self.m.replace.assert_not_called()
        f.timelineObject.rollTo.assert_not_called()
        self.app.fireCustomEvent.assert_not_called()

    def test_noop_refresh_and_history_callbacks_do_not_queue(self):
        for replay, refreshing, length in ((False, False, 10), (True, False, 12), (False, True, 12)):
            with self.subTest(replay=replay, refreshing=refreshing, length=length):
                self.m._history_replay, self.m._refreshing = replay, refreshing
                self.m.Compute().notify(NS(customFeature=self.feature(length=length)))
                self.assertFalse(self.m._pending)

    def test_schedule_is_coalesced_and_does_not_interrupt_active_command(self):
        self.m._pending['A'] = self.feature()
        self.m.request_refresh()
        self.m.request_refresh()
        self.app.fireCustomEvent.assert_called_once()
        self.app.userInterface.activeCommand = 'SketchEdit'
        self.m.Dispatch().notify(None)
        self.command.execute.assert_not_called()
        self.assertTrue(self.m._pending)
        self.app.userInterface.activeCommand = 'SelectCommand'
        self.m.Dispatch().notify(None)
        self.command.execute.assert_called_once()

    def test_dispatch_does_not_touch_other_document_or_rolled_back_feature(self):
        self.m._pending['A'] = self.feature()
        self.m.active_test = lambda: False
        self.m.Dispatch().notify(None)
        self.command.execute.assert_not_called()
        self.m.active_test = lambda: True
        self.timeline.markerPosition = 1
        self.m.Dispatch().notify(None)
        self.command.execute.assert_not_called()
        self.assertFalse(self.m._pending)

    def test_refresh_orders_features_and_restores_marker(self):
        a, b = self.feature('A', 2), self.feature('B', 8)
        self.m._pending.update(B=b, A=a)
        args = NS(executeFailed=False)
        self.m.Execute('refresh').notify(args)
        self.assertFalse(args.executeFailed)
        self.assertEqual([e['feature'] for e in self.m._report['events']], ['A', 'B'])
        self.assertEqual(self.timeline.markerPosition, 20)
        self.assertFalse(self.m._refreshing)
        self.assertFalse(self.m._pending)
        self.assertEqual(self.m.replace.call_count, 2)

    def test_failed_refresh_restores_marker_and_does_not_retry(self):
        self.m._pending['A'] = self.feature()
        self.m.replace.side_effect = RuntimeError('replacement failed')
        args = NS(executeFailed=False)
        self.m.Execute('refresh').notify(args)
        self.assertTrue(args.executeFailed)
        self.assertEqual(self.timeline.markerPosition, 20)
        self.assertFalse(self.m._refreshing)
        self.assertFalse(self.m._pending)

    def test_undo_cancels_already_queued_refresh(self):
        self.m._pending['A'] = self.feature()
        self.m.request_refresh()
        self.m.Starting().notify(NS(commandId='UndoCommand'))
        self.m.Dispatch().notify(None)
        self.command.execute.assert_not_called()
        self.assertTrue(self.m._history_replay)

    def test_nested_environment_events_do_not_release_undo_guard(self):
        self.m.Starting().notify(NS(commandId='UndoCommand'))
        self.m.Starting().notify(NS(commandId='ActivateEnvironmentCommand'))
        self.m.Terminated().notify(NS(commandId='ActivateEnvironmentCommand'))
        self.assertTrue(self.m._history_replay)
        self.m.Compute().notify(NS(customFeature=self.feature()))
        self.assertFalse(self.m._pending)
        self.m.Terminated().notify(NS(commandId='UndoCommand'))
        self.assertFalse(self.m._history_replay)

    def test_false_queue_return_does_not_prevent_subsequent_delivery(self):
        self.m._pending['A'] = self.feature()
        self.app.fireCustomEvent.return_value = False
        self.m.request_refresh()
        self.m.Dispatch().notify(None)
        self.command.execute.assert_called_once()
        self.assertEqual([e['kind'] for e in self.m._report['events']],
                         ['dispatch-request', 'dispatch-delivered'])


if __name__ == '__main__':
    unittest.main()
