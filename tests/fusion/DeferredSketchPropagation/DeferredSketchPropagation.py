"""Standalone Fusion reproduction; imports no AirfoilFitter code.

Creates a NEW unsaved document. No Compute All, curve recreation, or timeline
movement occurs inside compute callbacks. Stop writes the final JSON report.
"""
import datetime
import json
import math
from pathlib import Path
import traceback

import adsk.core
import adsk.fusion

ID = 'mr33g.Diagnostics.DeferredSketchPropagation.v1'
# CommandDefinition IDs allow only letters, digits, and underscores. Custom
# feature definition IDs use a different API and can retain their dotted ID.
COMMAND_PREFIX = 'mr33g_Diagnostics_DeferredSketchPropagation_v1_'
_handlers = []
_commands = []
_controls = []
_cases = []
_definition = None
_design = None
_building = False
_ready = False
_report = None
_path = None
EVENT_ID = COMMAND_PREFIX + 'dispatch'
_custom_event = None
_pending = {}
_event_queued = False
_refreshing = False
_history_replay = False


def attach(event, handler):
    event.add(handler)
    _handlers.append((event, handler))


def xyz(p):
    return [p.x, p.y, p.z]


def point(x, y=0, z=0):
    return adsk.core.Point3D.create(x, y, z)


def nurbs(length):
    # One degree-nine span, like a fixed AF spline, but no fitting or file data.
    points = [point(length * i / 9, math.sin(math.pi * i / 9)) for i in range(10)]
    return adsk.core.NurbsCurve3D.createNonRational(points, 9, [0.] * 10 + [1.] * 10, False)


def output(feature):
    sketches = [adsk.fusion.Sketch.cast(f) for f in feature.features]
    sketches = [s for s in sketches if s]
    if len(sketches) != 1:
        raise RuntimeError('Expected exactly one contained sketch.')
    return sketches[0]


def replace(sketch, length):
    if sketch.sketchCurves.sketchFixedSplines.count:
        ok = sketch.sketchCurves.sketchFixedSplines.item(0).replaceGeometry(nurbs(length))
    else:
        endpoint = sketch.sketchCurves.sketchLines.item(0).endSketchPoint
        ok = endpoint.move(endpoint.geometry.vectorTo(point(length)))
    if not ok:
        raise RuntimeError('Fusion rejected the in-place geometry change.')


def write_report():
    if _path and _report:
        _path.write_text(json.dumps(_report, indent=2, ensure_ascii=False), encoding='utf-8')


class Compute(adsk.fusion.CustomFeatureEventHandler):
    def notify(self, args):
        if _building:
            return
        entry = {'kind': 'compute', 'time': datetime.datetime.now().isoformat()}
        try:
            feature = args.customFeature
            entry['feature'] = feature.name
            chord = feature.dependencies.itemById('chord').entity
            length = chord.startSketchPoint.geometry.distanceTo(chord.endSketchPoint.geometry)
            sketch = output(feature)
            entry['lengthCm'] = length
            entry['revisionBefore'] = sketch.revisionId
            geometry = sketch.sketchCurves.item(0).geometry
            points = geometry.controlPoints if hasattr(geometry, 'controlPoints') else [geometry.startPoint, geometry.endPoint]
            changed = abs(max(p.x for p in points) - length) > 1e-9
            entry['changed'] = changed
            # Experimental workaround: leave geometry alone in this callback.
            # Refresh only after the upstream transaction has finished.
            if changed and not _refreshing and not _history_replay:
                _pending[feature.name] = feature
                entry['queued'] = True
            else:
                entry['queued'] = False
            entry['success'] = True
        except Exception:
            entry['error'] = traceback.format_exc()
            args.computeStatus.statusMessages.addError('DRPOINT_COMPUTE_FAILED', '')
        # Buffer only: no downstream reads, UI calls, or file writes in compute.
        if _report is not None:
            _report['events'].append(entry)


def active_test():
    return _design and adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct) == _design


def snapshot(kind, detail=None):
    if not active_test() or _building:
        return
    entry = {'kind': kind, 'detail': detail, 'time': datetime.datetime.now().isoformat(),
             'marker': _design.timeline.markerPosition, 'cases': []}
    target = _design.userParameters.itemByName('probeLength').value
    for case in _cases:
        result = {'case': case['name'], 'requestedLengthCm': target}
        try:
            # Preserve feature health even if a subsequent geometry read fails.
            result.update(loftHealth=case['loft'].healthState,
                          loftMessage=case['loft'].errorOrWarningMessage,
                          loftRolledBack=case['loft'].timelineObject.isRolledBack)
            sketch = output(case['feature']) if case['feature'] else case['sketch']
            curve = sketch.sketchCurves.item(0).geometry
            points = curve.controlPoints if hasattr(curve, 'controlPoints') else [curve.startPoint, curve.endPoint]
            result.update(sketchRevision=sketch.revisionId,
                          curveType=curve.objectType, curvePoints=[xyz(p) for p in points],
                          outputMaxX=max(p.x for p in points))
            if case['feature']:
                result['customHealth'] = case['feature'].healthState
                result['customMessage'] = case['feature'].errorOrWarningMessage
                line = case['feature'].dependencies.itemById('chord').entity
                result['chordEndpoints'] = [xyz(line.startSketchPoint.geometry), xyz(line.endSketchPoint.geometry)]
            bodies = []
            for body in case['loft'].bodies:
                body_result = {}
                bodies.append(body_result)
                try:
                    body_result.update(revision=body.revisionId, faceCount=body.faces.count,
                                       edgeCount=body.edges.count)
                    bounds = body.boundingBox
                    body_result['bounds'] = [xyz(bounds.minPoint), xyz(bounds.maxPoint)]
                    body_result['vertices'] = [xyz(v.geometry) for v in body.vertices]
                except Exception:
                    body_result['error'] = traceback.format_exc()
            result['bodies'] = bodies
            if len(bodies) == 1 and 'bounds' in bodies[0] and not result['loftRolledBack']:
                result['loftMatchesOutput'] = abs(bodies[0]['bounds'][1][0] - result['outputMaxX']) < 1e-6
                result['outputMatchesRequested'] = abs(result['outputMaxX'] - target) < 1e-6
        except Exception:
            result['error'] = traceback.format_exc()
        entry['cases'].append(result)
    _report['events'].append(entry)
    write_report()


def add_curve(sketch, kind, length):
    if kind == 'line':
        return sketch.sketchCurves.sketchLines.addByTwoPoints(point(0), point(length))
    return sketch.sketchCurves.sketchFixedSplines.addByNurbsCurve(nurbs(length))


def build_case(index, name, kind, custom):
    # Keep the reproduction entirely in the root component. Native entities in
    # inactive child components introduce assembly-context requirements that are
    # unrelated to the downstream propagation being tested.
    component = _design.rootComponent
    support = component.xYConstructionPlane
    if index:
        support_input = component.constructionPlanes.createInput()
        support_input.setByOffset(support, adsk.core.ValueInput.createByReal(index * 8))
        support = component.constructionPlanes.add(support_input)
        support.name = name + ' support'
    chord = None
    if custom:
        source = component.sketches.add(support)
        source.name = name + ' source chord'
        chord = source.sketchCurves.sketchLines.addByTwoPoints(point(0), point(10))
        chord.startSketchPoint.isFixed = True
        source.geometricConstraints.addHorizontal(chord)
        dimension = source.sketchDimensions.addDistanceDimension(
            chord.startSketchPoint, chord.endSketchPoint,
            adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation, point(5, -1))
        dimension.parameter.expression = 'probeLength'
        source.isLightBulbOn = False
    sketch = component.sketches.add(support)
    sketch.name = name + ' output'
    add_curve(sketch, kind, 10)
    feature = None
    if custom:
        # Reacquire after dimension solving and output creation, and record the
        # exact context if Fusion rejects even this root-component dependency.
        chord = source.sketchCurves.sketchLines.item(0)
        _report['events'].append({
            'kind': 'dependency-setup', 'case': name,
            'valid': chord.isValid, 'type': chord.objectType,
            'hasAssemblyContext': chord.assemblyContext is not None,
            'sourceIsRoot': source.parentComponent == _design.rootComponent,
            'outputIsRoot': sketch.parentComponent == _design.rootComponent})
        data = component.features.customFeatures.createInput(_definition)
        if not data.addDependency('chord', chord):
            raise RuntimeError('Could not add chord dependency.')
        if not data.setStartAndEndFeatures(sketch, sketch):
            raise RuntimeError('Could not group the single output sketch.')
        feature = component.features.customFeatures.add(data)
        feature.name = name
        sketch = output(feature)
    plane_input = component.constructionPlanes.createInput()
    plane_input.setByOffset(support, adsk.core.ValueInput.createByReal(5))
    plane = component.constructionPlanes.add(plane_input)
    tip = component.sketches.add(plane)
    tip.name = name + ' stationary tip'
    add_curve(tip, kind, 8)
    loft_input = component.features.loftFeatures.createInput(adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    loft_input.isSolid = False
    # Open single-curve paths, with no chain inference or cached closed profiles.
    for section in (sketch, tip):
        path = component.features.createPath(section.sketchCurves.item(0), False)
        loft_input.loftSections.add(path)
    loft = component.features.loftFeatures.add(loft_input)
    loft.name = name + ' surface loft'
    sketch.isLightBulbOn = False
    tip.isLightBulbOn = False
    _cases.append(dict(name=name, component=component, sketch=sketch, feature=feature, loft=loft))


class Execute(adsk.core.CommandEventHandler):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def notify(self, args):
        global _building, _refreshing
        try:
            if not active_test():
                raise RuntimeError('Activate the new DeferredSketchPropagation test document first.')
            if self.action == 'build':
                if _design.userParameters.itemByName('probeLength') or _cases:
                    raise RuntimeError('This fixture has already been built or partially built. Start a fresh probe.')
                _building = True
                try:
                    _design.userParameters.add('probeLength', adsk.core.ValueInput.createByReal(10), 'cm', 'Diagnostic chord length')
                    for index, spec in enumerate([
                            ('A callback line', 'line', True),
                            ('B callback spline', 'spline', True),
                            ('C callback spline repeat', 'spline', True),
                            ('D ordinary command spline', 'spline', False)]):
                        build_case(index, *spec)
                finally:
                    _building = False
            elif not _ready:
                raise RuntimeError('Run Deferred probe: build fixture first. A healthy baseline is required.')
            elif self.action == 'refresh':
                batch = sorted(_pending.values(), key=lambda f: f.timelineObject.index)
                _pending.clear()
                marker = _design.timeline.markerPosition
                _refreshing = True
                try:
                    for feature in batch:
                        if not feature.isValid or feature.timelineObject.index >= marker:
                            raise RuntimeError('Queued feature is invalid or beyond the current timeline marker.')
                        if not feature.timelineObject.rollTo(False):
                            raise RuntimeError('Could not position timeline after ' + feature.name)
                        chord = feature.dependencies.itemById('chord').entity
                        length = chord.startSketchPoint.geometry.distanceTo(chord.endSketchPoint.geometry)
                        replace(output(feature), length)
                        _report['events'].append({'kind': 'ordinary-refresh', 'feature': feature.name, 'lengthCm': length})
                finally:
                    try:
                        _design.timeline.markerPosition = marker
                    finally:
                        _refreshing = False
            elif self.action == 'advance':
                parameter = _design.userParameters.itemByName('probeLength')
                parameter.expression = '{} cm'.format(round(parameter.value + 2, 6))
            else:
                case = _cases[-1]
                marker = _design.timeline.markerPosition
                try:
                    # Ordinary command control uses the correct historical position.
                    # This is deliberately NEVER done in the compute callback.
                    if not case['sketch'].timelineObject.rollTo(False):
                        raise RuntimeError('Could not position the ordinary-command control.')
                    replace(case['sketch'], _design.userParameters.itemByName('probeLength').value)
                finally:
                    _design.timeline.markerPosition = marker
        except Exception:
            if self.action == 'refresh':
                _pending.clear()  # No automatic retry loop after a failed transaction.
            error = traceback.format_exc()
            _report['events'].append({'kind': 'command-error', 'action': self.action, 'error': error})
            write_report()
            args.executeFailed = True
            args.executeFailedMessage = error


class Created(adsk.core.CommandCreatedEventHandler):
    def __init__(self, action):
        super().__init__()
        self.action = action

    def notify(self, args):
        args.command.isRepeatable = False
        attach(args.command.execute, Execute(self.action))


class EditCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        args.command.commandInputs.addTextBoxCommandInput(
            'probeInfo', 'Propagation probe',
            'Use Deferred probe: change chord to update the input. This dialog does not edit the model.', 3, True)


class Terminated(adsk.core.ApplicationCommandEventHandler):
    def notify(self, args):
        global _ready, _history_replay
        try:
            replay = _history_replay or is_history_command(args.commandId)
            # Fusion emits nested ActivateEnvironmentCommand events during
            # Undo/Redo. Keep the guard until the outer history command ends.
            if is_history_command(args.commandId):
                _history_replay = False
            if replay:
                _pending.clear()
            if args.commandId == COMMAND_PREFIX + 'build' and active_test():
                snapshot('baseline', args.commandId)
                baseline = _report['events'][-1]['cases']
                failures = [c['case'] for c in baseline if c.get('error')
                            or c.get('customHealth', 0) != 0 or c.get('loftHealth') != 0
                            or not c.get('loftMatchesOutput') or not c.get('outputMatchesRequested')]
                _ready = len(baseline) == 4 and not failures
                _report['baselineHealthy'] = _ready
                write_report()
                ui = adsk.core.Application.get().userInterface
                if _ready:
                    ui.messageBox('Baseline healthy. Run Deferred probe: change chord and wait for the automatic refresh.\n'
                                  'Then run Deferred probe: direct control. Repeat once, then stop and keep the document open.\n'
                                  'The refresh is a separate undo step. No Compute All is used.')
                else:
                    ui.messageBox('Baseline failed. Do not run the change commands.\n'
                                  'Report: ' + str(_path))
            elif _cases:
                snapshot('command-terminated', args.commandId)
            if not replay and args.commandId != COMMAND_PREFIX + 'refresh':
                request_refresh()
        except Exception:
            if _report is not None:
                _report['events'].append({'kind': 'snapshot-error', 'error': traceback.format_exc()})
                write_report()


def is_history_command(command_id):
    return 'undo' in command_id.lower() or 'redo' in command_id.lower()


class Starting(adsk.core.ApplicationCommandEventHandler):
    def notify(self, args):
        global _history_replay
        _history_replay = _history_replay or is_history_command(args.commandId)
        if _history_replay:
            _pending.clear()


def request_refresh():
    global _event_queued
    if _ready and _pending and not _refreshing and not _event_queued and active_test():
        _event_queued = True
        try:
            result = adsk.core.Application.get().fireCustomEvent(EVENT_ID, 'targeted-refresh')
        except Exception:
            _event_queued = False
            raise
        _report['events'].append({'kind': 'dispatch-request', 'time': datetime.datetime.now().isoformat(),
                                  'returnValue': result})
        # In the first live run, false returns were followed by event delivery.
        # Record the return separately; do not claim the refresh failed solely
        # from this value. Permit retry on a later command if no event arrives.
        if not result:
            _event_queued = False
        write_report()


class Dispatch(adsk.core.CustomEventHandler):
    def notify(self, args):
        global _event_queued
        _event_queued = False
        try:
            _report['events'].append({'kind': 'dispatch-delivered', 'time': datetime.datetime.now().isoformat()})
            write_report()
            if not _ready or not _pending or _refreshing or _history_replay or not active_test():
                return
            ui = adsk.core.Application.get().userInterface
            # Never interrupt a user command. Its termination can queue us again.
            if ui.activeCommand != 'SelectCommand':
                _report['events'].append({'kind': 'refresh-postponed', 'activeCommand': ui.activeCommand})
                write_report()
                return
            marker = _design.timeline.markerPosition
            if any(not f.isValid or f.timelineObject.index >= marker for f in _pending.values()):
                _pending.clear()
                _report['events'].append({'kind': 'refresh-cancelled', 'reason': 'invalid or rolled-back feature'})
                write_report()
                return
            command = ui.commandDefinitions.itemById(COMMAND_PREFIX + 'refresh')
            if not command or not command.execute():
                raise RuntimeError('Could not execute the ordinary refresh command.')
        except Exception:
            _pending.clear()
            _report['events'].append({'kind': 'dispatch-error', 'error': traceback.format_exc()})
            write_report()


def detach():
    global _custom_event, _event_queued, _ready, _history_replay
    _ready = False
    _pending.clear()
    _event_queued = False
    _history_replay = False
    for event, handler in reversed(_handlers):
        try:
            event.remove(handler)
        except Exception:
            pass  # Command event owners may already have been destroyed.
    _handlers.clear()
    if _custom_event is not None:
        adsk.core.Application.get().unregisterCustomEvent(EVENT_ID)
        _custom_event = None
    for item in _controls + _commands:
        if item.isValid:
            item.deleteMe()
    _controls.clear()
    _commands.clear()


def recover_existing(design):
    """Resolve our complete fixture for a read-only snapshot, without rebuilding."""
    if not design or not design.userParameters.itemByName('probeLength'):
        return False
    root = design.rootComponent
    features = [f for f in root.features.customFeatures if f.definition.id == ID]
    if not features:
        return False
    recovered = []
    for feature in sorted(features, key=lambda f: f.name):
        lofts = [f for f in root.features.loftFeatures if f.name == feature.name + ' surface loft']
        if len(lofts) != 1:
            raise RuntimeError('Existing probe is incomplete: missing loft for ' + feature.name)
        recovered.append(dict(name=feature.name, feature=feature, sketch=output(feature),
                              component=root, loft=lofts[0]))
    direct = [f for f in root.features.loftFeatures if f.name.startswith('D ordinary command spline')]
    if len(features) != 3 or len(direct) != 1:
        raise RuntimeError('Existing probe is incomplete; expected three custom features and one direct control.')
    name = direct[0].name.removesuffix(' surface loft')
    sketches = [s for s in root.sketches if s.name == name + ' output']
    if len(sketches) != 1:
        raise RuntimeError('Cannot uniquely resolve the ordinary-command output sketch.')
    recovered.append(dict(name=name, feature=None, sketch=sketches[0], component=root, loft=direct[0]))
    _cases.extend(recovered)
    return True


def run(context):
    global _definition, _design, _building, _report, _path, _ready, _custom_event
    app = adsk.core.Application.get()
    try:
        detach()
        _cases.clear()
        _ready = False
        _building = True
        _path = Path(__file__).with_name('propagation-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
        _report = {'fusionVersion': app.version, 'script': str(Path(__file__).resolve()),
                   'probeRevision': 2,
                   'experiment': 'defer callback geometry to ordinary command; no Compute All',
                   'note': 'No AirfoilFitter imports. Units cm. Ordinary control changes only on its own command.',
                   'events': []}
        existing = adsk.fusion.Design.cast(app.activeProduct)
        if recover_existing(existing):
            _design = existing
            _building = False
            _report['mode'] = 'read-only existing fixture'
            snapshot('existing-state')
            app.userInterface.messageBox(
                'Captured the existing probe without changing geometry or moving the timeline.\n'
                'No test commands or compute handlers were attached. You can stop this add-in now.\n\n'
                'Report: ' + str(_path))
            return
        _definition = adsk.fusion.CustomFeatureDefinition.create(ID, 'Propagation probe', str(Path(__file__).with_name('resources')))
        # Match the documented registration sequence and the production add-in.
        # Revision 2 omitted this and began with "extension ... not running"
        # warnings, so its downstream failure is not a clean baseline.
        edit_id = COMMAND_PREFIX + 'edit'
        edit = app.userInterface.commandDefinitions.itemById(edit_id)
        if not edit:
            edit = app.userInterface.commandDefinitions.addButtonDefinition(
                edit_id, 'Inspect propagation probe', 'Show propagation probe instructions')
        _commands.append(edit)
        attach(edit.commandCreated, EditCreated())
        _definition.editCommandId = edit_id
        attach(_definition.customFeatureCompute, Compute())
        document = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        document.name = 'DeferredSketchPropagation - disposable test'
        _design = adsk.fusion.Design.cast(app.activeProduct)
        _design.designType = adsk.fusion.DesignTypes.ParametricDesignType
        _building = False
        panel = app.userInterface.allToolbarPanels.itemById('SolidScriptsAddinsPanel')
        if not panel:
            raise RuntimeError('Could not find the Utilities Add-ins panel.')
        for action, title in [('build', 'Deferred probe: build fixture'), ('advance', 'Deferred probe: change chord'),
                              ('direct', 'Deferred probe: direct control'), ('refresh', 'Deferred probe: refresh outputs')]:
            command_id = COMMAND_PREFIX + action
            command = app.userInterface.commandDefinitions.itemById(command_id)
            if not command:
                command = app.userInterface.commandDefinitions.addButtonDefinition(command_id, title, title)
            _commands.append(command)
            attach(command.commandCreated, Created(action))
            _controls.append(panel.controls.addCommand(command))
        attach(app.userInterface.commandTerminated, Terminated())
        attach(app.userInterface.commandStarting, Starting())
        _custom_event = app.registerCustomEvent(EVENT_ID)
        attach(_custom_event, Dispatch())
        write_report()
        app.userInterface.messageBox(
            'Opened a NEW empty disposable test document. Add-in startup must finish before building.\n\n'
            'Use command search (S) or Utilities > Add-ins:\n'
            '1. Deferred probe: build fixture. Wait for the baseline result.\n'
            '2. If baseline is healthy: Deferred probe: change chord (100 to 120 mm), then wait for automatic refresh.\n'
            '3. Deferred probe: direct control.\n'
            'Then stop this add-in to finish the report.\n\n'
            'Do not use Compute All or edit the lofts during this test.\n'
            'The fourth loft changes only when you run direct control.\n\n'
            'Report: ' + str(_path))
    except Exception:
        _building = False
        error = traceback.format_exc()
        if _report is not None:
            _report['events'].append({'kind': 'setup-error', 'error': error})
            write_report()
        detach()
        app.userInterface.messageBox('Propagation probe setup failed:\n' + error)


def stop(context):
    try:
        if _cases:
            snapshot('stop')
    finally:
        detach()
    if _path:
        adsk.core.Application.get().userInterface.messageBox('Report saved:\n' + str(_path))
