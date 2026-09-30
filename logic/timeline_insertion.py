"""Place only newly created AF entities at the requested insertion point.

Called within the create command transaction. A failure must propagate to
executeFailed so Fusion aborts the entire creation, including support planes.
"""


class TimelineInsertionError(RuntimeError):
    pass


class TimelineInsertion:
    def __init__(self, timeline, planes):
        self.timeline = timeline
        self.position = timeline.markerPosition
        # Keep object identities, not mutable indices or entity token strings.
        self.existing_planes = [planes.item(i) for i in range(planes.count)]
        self.created_planes = []

    def place_new_planes(self, planes):
        created = [planes.item(i) for i in range(planes.count)]
        created = [p for p in created if not any(p == old for old in self.existing_planes)]
        for plane in sorted(created, key=lambda p: p.timelineObject.index):
            self.place(plane, 'support plane')
            self.created_planes.append(plane)
        self.existing_planes.extend(created)

    def place(self, entity, stage, position=None):
        target = self.position if position is None else position
        item = entity.timelineObject
        actual = item.index
        if actual != target:
            # Only move new entities backwards to the requested position.
            # Never move existing history or bypass a dependency restriction.
            if actual < target or not item.canReorder(target) or not item.reorder(target):
                raise TimelineInsertionError(
                    f'Cannot insert AirfoilSpline {stage} at timeline position {target} '
                    f'(Fusion created it at {actual}). Creation will be cancelled; '
                    'check whether its references require a later timeline position.')
            if item.index != target:
                raise TimelineInsertionError(
                    f'Fusion did not place the AirfoilSpline {stage} at the requested '
                    f'timeline position {target}; actual position is {item.index}.')
        if self.timeline.markerPosition != target + 1:
            if not item.rollTo(False) or self.timeline.markerPosition != target + 1:
                raise TimelineInsertionError('Cannot advance the timeline after the new AirfoilSpline ' + stage)
        self.position = target + 1
        return target
