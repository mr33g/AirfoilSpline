"""Experimental parametric AirfoilSpline feature (Fusion Custom Features preview)."""
import copy
import os
import traceback

import adsk.core
import adsk.fusion

from logic import feature_recipe
from logic.airfoil_frame import chord_frame, sketch_points


# AirfoilSpline owns its feature data independently of the legacy add-in.
GROUP = 'AirfoilSpline.CustomCommand.v1'
DEFINITION_ID = 'mr33g.AirfoilSpline.Parametric.v1'
EDIT_ID = 'AirfoilSplineEditFeature'
_definition = None
_handlers = []
_sessions = []
_busy = set()
_selection_highlight = None
_deferred = None


def _attach(event, handler, keep):
    event.add(handler)
    keep.append((event, handler))


def register(addin_dir):
    global _definition, _selection_highlight, _deferred
    ui = adsk.core.Application.get().userInterface
    _definition = adsk.fusion.CustomFeatureDefinition.create(
        DEFINITION_ID, 'AirfoilSpline', os.path.join(addin_dir, 'resources', 'AirfoilSplineFeature'))
    edit = ui.commandDefinitions.itemById(EDIT_ID)
    if not edit:
        edit = ui.commandDefinitions.addButtonDefinition(EDIT_ID, 'Edit AirfoilSpline', 'Edit fitted airfoil')
    edit.resourceFolder = os.path.join(addin_dir, 'resources', 'AirfoilSplineFeature')
    # Fusion validates the ID immediately; the command must already exist.
    _definition.editCommandId = EDIT_ID
    _attach(edit.commandCreated, EditCreated(), _handlers)
    _attach(_definition.customFeatureCompute, Compute(), _handlers)
    _selection_highlight = SelectionHighlight(ui)
    _attach(ui.activeSelectionChanged, _selection_highlight, _handlers)
    _attach(ui.commandStarting, ClearSelectionHighlight(_selection_highlight), _handlers)
    from logic.deferred_update import DeferredUpdates
    _deferred = DeferredUpdates(update, _busy, _native)
    _deferred.start()


def stop():
    global _deferred
    if _deferred:
        _deferred.stop()
        _deferred = None
    if _selection_highlight:
        _selection_highlight.clear()
    feature_recipe._fit_cached.cache_clear()
    for session in list(_sessions):
        session.restore()
    _sessions.clear()
    for event, handler in _handlers:
        event.remove(handler)
    _handlers.clear()
    command = adsk.core.Application.get().userInterface.commandDefinitions.itemById(EDIT_ID)
    if command:
        command.deleteMe()


def _native(entity):
    return getattr(entity, 'nativeObject', None) or entity


def tag(entity, role):
    _native(entity).attributes.add(GROUP, 'role', role)


def _group_start(sketch, supports):
    """Accept only an exact, contiguous block of explicitly owned entities."""
    if not supports:
        return sketch
    members = [_native(entity) for entity in supports] + [sketch]
    timeline = sketch.timelineObject.parentTimeline
    start = members[0].timelineObject.index
    if start < 0:
        raise RuntimeError('Cannot verify the AirfoilSpline support group position.')
    for offset, member in enumerate(members):
        item = member.timelineObject
        if (item.parentTimeline != timeline or item.index != start + offset
                or _native(timeline.item(start + offset).entity) != member):
            raise RuntimeError('AirfoilSpline supports and output are not contiguous; '
                               'creation cancelled to protect unrelated timeline operations.')
    return members[0]


def wrap(sketch, line, inputs, cache, rotation, flip, *, supports=()):
    if _definition is None:
        raise RuntimeError('AirfoilSpline custom feature definition is not registered.')
    path = inputs.itemById('file_path').value
    recipe = dict(feature_recipe.read_source(path), schema=feature_recipe.SCHEMA,
                  rotation=int(rotation), flip=bool(flip))
    values = dict(te=inputs.itemById('te_thickness').value,
                  smoothness=inputs.itemById('smoothness_input').valueOne,
                  upper_count=len(cache['upper_cp_raw']), lower_count=len(cache['lower_cp_raw']),
                  continuity=3 if cache['enforce_g3'] else 2 if cache['enforce_g2'] else 1)
    native = sketch.nativeObject or sketch
    tag(native, 'output')
    collection = native.parentComponent.features.customFeatures
    data = collection.createInput(_definition)
    for key, label, units in feature_recipe.PARAMETERS:
        if not data.addCustomParameter(key, label, adsk.core.ValueInput.createByReal(values[key]), units, True):
            raise RuntimeError('Cannot create airfoil parameter: ' + label)
    if not data.addDependency('chord', line):
        raise RuntimeError('Cannot retain the airfoil chord dependency.')
    # A range includes EVERY intervening operation. Check the actual entities,
    # immediately before grouping, rather than relying on an old marker index.
    first = _group_start(native, supports)
    if not data.setStartAndEndFeatures(first, native):
        raise RuntimeError('Fusion could not group the airfoil output into one timeline feature.')
    feature = collection.add(data)
    if not feature:
        raise RuntimeError('Fusion could not create the AirfoilSpline custom feature.')
    expected = [_native(entity) for entity in supports] + [native]
    actual = [_native(entity) for entity in feature.features]
    if len(actual) != len(expected) or any(entity not in expected for entity in actual):
        raise RuntimeError('Fusion grouped unexpected features; AirfoilSpline creation cancelled.')
    feature.name = 'AirfoilSpline - ' + os.path.splitext(recipe['filename'])[0]
    _native(feature).attributes.add(GROUP, 'recipe', feature_recipe.encode(recipe))
    return feature


def read_recipe(feature):
    attribute = _native(feature).attributes.itemByName(GROUP, 'recipe')
    if not attribute:
        raise RuntimeError('This feature has no embedded AirfoilSpline recipe.')
    return feature_recipe.decode(attribute.value)


def parameter_values(feature):
    return {key: feature.parameters.itemById(key).value for key, _, _ in feature_recipe.PARAMETERS}


def output_sketch(feature):
    for entity in feature.features:
        sketch = adsk.fusion.Sketch.cast(entity)
        if sketch and _role(sketch) == 'output':
            return sketch.nativeObject or sketch
    raise RuntimeError('The AirfoilSpline output sketch is missing.')


def _role(entity):
    attribute = _native(entity).attributes.itemByName(GROUP, 'role')
    return attribute.value if attribute else None


class SelectionHighlight(adsk.core.ActiveSelectionEventHandler):
    """Highlight with transient graphics without altering command selections."""
    def __init__(self, ui):
        super().__init__()
        self.ui = ui
        self.groups = []
        self.updating = False

    def clear(self):
        for group in self.groups:
            if group.isValid:
                group.deleteMe()
        self.groups.clear()

    def notify(self, args):
        if self.updating:
            return
        self.updating = True
        try:
            self.clear()
            sketches = []
            for selection in args.currentSelection:
                feature = adsk.fusion.CustomFeature.cast(selection.entity)
                if not feature or feature.definition.id != DEFINITION_ID:
                    continue
                sketch = output_sketch(feature)
                if sketch in sketches:
                    continue
                sketches.append(sketch)
                # Native worldGeometry is in parent-component coordinates, the
                # coordinate system used by that component's custom graphics.
                group = sketch.parentComponent.customGraphicsGroups.add()
                self.groups.append(group)
                group.isSelectable = False
                curves = list(sketch.sketchCurves.sketchFixedSplines)
                curves += list(sketch.sketchCurves.sketchLines)
                for curve in curves:
                    if _role(curve) in ('upper', 'lower', 'trailing'):
                        graphic = group.addCurve(curve.worldGeometry)
                        graphic.color = adsk.fusion.CustomGraphicsSolidColorEffect.create(
                            adsk.core.Color.create(0, 160, 255, 255))
                        graphic.weight = 3
                        graphic.depthPriority = 100
        except Exception:
            self.clear()
            adsk.core.Application.get().log('AirfoilSpline selection highlight failed: ' + traceback.format_exc())
        finally:
            self.updating = False


class ClearSelectionHighlight(adsk.core.ApplicationCommandEventHandler):
    def __init__(self, highlight):
        super().__init__()
        self.highlight = highlight

    def notify(self, args):
        # Remove transient highlighting before Edit, Delete, or other commands.
        self.highlight.clear()


def _same_curve(first, second):
    """Compare the actual model geometry, including its parameter direction.

    Do not use an in-memory 'last applied' flag: Undo can restore older geometry.
    """
    try:
        if first.isRational or second.isRational:
            return False
        if (first.degree, first.isClosed, first.isPeriodic) != (second.degree, second.isClosed, second.isPeriodic):
            return False
        a, b = first.controlPoints, second.controlPoints
        ka, kb = first.knots, second.knots
        return (len(a) == len(b) and len(ka) == len(kb)
                and all(p.distanceTo(q) <= 1e-9 for p, q in zip(a, b))
                and all(abs(x - y) <= 1e-12 for x, y in zip(ka, kb)))
    except AttributeError:
        return False


def apply_edit(feature, original_recipe, original_values, recipe, values, te_expression):
    # A double flip, opening/accepting, or visualization-only edit must not
    # replace the curves or rewrite unchanged attributes/parameters.
    if (any(recipe[key] != original_recipe[key] for key in ('dat', 'rotation', 'flip'))
            or values != original_values):
        update(feature, recipe, values)
    if recipe != original_recipe:
        _native(feature).attributes.add(GROUP, 'recipe', feature_recipe.encode(recipe))
    for name, _, _ in feature_recipe.PARAMETERS:
        parameter = feature.parameters.itemById(name)
        if name == 'te':
            if parameter.expression != te_expression:
                parameter.expression = te_expression
        elif values[name] != original_values[name]:
            parameter.value = values[name]
    if recipe['filename'] != original_recipe['filename']:
        feature.name = 'AirfoilSpline - ' + os.path.splitext(recipe['filename'])[0]


def update(feature, recipe=None, values=None, *, apply=True):
    """Refit and compare; optionally replace existing sketch geometry in place."""
    recipe = read_recipe(feature) if recipe is None else recipe
    values = parameter_values(feature) if values is None else values
    dependency = feature.dependencies.itemById('chord')
    line = adsk.fusion.SketchLine.cast(dependency.entity) if dependency else None
    if not line:
        raise RuntimeError('The AirfoilSpline chord reference is missing.')
    frame, length = chord_frame(line, recipe['rotation'], recipe['flip'])
    fitted = feature_recipe.fit(recipe, values, length)
    sketch = output_sketch(feature)
    coordinate_sketch = sketch
    occurrence = line.assemblyContext
    if occurrence:
        coordinate_sketch = sketch.createForAssemblyContext(occurrence)
        if not coordinate_sketch:
            raise RuntimeError('Cannot resolve the output sketch occurrence.')
    curves = {_role(s): s for s in sketch.sketchCurves.sketchFixedSplines}
    replacements = []
    endpoints = []
    for role, offset in (('upper', 0), ('lower', 3)):
        if role not in curves:
            raise RuntimeError('The original airfoil spline is missing: ' + role)
        points = sketch_points(fitted[offset], frame, length, coordinate_sketch)
        nurbs = adsk.core.NurbsCurve3D.createNonRational(
            points, fitted[offset + 2], list(fitted[offset + 1]), False)
        if not nurbs:
            raise RuntimeError('Cannot construct the updated airfoil spline.')
        old = curves[role].geometry
        if not _same_curve(old, nurbs):
            replacements.append((curves[role], nurbs, old))
        endpoints.append(points[-1])
    connectors = [line for line in sketch.sketchCurves.sketchLines if _role(line) == 'trailing']
    if len(connectors) > 1:
        raise RuntimeError('The airfoil has more than one trailing-edge connector.')
    open_te = endpoints[0].distanceTo(endpoints[1]) > 1e-7
    connector_changed = bool(connectors) != open_te
    if open_te and connectors:
        connector_changed = any(point.geometry.distanceTo(target) > 1e-7
                                for point, target in zip(
                                    (connectors[0].startSketchPoint, connectors[0].endSketchPoint), endpoints))
    changed = bool(replacements) or connector_changed
    if not apply or not changed:
        return changed
    saved_points = [(point, point.geometry.copy()) for connector in connectors
                    for point in (connector.startSketchPoint, connector.endSketchPoint)]
    added_connector = None
    try:
        for spline, geometry, old in replacements:
            if not spline.replaceGeometry(geometry):
                raise RuntimeError('Fusion rejected SketchFixedSpline.replaceGeometry.')
        if endpoints[0].distanceTo(endpoints[1]) > 1e-7:
            if connectors:
                connector = connectors[0]
                for point, target in zip((connector.startSketchPoint, connector.endSketchPoint), endpoints):
                    if point.geometry.distanceTo(target) > 1e-7:
                        if not point.move(point.geometry.vectorTo(target)):
                            raise RuntimeError('Fusion could not update the trailing-edge connector.')
            else:
                added_connector = sketch.sketchCurves.sketchLines.addByTwoPoints(*endpoints)
                tag(added_connector, 'trailing')
        else:
            for connector in connectors:
                if not connector.deleteMe():
                    raise RuntimeError('Fusion could not remove the closed trailing-edge connector.')
    except Exception:
        # A compute callback is not an ordinary command transaction. Restore the
        # original spline shapes if Fusion accepts one replacement but rejects another.
        for spline, geometry, old in replacements:
            try:
                if not spline.replaceGeometry(old):
                    raise RuntimeError('Fusion rejected spline rollback.')
            except Exception:
                adsk.core.Application.get().log('AirfoilSpline rollback failed: ' + traceback.format_exc())
        try:
            if added_connector and not added_connector.deleteMe():
                raise RuntimeError('Fusion rejected connector rollback.')
            for point, original in saved_points:
                if point.geometry.distanceTo(original) > 1e-7:
                    if not point.move(point.geometry.vectorTo(original)):
                        raise RuntimeError('Fusion rejected connector endpoint rollback.')
        except Exception:
            adsk.core.Application.get().log('AirfoilSpline rollback failed: ' + traceback.format_exc())
        raise
    return changed


class Compute(adsk.fusion.CustomFeatureEventHandler):
    def notify(self, args):
        feature = args.customFeature
        key = _native(feature).entityToken
        # Fusion may compute during initial collection.add, before attributes exist.
        if key in _busy or not _native(feature).attributes.itemByName(GROUP, 'recipe'):
            return
        _busy.add(key)
        try:
            if _deferred:
                if not _deferred.history_replay and update(feature, apply=False):
                    _deferred.queue(feature)
            else:
                update(feature)
        except Exception:
            adsk.core.Application.get().log('AirfoilSpline recompute failed: ' + traceback.format_exc())
            args.computeStatus.statusMessages.addError('DRPOINT_COMPUTE_FAILED', '')
        finally:
            _busy.discard(key)


class EditCreated(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            ui = adsk.core.Application.get().userInterface
            feature = adsk.fusion.CustomFeature.cast(ui.activeSelections.item(0).entity)
            if not feature or feature.definition.id != DEFINITION_ID:
                raise RuntimeError('Select an AirfoilSpline custom feature to edit.')
            session = EditSession(feature, args.command)
            session.connect()
            _sessions.append(session)
        except Exception:
            app = adsk.core.Application.get()
            app.log('AirfoilSpline edit failed: ' + traceback.format_exc())
            app.userInterface.messageBox('Could not open the airfoil feature. See Text Commands for details.')


class EditSession:
    def __init__(self, feature, command):
        # Import lazily: the creation handlers import fitter, which imports us.
        from ui.dialog import create_ui_inputs
        from logic import state
        import tempfile
        from pathlib import Path

        self.feature = feature
        self.command = command
        self.recipe = copy.deepcopy(read_recipe(feature))
        self.values = parameter_values(feature)
        self.handlers = []
        self.marker = None
        self.ready = False
        self.design = feature.parentComponent.parentDesign
        self.directory = tempfile.TemporaryDirectory(prefix='airfoil_edit_')
        # The normal fitter can read embedded data through its existing loader.
        self.path = str(Path(self.directory.name) / Path(self.recipe['filename']).name)
        Path(self.path).write_text(self.recipe['dat'])
        state.reset_state()
        command.setDialogSize(300, 0)
        create_ui_inputs(command.commandInputs, smoothness_max=max(0.1, self.values['smoothness']))
        self.sketch = output_sketch(feature)
        self.visible = self.sketch.isLightBulbOn

    def initialize(self):
        from logic import state
        from ui.handlers import AirfoilSplineCommandInputChangedHandler, update_cp_count_labels

        inputs = self.command.commandInputs
        dependency = self.feature.dependencies.itemById('chord')
        if not dependency or not dependency.entity:
            raise RuntimeError('The AirfoilSpline chord reference is missing.')
        inputs.itemById('chord_line').addSelection(dependency.entity)
        inputs.itemById('file_path').value = self.path
        inputs.itemById('select_file').text = os.path.splitext(self.recipe['filename'])[0]
        state.rotation_state = self.recipe['rotation']
        state.flip_orientation = self.recipe['flip']
        state.current_cp_count_upper = int(self.values['upper_count'])
        state.current_cp_count_lower = int(self.values['lower_count'])
        te = inputs.itemById('te_thickness')
        te.maximumValue = max(te.maximumValue, self.values['te'])
        te.expression = self.feature.parameters.itemById('te').expression
        smoothness = inputs.itemById('smoothness_input')
        smoothness.valueOne = self.values['smoothness']
        items = inputs.itemById('continuity_level').listItems
        items.item(int(self.values['continuity']) - 1).isSelected = True
        update_cp_count_labels(inputs)
        # Reuse visibility and manipulator setup without initiating a file change.
        shared = AirfoilSplineCommandInputChangedHandler()
        shared.handle(None, inputs, 'chord_line')
        self.lock_inputs()
        self.ready = True

    def lock_inputs(self):
        inputs = self.command.commandInputs
        inputs.itemById('chord_line').isEnabled = False
        inputs.itemById('rotate_airfoil').isEnabled = False

    def connect(self):
        from ui.handlers import AirfoilSplineCommandInputChangedHandler, update_cp_count_labels
        from logic.fitter import run_fitter
        from logic import state
        session = self
        shared_changed = AirfoilSplineCommandInputChangedHandler(preserve_fit_settings=True)

        class Activate(adsk.core.CommandEventHandler):
            def notify(self, args):
                if session.marker is None:
                    try:
                        session.marker = session.design.timeline.markerPosition
                        args.command.beginStep()
                        if not session.ready:
                            session.initialize()
                        session.command.doExecutePreview()
                    except Exception:
                        adsk.core.Application.get().log('AirfoilSpline edit initialization failed: ' + traceback.format_exc())
                        session.restore()
                        raise

        class Changed(adsk.core.InputChangedEventHandler):
            def notify(self, args):
                if not session.ready or args.input.id in ('chord_line', 'rotate_airfoil'):
                    return
                shared_changed.notify(args)
                session.lock_inputs()

        class Preview(adsk.core.CommandEventHandler):
            def notify(self, args):
                if session.ready:
                    succeeded = run_fitter(session.command.commandInputs, True, initialize_te=False)
                    # Keep the original visible until a replacement preview exists.
                    session.sketch.isLightBulbOn = False if succeeded else session.visible
                    update_cp_count_labels(session.command.commandInputs)
                    # This is graphics only; execute must still commit the edit.
                    args.isValidResult = False

        class Execute(adsk.core.CommandEventHandler):
            def notify(self, args):
                key = _native(session.feature).entityToken
                _busy.add(key)
                try:
                    if not session.ready:
                        raise RuntimeError('The edit dialog could not be initialized.')
                    inputs = session.command.commandInputs
                    recipe = dict(session.recipe)
                    recipe.update(feature_recipe.read_source(inputs.itemById('file_path').value))
                    recipe['flip'] = state.flip_orientation
                    values = dict(
                        te=inputs.itemById('te_thickness').value,
                        smoothness=inputs.itemById('smoothness_input').valueOne,
                        upper_count=state.current_cp_count_upper,
                        lower_count=state.current_cp_count_lower,
                        continuity=int(inputs.itemById('continuity_level').selectedItem.name[1:]))
                    # Preview needs no history rollback. Keep other airfoils visible
                    # while the dialog is open; roll only for a committed geometry edit.
                    if (any(recipe[k] != session.recipe[k] for k in ('dat', 'rotation', 'flip'))
                            or values != session.values):
                        session.feature.timelineObject.rollTo(False)
                    apply_edit(session.feature, session.recipe, session.values, recipe, values,
                               inputs.itemById('te_thickness').expression)
                except Exception as exc:
                    adsk.core.Application.get().log('AirfoilSpline edit failed: ' + traceback.format_exc())
                    args.executeFailed = True
                    args.executeFailedMessage = str(exc)
                finally:
                    _busy.discard(key)
                    state.reset_state()
                    session.restore()

        class Destroy(adsk.core.CommandEventHandler):
            def notify(self, args):
                try:
                    state.reset_state()
                    session.restore()
                finally:
                    session.directory.cleanup()
                    session.handlers.clear()
                    if session in _sessions:
                        _sessions.remove(session)

        _attach(self.command.activate, Activate(), self.handlers)
        _attach(self.command.inputChanged, Changed(), self.handlers)
        _attach(self.command.executePreview, Preview(), self.handlers)
        _attach(self.command.execute, Execute(), self.handlers)
        _attach(self.command.destroy, Destroy(), self.handlers)

    def restore(self):
        self.sketch.isLightBulbOn = self.visible
        if self.marker is not None:
            self.design.timeline.markerPosition = self.marker
            self.marker = None
