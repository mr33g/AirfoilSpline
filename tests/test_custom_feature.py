"""Offline coverage; Fusion's model kernel still needs the manual smoke tests."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

import numpy as np
from scipy import interpolate, special  # Load extensions before temporary sys.modules patches.
from airfoil_fit import bspline_helper

ROOT = Path(__file__).resolve().parents[1]


def api_stub():
    adsk = ModuleType('adsk')
    adsk.core = ModuleType('adsk.core')
    adsk.fusion = ModuleType('adsk.fusion')
    for name in ('CommandCreatedEventHandler', 'CommandEventHandler', 'InputChangedEventHandler',
                 'ActiveSelectionEventHandler', 'ApplicationCommandEventHandler'):
        setattr(adsk.core, name, type(name, (), {}))
    adsk.core.Application = NS(get=lambda: NS(log=Mock()))
    adsk.fusion.CustomFeatureEventHandler = type('CustomFeatureEventHandler', (), {})
    adsk.fusion.SketchLine = NS(cast=lambda obj: obj)
    adsk.fusion.Sketch = NS(cast=lambda obj: obj)
    return adsk


def load(name, path, modules):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


class RegistrationTests(unittest.TestCase):
    def test_edit_command_exists_before_definition_references_it(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                adsk = api_stub()
                commands = {}
                edit = NS(commandCreated=Mock())
                if existing:
                    commands['AirfoilSplineEditFeature'] = edit

                def add_command(command_id, *args):
                    commands[command_id] = edit
                    return edit

                definitions = NS(itemById=commands.get, addButtonDefinition=Mock(side_effect=add_command))
                adsk.core.Application = NS(get=lambda: NS(userInterface=NS(
                    commandDefinitions=definitions, activeSelectionChanged=Mock(), commandStarting=Mock())))

                class Definition:
                    customFeatureCompute = Mock()

                    @property
                    def editCommandId(self):
                        return self._edit_id

                    @editCommandId.setter
                    def editCommandId(self, value):
                        if value not in commands:
                            raise RuntimeError('3 : Invalid command Id')
                        self._edit_id = value

                definition = Definition()
                adsk.fusion.CustomFeatureDefinition = NS(create=lambda *args: definition)
                logic = ModuleType('logic')
                logic.feature_recipe = NS()
                module = load('registration_test', 'logic/custom_feature.py',
                              {'adsk': adsk, 'adsk.core': adsk.core, 'adsk.fusion': adsk.fusion,
                               'logic': logic, 'logic.airfoil_frame': NS(chord_frame=Mock(), sketch_points=Mock())})
                with patch.dict(sys.modules, {'logic.deferred_update': NS(DeferredUpdates=Mock())}):
                    module.register(str(ROOT))
                self.assertEqual(definition.editCommandId, module.EDIT_ID)
                self.assertEqual(definitions.addButtonDefinition.call_count, 0 if existing else 1)
                edit.commandCreated.add.assert_called_once()


class WrappingTests(unittest.TestCase):
    def test_insertion_groups_only_output_even_with_unrelated_history(self):
        adsk = api_stub()
        adsk.core.ValueInput = NS(createByReal=lambda value: value)
        recipe = NS(read_source=lambda path: {'filename': path}, SCHEMA=1,
                    PARAMETERS=[], encode=lambda recipe: 'recipe')
        logic = ModuleType('logic')
        logic.feature_recipe = recipe
        module = load('wrap_test', 'logic/custom_feature.py',
                      {'adsk': adsk, 'adsk.core': adsk.core, 'adsk.fusion': adsk.fusion,
                       'logic': logic, 'logic.airfoil_frame': NS(chord_frame=Mock(), sketch_points=Mock())})
        module._definition = object()
        foreign = object()
        support = object()
        feature = NS(nativeObject=None, attributes=NS(add=Mock()))
        data = NS(addDependency=Mock(return_value=True), setStartAndEndFeatures=Mock(return_value=True))
        collection = NS(createInput=Mock(return_value=data), add=Mock(return_value=feature))
        native = NS(attributes=NS(add=Mock()), parentComponent=NS(features=NS(customFeatures=collection)))
        sketch = NS(nativeObject=native)
        # Fusion may place the new sketch beyond existing operations. The
        # enclosing range must still contain only the actual sketch object.
        history = [support, foreign, native]
        def set_range(first, last):
            feature.features = history[history.index(first):history.index(last) + 1]
            return True
        data.setStartAndEndFeatures.side_effect = set_range
        values = {'file_path': 'foil.dat', 'te_thickness': .01}
        inputs = NS(itemById=lambda key: NS(value=values.get(key), valueOne=.1))
        cache = dict(upper_cp_raw=[1, 2], lower_cp_raw=[1, 2], enforce_g3=False, enforce_g2=True)
        module.wrap(sketch, object(), inputs, cache, 0, False)
        self.assertEqual(feature.features, [native])
        data.setStartAndEndFeatures.assert_called_once_with(native, native)


class RecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        adsk = api_stub()
        cls.recipe = load('recipe_test', 'logic/feature_recipe.py',
                          {'adsk': adsk, 'adsk.core': adsk.core})
        x = (1 - np.cos(np.linspace(0, np.pi, 81))) / 2
        y = 0.6 * (0.2969 * np.sqrt(x) - 0.126 * x - 0.3516 * x**2
                   + 0.2843 * x**3 - 0.1036 * x**4)
        points = list(zip(x[::-1], y[::-1])) + list(zip(x[1:], -y[1:]))
        cls.dat = 'NACA 0012\n' + '\n'.join(f'{a:.10f} {b:.10f}' for a, b in points)
        cls.values = dict(te=0.02, smoothness=0.1, upper_count=8, lower_count=8, continuity=1)

    def test_embedded_source_survives_deleted_original_and_refits(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'foil.dat'
            path.write_text(self.dat)
            recipe = dict(self.recipe.read_source(path), schema=1, rotation=0, flip=False)
        recipe = self.recipe.decode(self.recipe.encode(recipe))
        first = self.recipe.fit(recipe, self.values, 10)
        changed = self.recipe.fit(recipe, dict(self.values, te=0.04), 10)
        again = self.recipe.fit(recipe, self.values, 10)
        self.assertEqual(first[0].shape, (8, 2))
        self.assertAlmostEqual(np.linalg.norm(first[0][-1] - first[3][-1]) * 10, 0.02, places=6)
        self.assertAlmostEqual(np.linalg.norm(changed[0][-1] - changed[3][-1]) * 10, 0.04, places=6)
        np.testing.assert_allclose(first[0], again[0])
        np.testing.assert_allclose(first[3], again[3])

    def test_invalid_parameters_rejected_before_fitting(self):
        for change in (dict(te=-1), dict(upper_count=4.5), dict(lower_count=20),
                       dict(continuity=4), dict(smoothness=float('nan'))):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.recipe.validate(dict(self.values, **change), 10)
        with self.assertRaises(ValueError):
            self.recipe.validate(self.values, 0)

    def test_unknown_schema_rejected(self):
        with self.assertRaises(ValueError):
            self.recipe.decode('{"schema": 99, "dat": "data"}')

    def test_recompute_cache_uses_shape_inputs_and_isolates_returned_arrays(self):
        self.recipe._fit_cached.cache_clear()
        recipe = dict(dat=self.dat, schema=1, rotation=0, flip=False)
        first = self.recipe.fit(recipe, self.values, 10)
        original = first[0].copy()
        first[0][:] = 123
        repeated = self.recipe.fit(dict(recipe, rotation=1, filename='renamed.dat'), self.values, 10)
        np.testing.assert_allclose(repeated[0], original)
        self.assertEqual(self.recipe._fit_cached.cache_info().misses, 1)
        self.assertEqual(self.recipe._fit_cached.cache_info().hits, 1)
        # Changes to every numerical input and to the embedded data must refit.
        with patch.object(self.recipe, 'BSplineProcessor', wraps=self.recipe.BSplineProcessor) as processor:
            for change in (dict(te=0.04), dict(smoothness=0.2), dict(upper_count=9),
                           dict(lower_count=9), dict(continuity=2)):
                self.recipe.fit(recipe, dict(self.values, **change), 10)
            self.recipe.fit(recipe, self.values, 20)
            self.recipe.fit(dict(recipe, dat=self.dat.replace('NACA 0012', 'Renamed')), self.values, 10)
            self.assertEqual(processor.call_count, 7)
        self.assertEqual(self.recipe._fit_cached.cache_info().maxsize, 64)

    def test_common_fit_data_matches_recompute_without_file_io(self):
        self.recipe._load_source.cache_clear()
        self.recipe._fit_cached.cache_clear()
        recipe = dict(dat=self.dat, schema=1)
        for continuity in (1, 2, 3):
            values = dict(self.values, upper_count=7, lower_count=9, continuity=continuity)
            with patch('builtins.open', side_effect=AssertionError('Embedded fit must stay in memory')):
                preview = self.recipe.fit_data(recipe, values, 10)
                geometry = self.recipe.fit(recipe, values, 10)
            self.assertEqual((preview['degree_u'], preview['degree_l']), (6, 8))
            self.assertEqual(preview['fit_result'].achieved_continuity, continuity)
            np.testing.assert_array_equal(preview['upper_cp_raw'], geometry[0])
            np.testing.assert_array_equal(preview['lower_cp_raw'], geometry[3])
            preview['upper_cp_raw'][:] = 123
            np.testing.assert_array_equal(self.recipe.fit(recipe, values, 10)[0], geometry[0])

    def test_failed_fit_is_rejected_and_not_cached(self):
        from airfoil_fit import FitResult
        self.recipe._fit_cached.cache_clear()
        recipe = dict(dat=self.dat, schema=1)
        failed = FitResult(False, 2, None, 'Iteration limit')
        values = dict(self.values, continuity=2)
        with patch.object(self.recipe.BSplineProcessor, 'fit_bspline', return_value=failed):
            with self.assertRaisesRegex(self.recipe.AirfoilFitError, 'G2.*Iteration limit'):
                self.recipe.fit(recipe, values, 10)
        self.assertEqual(self.recipe._fit_cached.cache_info().currsize, 0)
        self.assertEqual(self.recipe.fit(recipe, values, 10)[0].shape, (8, 2))


class FitPreviewIntegrationTests(unittest.TestCase):
    def test_preview_calls_common_fitter_and_preserves_cache_on_failure(self):
        from logic import feature_recipe
        feature_recipe._fit_cached.cache_clear()
        adsk = api_stub()
        app = NS(log=Mock(), userInterface=NS(messageBox=Mock()),
                 activeProduct=NS(unitsManager=NS(defaultLengthUnits='mm')))
        adsk.core.Application = NS(get=lambda: app)
        adsk.core.Vector3D = NS(create=lambda *args: NS())
        adsk.fusion.Design = NS(cast=lambda obj: obj)
        state = NS(preview_graphics=None, needs_refit=True, fit_cache={}, rotation_state=0,
                   flip_orientation=False, current_cp_count_upper=7, current_cp_count_lower=9)
        logic = ModuleType('logic')
        logic.state, logic.feature_recipe, logic.custom_feature = state, feature_recipe, NS()
        render = Mock()
        line = NS(parentSketch=NS())
        controls = dict(chord_line=NS(selectionCount=1, selection=lambda _: NS(entity=line)),
                        te_thickness=NS(value=.02), smoothness_input=NS(valueOne=.001),
                        continuity_level=NS(selectedItem=NS(name='G2')),
                        initial_cp_count=NS(value=10))
        modules = {
            'adsk': adsk, 'adsk.core': adsk.core, 'adsk.fusion': adsk.fusion, 'logic': logic,
            'logic.airfoil_frame': NS(chord_frame=lambda *args: (NS(getCell=lambda *args: 0), 10)),
            'logic.timeline_insertion': NS(TimelineInsertion=Mock(), TimelineInsertionError=RuntimeError),
            'logic.preview_renderer': NS(render_preview=render),
            'utils.fusion_geometry_helper': NS(create_fusion_spline=Mock()),
            'utils.sketch_plane_helper': NS(AirfoilPlaneError=ValueError, resolve_airfoil_plane=Mock(), add_airfoil_sketch=Mock()),
        }
        module = load('preview_fit_integration', 'logic/fitter.py', modules)
        x = (1 - np.cos(np.linspace(0, np.pi, 61))) / 2
        y = .6 * (.2969*np.sqrt(x)-.126*x-.3516*x*x+.2843*x**3-.1036*x**4)
        points = list(zip(x[::-1], y[::-1])) + list(zip(x[1:], -y[1:]))
        dat = 'foil\n' + '\n'.join(f'{a:.12f} {b:.12f}' for a,b in points)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'foil.dat'
            path.write_text(dat)
            controls['file_path'] = NS(value=str(path))
            inputs = NS(itemById=controls.get)
            with patch.object(feature_recipe, 'fit_data', wraps=feature_recipe.fit_data) as shared:
                self.assertTrue(module.run_fitter(inputs, True, initialize_te=False))
                shared.assert_called_once()
            render.assert_called_once()
            geometry = feature_recipe.fit(dict(dat=dat), dict(te=.02, smoothness=.001,
                                          upper_count=7, lower_count=9, continuity=2), 10)
            np.testing.assert_array_equal(state.fit_cache['upper_cp_raw'], geometry[0])
            previous = state.fit_cache
            state.needs_refit = True
            render.reset_mock()
            with patch.object(feature_recipe, 'fit_data', side_effect=feature_recipe.AirfoilFitError('G2 failed')):
                self.assertFalse(module.run_fitter(inputs, True, initialize_te=False))
            render.assert_not_called()
            self.assertIs(state.fit_cache, previous)
            self.assertTrue(state.needs_refit)
            app.log.assert_called_with('G2 failed')


class PreviewTests(unittest.TestCase):
    def test_file_replacement_in_edit_preserves_te_and_counts(self):
        adsk = api_stub()
        adsk.core.DialogResults = NS(DialogOK=1)
        dialog = NS(showOpen=lambda: 1, filename='replacement.dat')
        adsk.core.Application = NS(get=lambda: NS(userInterface=NS(createFileDialog=lambda: dialog)))
        logic = ModuleType('logic')
        logic.state = NS(fit_cache={'old': True}, current_cp_count_upper=9,
                         current_cp_count_lower=11, needs_refit=False)
        controls = dict(file_path=NS(value='original.dat'), select_file=NS(text='original'),
                        te_thickness=NS(value=0.04), chord_line=NS(selectionCount=0))
        inputs = NS(itemById=controls.get)
        module = load('handlers_test', 'ui/handlers.py', {
            'adsk': adsk, 'adsk.core': adsk.core, 'adsk.fusion': adsk.fusion,
            'logic': logic, 'logic.fitter': NS(run_fitter=Mock()),
            'ui.dialog': NS(create_ui_inputs=Mock())})
        module.AirfoilSplineCommandInputChangedHandler(preserve_fit_settings=True).handle(
            None, inputs, 'select_file')
        self.assertEqual(controls['file_path'].value, 'replacement.dat')
        self.assertEqual(controls['te_thickness'].value, 0.04)
        self.assertEqual(logic.state.current_cp_count_upper, 9)
        self.assertEqual(logic.state.current_cp_count_lower, 11)
        self.assertEqual(logic.state.fit_cache, {})

    def test_curves_and_handles_are_graphics_only(self):
        adsk = api_stub()
        log = Mock()
        adsk.core.Application = NS(get=lambda: NS(log=log))
        adsk.core.Point3D = NS(create=lambda *xyz: xyz)
        adsk.core.Color = NS(create=lambda *rgba: rgba)
        adsk.core.NurbsCurve3D = NS(createNonRational=Mock(side_effect=lambda *args: args))
        adsk.fusion.CustomGraphicsCoordinates = NS(create=lambda coords: coords)
        adsk.fusion.CustomGraphicsSolidColorEffect = NS(create=lambda color: color)
        adsk.fusion.CustomGraphicsPointTypes = NS(UserDefinedCustomGraphicsPointType=1)
        adsk.fusion.LineStylePatterns = NS(dashedLineStylePattern=1)
        logic = ModuleType('logic')
        logic.state = NS()
        module = load('preview_test', 'logic/preview_renderer.py',
                      {'adsk': adsk, 'adsk.core': adsk.core, 'adsk.fusion': adsk.fusion,
                       'logic': logic, 'logic.fusion_graphics': NS(draw_error_labels=Mock())})
        # Coordinates have already been transformed into the owning component.
        coords = [1, 2, 3, 4, 5, 6]
        module._get_world_pts = Mock(return_value=coords)
        group = NS(addCurve=Mock(side_effect=lambda curve: NS()),
                   addLines=Mock(side_effect=lambda *args: NS()),
                   addPointSet=Mock(return_value=NS()))
        cp = [[0, 0], [1, 0]]
        cache = dict(upper_knots=[0, 0, 1, 1], lower_knots=[0, 0, 1, 1], degree_u=1, degree_l=1)
        module.draw_airfoil_curves(group, cp, cp, cache, 10, None)
        # An object with no sketch geometry APIs proves handles need no sketch.
        module.draw_control_polygon(group, cp, cp, 10, None, object(), cp, cp)
        self.assertEqual(group.addCurve.call_count, 2)
        self.assertEqual(group.addCurve.call_args.args[0][0], [(1, 2, 3), (4, 5, 6)])
        self.assertEqual(group.addPointSet.call_args.args[0], coords + coords)
        log.assert_not_called()


class Point:
    def __init__(self, y):
        self.y = y

    def copy(self):
        return Point(self.y)

    def distanceTo(self, other):
        return abs(self.y - other.y)

    def vectorTo(self, other):
        return other.y - self.y


class SketchPoint:
    def __init__(self, y):
        self.geometry = Point(y)

    def move(self, delta):
        self.geometry.y += delta
        return True


def attributes(role):
    return NS(itemByName=lambda group, key: NS(value=role) if key == 'role' else None)


class RecomputeTests(unittest.TestCase):
    def setUp(self):
        adsk = api_stub()
        adsk.core.NurbsCurve3D = NS(createNonRational=lambda pts, degree, knots, closed: pts)
        self.recipe = NS(fit=Mock(return_value=([Point(0.02)], [0, 1], 1,
                                                [Point(-0.02)], [0, 1], 1)))
        frame = NS(chord_frame=Mock(return_value=(object(), 10)),
                   sketch_points=lambda pts, *args: pts)
        logic = ModuleType('logic')
        logic.feature_recipe = self.recipe
        self.module = load('custom_feature_test', 'logic/custom_feature.py',
                           {'adsk': adsk, 'adsk.core': adsk.core, 'adsk.fusion': adsk.fusion,
                            'logic': logic, 'logic.airfoil_frame': frame})
        self.upper = NS(attributes=attributes('upper'), geometry='original upper',
                        replaceGeometry=Mock(return_value=True))
        self.lower = NS(attributes=attributes('lower'), geometry='original lower',
                        replaceGeometry=Mock(return_value=True))
        self.connector = NS(attributes=attributes('trailing'), startSketchPoint=SketchPoint(0.01),
                            endSketchPoint=SketchPoint(-0.01), deleteMe=Mock(return_value=True))
        self.sketch = NS(attributes=attributes('output'), nativeObject=None,
                         sketchCurves=NS(sketchFixedSplines=[self.upper, self.lower],
                                         sketchLines=[self.connector]))
        self.line = NS(assemblyContext=None)
        self.feature = NS(features=[self.sketch], dependencies=NS(itemById=lambda _: NS(entity=self.line)))

    def update(self):
        self.module.update(self.feature, dict(rotation=0, flip=False), {})

    def group_entities(self, indices):
        entries = {}
        timeline = NS(item=lambda index: entries[index])
        members = []
        for index in indices:
            entity = NS(nativeObject=None, timelineObject=NS(index=index, parentTimeline=timeline))
            entries[index] = NS(entity=entity)
            members.append(entity)
        return members, entries

    def test_support_group_accepts_only_contiguous_owned_members(self):
        for indices in ([3, 4], [3, 4, 5]):
            with self.subTest(indices=indices):
                members, _ = self.group_entities(indices)
                self.assertIs(self.module._group_start(members[-1], members[:-1]), members[0])

    def test_support_group_rejects_intervening_foreign_operation(self):
        members, entries = self.group_entities([3, 5])
        entries[4] = NS(entity=object())
        with self.assertRaisesRegex(RuntimeError, 'not contiguous'):
            self.module._group_start(members[-1], members[:-1])

    def test_support_group_rejects_index_that_resolves_to_foreign_entity(self):
        members, entries = self.group_entities([3, 4])
        entries[3] = NS(entity=object())
        with self.assertRaisesRegex(RuntimeError, 'not contiguous'):
            self.module._group_start(members[-1], members[:-1])

    def test_support_group_normalizes_occurrence_proxy(self):
        members, _ = self.group_entities([3, 4])
        proxy = NS(nativeObject=members[0])
        self.assertIs(self.module._group_start(members[-1], [proxy]), members[0])

    def test_read_only_check_detects_change_without_mutating(self):
        self.assertTrue(self.module.update(self.feature, dict(rotation=0, flip=False), {}, apply=False))
        self.upper.replaceGeometry.assert_not_called()
        self.lower.replaceGeometry.assert_not_called()
        self.assertEqual(self.connector.startSketchPoint.geometry.y, 0.01)

    def test_read_only_check_detects_connector_only_change_and_noop(self):
        self.module._same_curve = Mock(return_value=True)
        self.assertTrue(self.module.update(self.feature, dict(rotation=0, flip=False), {}, apply=False))
        self.connector.startSketchPoint.geometry.y = 0.02
        self.connector.endSketchPoint.geometry.y = -0.02
        self.assertFalse(self.module.update(self.feature, dict(rotation=0, flip=False), {}))
        self.upper.replaceGeometry.assert_not_called()

    def test_compute_queues_without_mutating_and_respects_history(self):
        self.feature.nativeObject = None
        self.feature.entityToken = 'af'
        self.feature.attributes = NS(itemByName=Mock(return_value=object()))
        self.module.update = Mock(return_value=True)
        self.module._deferred = NS(history_replay=False, queue=Mock())
        self.module.Compute().notify(NS(customFeature=self.feature))
        self.module.update.assert_called_once_with(self.feature, apply=False)
        self.module._deferred.queue.assert_called_once_with(self.feature)
        self.assertFalse(self.module._busy)
        self.module._deferred.history_replay = True
        self.module.Compute().notify(NS(customFeature=self.feature))
        self.assertEqual(self.module.update.call_count, 1)

    def test_proxy_reads_recipe_and_roles_from_native_attributes(self):
        native = NS(attributes=NS(itemByName=lambda group, name: NS(value='stored')))
        proxy = NS(nativeObject=native, attributes=NS(itemByName=Mock(return_value=None)))
        self.recipe.decode = lambda text: text
        self.assertEqual(self.module.read_recipe(proxy), 'stored')
        self.assertEqual(self.module._role(proxy), 'stored')
        proxy.attributes.itemByName.assert_not_called()

    def highlight_fixture(self):
        self.feature.definition = NS(id=self.module.DEFINITION_ID)
        self.module.adsk.fusion.CustomFeature = NS(cast=lambda obj: obj if obj is self.feature else None)
        self.module.adsk.core.Color = NS(create=lambda *rgba: rgba)
        self.module.adsk.fusion.CustomGraphicsSolidColorEffect = NS(create=lambda color: color)
        for curve in (self.upper, self.lower, self.connector):
            curve.worldGeometry = object()
        group = NS(isValid=True, deleteMe=Mock(), addCurve=Mock(side_effect=lambda geometry: NS()))
        self.sketch.parentComponent = NS(customGraphicsGroups=NS(add=Mock(return_value=group)))
        selection = NS(add=Mock(), removeByEntity=Mock())
        return self.module.SelectionHighlight(NS(activeSelections=selection)), group, selection

    def test_timeline_highlight_keeps_feature_as_the_only_selection(self):
        handler, group, selection = self.highlight_fixture()
        handler.notify(NS(currentSelection=[NS(entity=self.feature)]))
        self.assertEqual(group.addCurve.call_count, 3)
        group.addCurve.assert_any_call(self.upper.worldGeometry)
        self.assertFalse(group.isSelectable)
        selection.add.assert_not_called()
        selection.removeByEntity.assert_not_called()
        self.module.ClearSelectionHighlight(handler).notify(NS())
        group.deleteMe.assert_called_once()
        self.assertEqual(handler.groups, [])

    def test_timeline_highlight_clears_overlay_on_deselection(self):
        handler, group, selection = self.highlight_fixture()
        handler.notify(NS(currentSelection=[NS(entity=self.feature)]))
        handler.notify(NS(currentSelection=[]))
        group.deleteMe.assert_called_once()
        self.assertEqual(handler.groups, [])
        selection.add.assert_not_called()
        selection.removeByEntity.assert_not_called()

    def test_thickness_edit_reuses_both_splines_and_connector(self):
        self.update()
        self.upper.replaceGeometry.assert_called_once()
        self.lower.replaceGeometry.assert_called_once()
        self.assertEqual(self.connector.startSketchPoint.geometry.y, 0.02)
        self.assertEqual(self.connector.endSketchPoint.geometry.y, -0.02)
        self.connector.deleteMe.assert_not_called()

    def test_rejected_second_spline_restores_originals(self):
        self.lower.replaceGeometry.side_effect = [False, True]
        with self.assertRaisesRegex(RuntimeError, 'replaceGeometry'):
            self.update()
        self.assertEqual(self.upper.replaceGeometry.call_args.args, ('original upper',))
        self.assertEqual(self.lower.replaceGeometry.call_args.args, ('original lower',))

    def test_failed_fit_never_changes_geometry(self):
        self.recipe.fit.side_effect = ValueError('invalid input')
        with self.assertRaises(ValueError):
            self.update()
        self.upper.replaceGeometry.assert_not_called()
        self.lower.replaceGeometry.assert_not_called()

    def test_connector_failure_restores_endpoint_already_moved(self):
        self.connector.endSketchPoint.move = Mock(return_value=False)
        with self.assertRaisesRegex(RuntimeError, 'connector'):
            self.update()
        self.assertEqual(self.connector.startSketchPoint.geometry.y, 0.01)
        self.assertEqual(self.upper.replaceGeometry.call_args.args, ('original upper',))

    def test_moved_component_uses_proxy_only_for_coordinate_conversion(self):
        self.line.assemblyContext = object()
        proxy = object()
        self.sketch.createForAssemblyContext = Mock(return_value=proxy)
        points = self.module.sketch_points
        self.module.sketch_points = Mock(side_effect=points)
        self.update()
        self.sketch.createForAssemblyContext.assert_called_once_with(self.line.assemblyContext)
        for call in self.module.sketch_points.call_args_list:
            self.assertIs(call.args[-1], proxy)
        self.upper.replaceGeometry.assert_called_once()

    def test_shared_edit_dialog_hydrates_previews_and_cancels_without_update(self):
        state = NS(reset_state=Mock())
        logic = ModuleType('logic')
        logic.state = state
        shared = NS(handle=Mock(), notify=Mock())
        preview = Mock(return_value=True)
        controls = {name: NS(isEnabled=True) for name in
                    ('chord_line', 'rotate_airfoil', 'file_path', 'select_file',
                     'te_thickness', 'smoothness_input', 'continuity_level')}
        controls['chord_line'].addSelection = Mock()
        controls['te_thickness'].maximumValue = 10
        continuity_items = [NS(isSelected=False) for _ in range(3)]
        controls['continuity_level'].listItems = NS(item=lambda i: continuity_items[i])
        command = NS(commandInputs=NS(itemById=controls.get),
                     activate=Mock(), inputChanged=Mock(), executePreview=Mock(),
                     execute=Mock(), destroy=Mock(), beginStep=Mock(), doExecutePreview=Mock())
        command.doExecutePreview.side_effect = lambda: command.executePreview.add.call_args.args[0].notify(NS())
        session = self.module.EditSession.__new__(self.module.EditSession)
        session.command = command
        session.feature = self.feature
        session.feature.parameters = NS(itemById=lambda _: NS(expression='0.25 mm'))
        session.feature.timelineObject = NS(rollTo=Mock())
        session.recipe = dict(rotation=3, flip=True, filename='embedded.dat')
        session.values = dict(te=0.025, smoothness=0.04, upper_count=9, lower_count=11, continuity=3)
        session.path = 'temporary/embedded.dat'
        session.sketch = NS(isLightBulbOn=True)
        session.visible = True
        session.ready = False
        session.marker = None
        session.handlers = []
        session.design = NS(timeline=NS(markerPosition=12))
        session.directory = NS(cleanup=Mock())
        self.module.update = Mock()
        with patch.dict(sys.modules, {
                'logic': logic, 'logic.fitter': NS(run_fitter=preview),
                'ui.handlers': NS(AirfoilSplineCommandInputChangedHandler=lambda **kwargs: shared,
                                  update_cp_count_labels=Mock())}):
            session.connect()
            command.activate.add.call_args.args[0].notify(NS(command=command))
            self.assertTrue(session.ready)
            self.assertEqual(state.rotation_state, 3)
            self.assertTrue(state.flip_orientation)
            self.assertEqual((state.current_cp_count_upper, state.current_cp_count_lower), (9, 11))
            self.assertEqual(controls['te_thickness'].expression, '0.25 mm')
            self.assertEqual(controls['smoothness_input'].valueOne, 0.04)
            self.assertTrue(continuity_items[2].isSelected)
            self.assertFalse(controls['chord_line'].isEnabled)
            self.assertFalse(controls['rotate_airfoil'].isEnabled)
            self.assertFalse(session.sketch.isLightBulbOn)
            command.doExecutePreview.assert_called_once()
            session.feature.timelineObject.rollTo.assert_not_called()
            preview.assert_called_once()
            preview.reset_mock()
            preview_args = NS()
            command.executePreview.add.call_args.args[0].notify(preview_args)
            preview.assert_called_once_with(command.commandInputs, True, initialize_te=False)
            self.assertFalse(preview_args.isValidResult)
            self.module.update.assert_not_called()
            changed = command.inputChanged.add.call_args.args[0]
            changed.notify(NS(input=NS(id='rotate_airfoil')))
            shared.notify.assert_not_called()
            changed.notify(NS(input=NS(id='flip_airfoil')))
            shared.notify.assert_called_once()
            session.design.timeline.markerPosition = 4
            command.destroy.add.call_args.args[0].notify(NS())
            self.assertEqual(session.design.timeline.markerPosition, 12)
            self.assertTrue(session.sketch.isLightBulbOn)
            session.directory.cleanup.assert_called_once()
            self.module.update.assert_not_called()

    def test_unchanged_edit_does_not_touch_model_or_parameters(self):
        recipe = dict(dat='embedded', rotation=1, flip=False, filename='foil.dat')
        values = dict(te=0.02)
        parameter = NS(expression='0.2 mm')
        feature = NS(parameters=NS(itemById=lambda _: parameter), attributes=NS(add=Mock()), name='User name')
        self.recipe.PARAMETERS = [('te', 'TE', 'mm')]
        self.module.update = Mock()
        self.module.apply_edit(feature, recipe, values, dict(recipe), dict(values), '0.2 mm')
        self.module.update.assert_not_called()
        feature.attributes.add.assert_not_called()
        self.assertEqual(feature.name, 'User name')

    def test_equal_curve_check_preserves_parameter_direction(self):
        curve = NS(degree=1, isClosed=False, isPeriodic=False, isRational=False,
                   controlPoints=[Point(0), Point(1)], knots=[0, 0, 1, 1])
        same = NS(**vars(curve))
        self.assertTrue(self.module._same_curve(curve, same))
        same.controlPoints = [Point(1), Point(0)]
        self.assertFalse(self.module._same_curve(curve, same))



if __name__ == '__main__':
    unittest.main()
