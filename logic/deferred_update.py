"""Experimental targeted AF updates in ordinary Fusion command transactions."""
import traceback

import adsk.core
import adsk.fusion

COMMAND_ID = 'AirfoilSplinesRefreshChangedFeatures'
EVENT_ID = 'AirfoilSplinesDispatchChangedFeatures'


def is_history(command_id):
    return 'undo' in command_id.lower() or 'redo' in command_id.lower()


class DeferredUpdates:
    def __init__(self, update, busy, native):
        self.update = update
        self.busy = busy
        self.native = native
        self.pending = []
        self.handlers = []
        self.event = None
        self.command = None
        self.queued = False
        self.running = False
        self.stopped = False
        self.history_replay = False

    def attach(self, event, handler):
        event.add(handler)
        self.handlers.append((event, handler))

    def start(self):
        app = adsk.core.Application.get()
        ui = app.userInterface
        self.command = ui.commandDefinitions.itemById(COMMAND_ID)
        if not self.command:
            self.command = ui.commandDefinitions.addButtonDefinition(
                COMMAND_ID, 'Refresh changed AirfoilSplines features', 'Apply queued airfoil updates')
        self.attach(self.command.commandCreated, Created(self))
        self.event = app.registerCustomEvent(EVENT_ID)
        if not self.event:
            raise RuntimeError('Cannot register the AirfoilSplines deferred update event.')
        self.attach(self.event, Dispatch(self))
        self.attach(ui.commandStarting, Starting(self))
        self.attach(ui.commandTerminated, Terminated(self))

    def stop(self):
        self.stopped = True
        self.pending.clear()
        self.queued = False
        for event, handler in reversed(self.handlers):
            try:
                event.remove(handler)
            except Exception:
                pass  # Completed command event owners may no longer exist.
        self.handlers.clear()
        app = adsk.core.Application.get()
        if self.event is not None:
            app.unregisterCustomEvent(EVENT_ID)
            self.event = None
        if self.command and self.command.isValid:
            self.command.deleteMe()
        self.command = None

    def queue(self, feature):
        if self.stopped or self.history_replay:
            return
        feature = self.native(feature)
        if not any(item == feature for item in self.pending):
            self.pending.append(feature)

    def active_batch(self):
        design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
        batch = []
        keep = []
        for feature in self.pending:
            try:
                if not feature.isValid:
                    continue
                if feature.parentComponent.parentDesign != design:
                    keep.append(feature)
                elif feature.timelineObject.index < design.timeline.markerPosition:
                    batch.append(feature)
                # Rolled-back features are not edited. A subsequent evaluation
                # can queue them again when the user rolls history forward.
            except Exception:
                continue  # Deleted feature or closed document.
        self.pending = keep + batch
        return design, sorted(batch, key=lambda f: f.timelineObject.index)

    def request(self):
        if self.stopped or self.running or self.history_replay or self.queued:
            return
        _, batch = self.active_batch()
        if not batch:
            return
        self.queued = True
        try:
            result = adsk.core.Application.get().fireCustomEvent(EVENT_ID, 'refresh')
        except Exception:
            self.queued = False
            raise
        # The live probe observed event delivery even after a false return.
        # Do not log a failure solely from this value; allow a later retry.
        if not result:
            self.queued = False

    def execute(self):
        if self.stopped or self.running or self.history_replay:
            return
        design, batch = self.active_batch()
        self.pending = [f for f in self.pending if f not in batch]
        # Inspect outputs before rolling history: later outputs may be
        # unavailable while the marker is positioned at an earlier feature.
        batch = [f for f in batch if self.update(f, apply=False)]
        if not batch:
            return
        marker = design.timeline.markerPosition
        keys = [self.native(f).entityToken for f in batch]
        added_keys = set(keys) - self.busy
        self.busy.update(added_keys)
        self.running = True
        try:
            for feature in batch:
                if not feature.timelineObject.rollTo(False):
                    raise RuntimeError('Cannot position history after ' + feature.name)
                self.update(feature)
        except Exception:
            # Do not auto-retry a failed command or its newly queued side effects.
            self.pending.clear()
            raise
        finally:
            try:
                design.timeline.markerPosition = marker
            finally:
                self.running = False
                self.busy.difference_update(added_keys)


def log_error():
    adsk.core.Application.get().log('AirfoilSplines deferred update failed: ' + traceback.format_exc())


class Created(adsk.core.CommandCreatedEventHandler):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def notify(self, args):
        args.command.isRepeatable = False
        self.owner.attach(args.command.execute, Execute(self.owner))


class Execute(adsk.core.CommandEventHandler):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def notify(self, args):
        try:
            self.owner.execute()
        except Exception as exc:
            log_error()
            args.executeFailed = True
            args.executeFailedMessage = str(exc)


class Starting(adsk.core.ApplicationCommandEventHandler):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def notify(self, args):
        if is_history(args.commandId):
            self.owner.history_replay = True
            self.owner.pending.clear()


class Terminated(adsk.core.ApplicationCommandEventHandler):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def notify(self, args):
        try:
            if is_history(args.commandId):
                self.owner.history_replay = False
                self.owner.pending.clear()
                return
            # Do not release the history guard for nested environment commands.
            self.owner.request()
        except Exception:
            log_error()


class Dispatch(adsk.core.CustomEventHandler):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def notify(self, args):
        owner = self.owner
        owner.queued = False
        if owner.stopped or owner.running or owner.history_replay:
            return
        try:
            _, batch = owner.active_batch()
            if not batch or adsk.core.Application.get().userInterface.activeCommand != 'SelectCommand':
                return  # Never cancel/interfere with a user's active command.
            if not owner.command.execute():
                raise RuntimeError('Cannot execute the AirfoilSplines refresh command.')
        except Exception:
            owner.pending.clear()
            log_error()
