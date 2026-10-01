"""Offline placement contracts using numeric transforms, not mocked answers."""
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import unittest
import numpy as np
from test_custom_feature import api_stub, load


class Vector:
    def __init__(self, x, y, z): self.xyz = np.array([x,y,z], dtype=float)
    @property
    def length(self): return np.linalg.norm(self.xyz)
    def normalize(self): self.xyz /= self.length
    def crossProduct(self, other): return Vector(*np.cross(self.xyz, other.xyz))
    def scaleBy(self, factor): self.xyz *= factor
    def copy(self): return Vector(*self.xyz)
    def add(self, other): self.xyz += other.xyz


class Point(Vector):
    def vectorTo(self, other): return Vector(*(other.xyz-self.xyz))
    def transformBy(self, matrix): self.xyz = (matrix.data @ np.r_[self.xyz, 1])[:3]


class Matrix:
    def __init__(self, data=None): self.data = np.eye(4) if data is None else np.array(data, dtype=float)
    def getCell(self, i, j): return self.data[i,j]
    def transformBy(self, other): self.data = other.data @ self.data
    def setWithCoordinateSystem(self, origin, x, y, z):
        self.data[:3,:3] = np.column_stack([x.xyz,y.xyz,z.xyz])
        self.data[:3,3] = origin.xyz


class PlacementTests(unittest.TestCase):
    def setUp(self):
        adsk = api_stub()
        adsk.core.Vector3D = NS(create=Vector)
        adsk.core.Point3D = NS(create=Point)
        adsk.core.Matrix3D = NS(create=Matrix)
        self.module = load('placement_test', 'logic/airfoil_frame.py',
                           {'adsk':adsk, 'adsk.core':adsk.core})

    def test_rotation_flip_and_chord_scale(self):
        for rotation in range(4):
            for flip in (False, True):
                with self.subTest(rotation=rotation, flip=flip):
                    sketch = NS(transform=Matrix(), assemblyContext=None, modelToSketchSpace=lambda p:p)
                    line = NS(startSketchPoint=NS(worldGeometry=Point(2,3,4)),
                              endSketchPoint=NS(worldGeometry=Point(12,3,4)), parentSketch=sketch)
                    frame, length = self.module.chord_frame(line, rotation, flip)
                    points = self.module.sketch_points([[0,0],[1,0],[.3,.1]], frame, length, sketch)
                    theta = rotation*np.pi/2
                    start = 12 if flip else 2
                    sign = -1 if flip else 1
                    expected = [[start,3,4],[start+sign*10,3,4],
                                [start+sign*3,3+np.cos(theta),4+np.sin(theta)]]
                    np.testing.assert_allclose([p.xyz for p in points], expected, atol=1e-12)
                    self.assertAlmostEqual(length, 10)

    def test_moved_occurrence_roundtrips_into_sketch_coordinates(self):
        # 90-degree rotation about X plus a translation; world normal becomes -Y.
        transform = Matrix([[1,0,0,7],[0,0,-1,11],[0,1,0,13],[0,0,0,1]])
        inverse = np.linalg.inv(transform.data)
        sketch = NS(transform=Matrix(), assemblyContext=NS(transform2=transform),
                    modelToSketchSpace=lambda p: Point(*(inverse @ np.r_[p.xyz,1])[:3]))
        line = NS(startSketchPoint=NS(worldGeometry=Point(7,11,13)),
                  endSketchPoint=NS(worldGeometry=Point(12,11,13)), parentSketch=sketch)
        frame, length = self.module.chord_frame(line, 0, False)
        points = self.module.sketch_points([[0,0],[1,0],[.4,.2]], frame, length, sketch)
        np.testing.assert_allclose([p.xyz for p in points], [[0,0,0],[5,0,0],[2,1,0]], atol=1e-12)

    def test_zero_length_chord_is_rejected(self):
        line = NS(startSketchPoint=NS(worldGeometry=Point(1,2,3)), endSketchPoint=NS(worldGeometry=Point(1,2,3)))
        with self.assertRaisesRegex(ValueError, 'positive length'):
            self.module.chord_frame(line, 0, False)


class SupportTests(unittest.TestCase):
    def setUp(self):
        adsk = api_stub()
        adsk.core.ValueInput = NS(createByReal=lambda x:x)
        self.module = load('support_test', 'utils/sketch_plane_helper.py', {'adsk':adsk,'adsk.core':adsk.core})
        self.source = NS(referencePlane=NS(isValid=True), assemblyContext=None)
        self.root = NS(xYConstructionPlane=object(), xZConstructionPlane=object(), yZConstructionPlane=object())

    def test_half_turn_reuses_source_support(self):
        for rotation in (0,2,4):
            result=self.module.resolve_airfoil_plane(NS(parentSketch=self.source), rotation, None,None,self.root,'foil')
            self.assertIs(result,self.source.referencePlane)

    def test_root_plane_requires_matching_normal_and_offset(self):
        line=NS(parentSketch=self.source, assemblyContext=None)
        self.assertIs(self.module.resolve_airfoil_plane(line,1,NS(x=2,y=0,z=3),NS(x=0,y=-1,z=0),self.root,'foil'), self.root.xZConstructionPlane)
        plane=NS()
        plane_input=NS(setByAngle=Mock(return_value=True))
        planes=NS(createInput=lambda:plane_input, add=Mock(return_value=plane))
        self.source.parentComponent=NS(constructionPlanes=planes)
        result=self.module.resolve_airfoil_plane(line,1,NS(x=2,y=4,z=3),NS(x=0,y=-1,z=0),self.root,'foil')
        self.assertIs(result,plane)
        plane_input.setByAngle.assert_called_once_with(line,-np.pi/2,self.source.referencePlane)
        self.assertFalse(plane.isLightBulbOn)

    def test_rejected_sketch_support_retries_once_with_helper(self):
        helper, output=object(),object()
        operation=Mock(side_effect=[RuntimeError('unsupported sketch'),output])
        with patch.object(self.module,'_create_support_plane',return_value=helper) as create:
            result,support=self.module.with_sketch_support(self.source,self.source,'foil',operation)
        self.assertIs(result,output)
        self.assertIs(support,helper)
        create.assert_called_once()
        self.assertEqual([call.args[0] for call in operation.call_args_list],[self.source,helper])

    def test_retry_veto_prevents_extra_geometry(self):
        with patch.object(self.module,'_create_support_plane') as create:
            with self.assertRaisesRegex(RuntimeError,'already created'):
                self.module.with_sketch_support(self.source,self.source,'foil',Mock(side_effect=RuntimeError('already created')),can_retry=lambda:False)
            create.assert_not_called()

    def test_output_sketch_uses_occurrence_for_creation_and_conversion(self):
        occurrence,proxy=object(),object()
        self.source.assemblyContext=occurrence
        native=NS(assemblyContext=None,createForAssemblyContext=Mock(return_value=proxy))
        sketches=NS(addWithoutEdges=Mock(return_value=native))
        self.source.parentComponent=NS(sketches=sketches)
        result=self.module.add_airfoil_sketch(self.source,self.source.referencePlane,'foil')
        self.assertIs(result,proxy)
        sketches.addWithoutEdges.assert_called_once_with(self.source.referencePlane,occurrence)
        native.createForAssemblyContext.assert_called_once_with(occurrence)


class FusionSplineAdapterTests(unittest.TestCase):
    def test_degree_knots_and_coordinates_are_forwarded_without_resampling(self):
        adsk=api_stub()
        adsk.core.Point3D=NS(create=lambda *xyz:xyz)
        geometry=object()
        create=Mock(return_value=geometry)
        adsk.core.NurbsCurve3D=NS(createNonRational=create)
        module=load('spline_adapter_test','utils/fusion_geometry_helper.py',{'adsk':adsk,'adsk.core':adsk.core})
        spline=NS(isControlPolygonVisible=False)
        add=Mock(return_value=spline)
        sketch=NS(sketchCurves=NS(sketchFixedSplines=NS(addByNurbsCurve=add)))
        cps=np.array([[0.,0.],[0.,1.],[1.,1.],[1.,0.]])
        knots=np.array([0,0,0,0,1,1,1,1])
        self.assertIs(module.create_fusion_spline(sketch,cps,knots,3),spline)
        create.assert_called_once_with([(0.,0.,0),(0.,1.,0),(1.,1.,0),(1.,0.,0)],3,knots.tolist(),False)
        add.assert_called_once_with(geometry)
        self.assertTrue(spline.isControlPolygonVisible)
        create.return_value=None
        add.reset_mock()
        with self.assertRaisesRegex(RuntimeError,'returned None'):
            module.create_fusion_spline(sketch,cps,knots,3)
        add.assert_not_called()
