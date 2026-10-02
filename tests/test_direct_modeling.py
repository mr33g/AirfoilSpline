"""Execute-path contracts without requiring Fusion's modeling kernel."""
from types import ModuleType, SimpleNamespace as NS
from unittest.mock import Mock, patch
import unittest
import numpy as np
from test_custom_feature import api_stub, load


class Point:
    def __init__(self, x, y, z):
        self.xyz = np.array([x, y, z], dtype=float)
    def transformBy(self, matrix):
        pass
    def distanceTo(self, other):
        return float(np.linalg.norm(self.xyz - other.xyz))
    @property
    def x(self): return self.xyz[0]
    @property
    def y(self): return self.xyz[1]
    @property
    def z(self): return self.xyz[2]


class DirectModelingTests(unittest.TestCase):
    def setup_case(self, parametric=False, gap=.02):
        adsk = api_stub()
        adsk.core.Point3D = NS(create=Point)
        adsk.core.Vector3D = NS(create=lambda *xyz: xyz)
        adsk.fusion.DesignTypes = NS(ParametricDesignType=1, DirectDesignType=0)
        # Deliberately omit timeline in direct mode: even reading it must fail.
        design = NS(designType=int(parametric), rootComponent=object(),
                    unitsManager=NS(defaultLengthUnits='mm'))
        if parametric:
            design.timeline = object()
        adsk.fusion.Design = NS(cast=lambda _: design)
        self.app = NS(activeProduct=design, log=Mock(), userInterface=NS(messageBox=Mock()))
        adsk.core.Application = NS(get=lambda: self.app)
        self.source = NS(parentComponent=NS(constructionPlanes=object()))
        self.line = NS(parentSketch=self.source, startSketchPoint=NS(worldGeometry=Point(0,0,0)))
        controls = dict(chord_line=NS(selectionCount=1, selection=lambda _: NS(entity=self.line)),
            file_path=NS(value='foil.dat'), te_thickness=NS(value=gap),
            continuity_level=NS(selectedItem=NS(name='G2')), initial_cp_count=NS(value=5),
            smoothness_input=NS(valueOne=.001))
        self.inputs = NS(itemById=controls.get)
        self.cache = dict(upper_cp_raw=np.array([[0.,0.],[1.,gap/2]]),
                          lower_cp_raw=np.array([[0.,0.],[1.,-gap/2]]),
                          upper_knots=[0,0,1,1], lower_knots=[0,0,1,1],
                          degree_u=1, degree_l=1, is_sharp=gap == 0)
        self.state = NS(preview_graphics=None, needs_refit=False, fit_cache=self.cache,
                        current_cp_count_upper=5,current_cp_count_lower=5,
                        rotation_state=1,flip_orientation=False)
        self.custom = NS(tag=Mock(), wrap=Mock(return_value=object()))
        self.recipe = NS(read_source=Mock(return_value={'dat':'foil'}),
                         fit_data=Mock(return_value=self.cache), AirfoilFitError=type('AirfoilFitError',(Exception,),{}))
        logic = ModuleType('logic')
        logic.state, logic.custom_feature, logic.feature_recipe = self.state, self.custom, self.recipe
        self.target = NS(modelToSketchSpace=lambda point: point,
                         sketchCurves=NS(sketchLines=NS(addByTwoPoints=Mock(return_value=object()))))
        self.create = Mock(side_effect=[object(),object()])
        self.resolve = Mock(return_value=object())
        self.add_sketch = Mock(return_value=self.target)
        self.insertion = NS(place_new_planes=Mock(), place=Mock(return_value=2), created_planes=[])
        self.timeline = Mock(return_value=self.insertion)
        self.preview = Mock()
        self.module = load('direct_fitter_test','logic/fitter.py',{
            'adsk':adsk,'adsk.core':adsk.core,'adsk.fusion':adsk.fusion,
            'logic':logic,'logic.airfoil_frame':NS(chord_frame=lambda *args:(NS(getCell=lambda i,j:float(i==j)),10)),
            'logic.timeline_insertion':NS(TimelineInsertion=self.timeline,TimelineInsertionError=type('TimelineError',(Exception,),{})),
            'logic.preview_renderer':NS(render_preview=self.preview),
            'utils.fusion_geometry_helper':NS(create_fusion_spline=self.create),
            'utils.sketch_plane_helper':NS(AirfoilPlaneError=type('PlaneError',(Exception,),{}),
                resolve_airfoil_plane=self.resolve,add_airfoil_sketch=self.add_sketch),
            'utils.i18n':NS(t=lambda key,**kw:key)})

    def execute(self):
        with patch.object(self.module.os.path,'exists',return_value=True):
            return self.module.run_fitter(self.inputs,False)

    def test_direct_blunt_output_has_no_timeline_or_feature_metadata(self):
        self.setup_case()
        self.assertTrue(self.execute())
        self.timeline.assert_not_called()
        self.custom.wrap.assert_not_called()
        self.custom.tag.assert_not_called()
        self.assertEqual(self.create.call_count,2)
        self.target.sketchCurves.sketchLines.addByTwoPoints.assert_called_once()
        np.testing.assert_allclose(self.create.call_args_list[0].args[1],[[0,0,0],[10,.1,0]])
        self.resolve.assert_called_once()
        self.add_sketch.assert_called_once_with(self.source,self.resolve.return_value,'foil')

    def test_direct_sharp_output_needs_no_closing_line(self):
        self.setup_case(gap=0)
        self.assertTrue(self.execute())
        self.target.sketchCurves.sketchLines.addByTwoPoints.assert_not_called()

    def test_parametric_output_still_wraps_and_places_feature(self):
        self.setup_case(parametric=True)
        self.assertTrue(self.execute())
        self.timeline.assert_called_once()
        self.assertEqual(self.insertion.place_new_planes.call_count,2)
        self.assertEqual(self.custom.tag.call_count,3)
        self.custom.wrap.assert_called_once()
        self.insertion.place.assert_any_call(self.target,'output sketch')
        self.insertion.place.assert_any_call(self.custom.wrap.return_value,'feature',position=2)

    def test_direct_preview_creates_no_persistent_geometry(self):
        self.setup_case()
        self.assertTrue(self.module.run_fitter(self.inputs,True))
        self.preview.assert_called_once()
        self.resolve.assert_not_called()
        self.create.assert_not_called()
        self.timeline.assert_not_called()

    def test_direct_creation_failure_is_reported_for_command_rollback(self):
        self.setup_case()
        self.create.side_effect = RuntimeError('kernel rejected spline')
        self.assertFalse(self.execute())
        self.app.userInterface.messageBox.assert_called_once()
        self.custom.wrap.assert_not_called()
