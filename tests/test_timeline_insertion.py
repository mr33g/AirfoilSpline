"""Insertion policy tests; Fusion's actual reorder/rollback needs a live test."""
from types import SimpleNamespace as NS
from unittest.mock import Mock
import unittest
from logic.timeline_insertion import TimelineInsertion, TimelineInsertionError


class Collection:
    def __init__(self, items):
        self.items = items

    @property
    def count(self):
        return len(self.items)

    def item(self, index):
        return self.items[index]


class InsertionTests(unittest.TestCase):
    def setUp(self):
        self.timeline = NS(markerPosition=3)

    def entity(self, index, permitted=True):
        item = NS(index=index, canReorder=Mock(return_value=permitted))
        def reorder(target):
            item.index = target
            return True
        def roll(before):
            self.timeline.markerPosition = item.index + 1
            return True
        item.reorder = Mock(side_effect=reorder)
        item.rollTo = Mock(side_effect=roll)
        return NS(timelineObject=item)

    def test_late_sketch_moves_to_requested_position(self):
        insertion = TimelineInsertion(self.timeline, Collection([]))
        sketch = self.entity(40)
        insertion.place(sketch, 'output sketch')
        sketch.timelineObject.canReorder.assert_called_once_with(3)
        sketch.timelineObject.reorder.assert_called_once_with(3)
        self.assertEqual(self.timeline.markerPosition, 4)

    def test_existing_planes_never_move_and_new_supports_stay_ordered(self):
        old = self.entity(30)
        planes = Collection([old])
        insertion = TimelineInsertion(self.timeline, planes)
        first, second = self.entity(40), self.entity(41)
        planes.items.extend([second, first])
        insertion.place_new_planes(planes)
        old.timelineObject.reorder.assert_not_called()
        self.assertEqual((first.timelineObject.index, second.timelineObject.index), (3, 4))
        insertion.place_new_planes(planes)
        self.assertEqual(first.timelineObject.reorder.call_count, 1)
        self.assertEqual(insertion.created_planes, [first, second])
        sketch = self.entity(42)
        self.assertEqual(insertion.place(sketch, 'output sketch'), 5)

    def test_dependency_rejection_stops_without_reorder(self):
        insertion = TimelineInsertion(self.timeline, Collection([]))
        sketch = self.entity(40, permitted=False)
        with self.assertRaisesRegex(TimelineInsertionError, 'Fusion created it at 40'):
            insertion.place(sketch, 'output sketch')
        sketch.timelineObject.reorder.assert_not_called()

    def test_successful_api_return_still_requires_correct_position(self):
        insertion = TimelineInsertion(self.timeline, Collection([]))
        sketch = self.entity(40)
        sketch.timelineObject.reorder.side_effect = None
        sketch.timelineObject.reorder.return_value = True
        with self.assertRaisesRegex(TimelineInsertionError, 'actual position is 40'):
            insertion.place(sketch, 'output sketch')

    def test_correct_position_does_not_reorder(self):
        insertion = TimelineInsertion(self.timeline, Collection([]))
        sketch = self.entity(3)
        self.timeline.markerPosition = 4
        insertion.place(sketch, 'output sketch')
        sketch.timelineObject.reorder.assert_not_called()
        sketch.timelineObject.rollTo.assert_not_called()

    def test_feature_reuses_output_slot(self):
        insertion = TimelineInsertion(self.timeline, Collection([]))
        slot = insertion.place(self.entity(3), 'output sketch')
        feature = self.entity(40)
        insertion.place(feature, 'feature', position=slot)
        feature.timelineObject.reorder.assert_called_once_with(3)

    def test_unrepresented_item_is_rejected(self):
        insertion = TimelineInsertion(self.timeline, Collection([]))
        with self.assertRaises(TimelineInsertionError):
            insertion.place(self.entity(-1), 'output sketch')


if __name__ == '__main__':
    unittest.main()
