import adsk.core, adsk.fusion
import os
import traceback
import numpy as np
from logic import state
import airfoil_spline_settings as config
from utils.fusion_geometry_helper import create_fusion_spline
from logic.airfoil_frame import chord_frame
from logic import custom_feature, feature_recipe
from logic.timeline_insertion import TimelineInsertion, TimelineInsertionError
from airfoil_fit import bspline_helper
from utils.sketch_plane_helper import AirfoilPlaneError, resolve_airfoil_plane, add_airfoil_sketch
from logic.preview_renderer import render_preview
from utils.i18n import t


def run_fitter(inputs, is_preview, initialize_te=True):
    """Core logic for fitting and geometry generation."""
    app = adsk.core.Application.get()
    
    # Cleanup old preview graphics before recalculating
    if state.preview_graphics:
        try:
            state.preview_graphics.deleteMe()
        except:
            pass
        state.preview_graphics = None
    
    try:
        # 1. Get Selection and Environment
        line_select = inputs.itemById('chord_line')
        if line_select.selectionCount == 0:
            return False
        
        # Check if file is selected
        file_path_input = inputs.itemById('file_path')
        if not file_path_input or not file_path_input.value:
            return False
        
        selected_line = adsk.fusion.SketchLine.cast(line_select.selection(0).entity)
        if not selected_line:
            return False
            
        airfoil_to_world, chord_length = chord_frame(
            selected_line, state.rotation_state, state.flip_orientation)
        y_axis_world = adsk.core.Vector3D.create(
            airfoil_to_world.getCell(0, 1), airfoil_to_world.getCell(1, 1),
            airfoil_to_world.getCell(2, 1))

        # 2. Fitting Logic
        do_new_fit = (state.needs_refit or not state.fit_cache) if is_preview else True

        def selected_initial_cp_count():
            try:
                initial_cp_count = inputs.itemById('initial_cp_count')
                if initial_cp_count:
                    if hasattr(initial_cp_count, 'value'):
                        return max(config.MIN_CP_COUNT, min(config.MAX_CP_COUNT, int(initial_cp_count.value)))
                    if initial_cp_count.selectedItem:
                        return max(config.MIN_CP_COUNT, min(config.MAX_CP_COUNT, int(initial_cp_count.selectedItem.name)))
            except Exception:
                pass
            return config.DEFAULT_CP_COUNT

        if do_new_fit:
            file_path = inputs.itemById('file_path').value
            if not file_path or not os.path.exists(file_path):
                return False

            recipe = feature_recipe.read_source(file_path)
            is_initial_fit = (not state.fit_cache or state.current_cp_count_upper is None
                              or state.current_cp_count_lower is None)
            if is_initial_fit and initialize_te:
                inputs.itemById('te_thickness').value = (
                    feature_recipe.source_te_thickness(recipe['dat']) * chord_length)
            dropdown = inputs.itemById('continuity_level')
            continuity = (int(dropdown.selectedItem.name[1:])
                          if dropdown and dropdown.selectedItem else config.DEFAULT_CONTINUITY)
            initial_count = selected_initial_cp_count()
            values = dict(
                te=inputs.itemById('te_thickness').value,
                smoothness=inputs.itemById('smoothness_input').valueOne,
                upper_count=state.current_cp_count_upper if state.current_cp_count_upper is not None else initial_count,
                lower_count=state.current_cp_count_lower if state.current_cp_count_lower is not None else initial_count,
                continuity=continuity)
            # Publish cache/state only after the exact requested fit succeeds.
            state.fit_cache = feature_recipe.fit_data(recipe, values, chord_length)
            state.current_cp_count_upper = int(values['upper_count'])
            state.current_cp_count_lower = int(values['lower_count'])
            state.needs_refit = False

        upper_cp = state.fit_cache['upper_cp_raw'].copy()
        lower_cp = state.fit_cache['lower_cp_raw'].copy()
        is_sharp = state.fit_cache['is_sharp']

        # 4. Update UI Status
        design = adsk.fusion.Design.cast(app.activeProduct)
        units_mgr = design.unitsManager
        def_units = units_mgr.defaultLengthUnits
        decimals = 2 if 'in' not in def_units else 4
       
        # 5. Render Geometry
        def transform_pts(pts, target):
            is_sketch = hasattr(target, 'modelToSketchSpace')
            transformed = []
            for pt in pts:
                p_world = adsk.core.Point3D.create(pt[0] * chord_length, pt[1] * chord_length, 0)
                p_world.transformBy(airfoil_to_world)
                if is_sketch:
                    p_local = target.modelToSketchSpace(p_world)
                else:
                    # Handle ConstructionPlane using its transform property
                    plane_transform = target.transform.copy()
                    plane_transform.invert()
                    p_world.transformBy(plane_transform)
                    p_local = p_world
                transformed.append([p_local.x, p_local.y, p_local.z])
            return np.array(transformed)

        
        if is_preview:
            target_sketch = selected_line.parentSketch
            
            # Render all preview graphics
            render_preview(
                target_sketch, upper_cp, lower_cp, state.fit_cache,
                chord_length, airfoil_to_world, y_axis_world,
                transform_pts, inputs, is_sharp
            )
        else:
            file_path = inputs.itemById('file_path').value
            sketch_name = os.path.splitext(os.path.basename(file_path))[0] if file_path else "Fitted Airfoil"
            is_parametric = design.designType == adsk.fusion.DesignTypes.ParametricDesignType
            source_sketch = selected_line.parentSketch
            planes = source_sketch.parentComponent.constructionPlanes
            insertion = TimelineInsertion(design.timeline, planes) if is_parametric else None
            # Track newly created supports explicitly; existing support geometry
            # must never become part of the AF-owned group.
            normal_world = adsk.core.Vector3D.create(
                airfoil_to_world.getCell(0, 2), airfoil_to_world.getCell(1, 2),
                airfoil_to_world.getCell(2, 2))
            target_plane = resolve_airfoil_plane(
                selected_line, state.rotation_state, selected_line.startSketchPoint.worldGeometry,
                normal_world, design.rootComponent, sketch_name)
            if insertion is not None:
                insertion.place_new_planes(planes)
            target_sketch = add_airfoil_sketch(source_sketch, target_plane, sketch_name)
            # Sketch creation may create an additional fallback support plane.
            if insertion is not None:
                insertion.place_new_planes(planes)
                output_position = insertion.place(target_sketch, 'output sketch')
            target_sketch.is3D = True
            u_final = transform_pts(upper_cp, target_sketch)
            l_final = transform_pts(lower_cp, target_sketch)
            upper = create_fusion_spline(target_sketch, u_final,
                state.fit_cache['upper_knots'], state.fit_cache['degree_u'])
            lower = create_fusion_spline(target_sketch, l_final,
                state.fit_cache['lower_knots'], state.fit_cache['degree_l'])
            if is_parametric:
                custom_feature.tag(upper, 'upper')
                custom_feature.tag(lower, 'lower')
            u_end = adsk.core.Point3D.create(*u_final[-1])
            l_end = adsk.core.Point3D.create(*l_final[-1])
            if u_end.distanceTo(l_end) > 1e-7:
                trailing = target_sketch.sketchCurves.sketchLines.addByTwoPoints(u_end, l_end)
                if is_parametric:
                    custom_feature.tag(trailing, 'trailing')
            if is_parametric:
                group_position = (insertion.created_planes[0].timelineObject.index
                                  if insertion.created_planes else output_position)
                feature = custom_feature.wrap(target_sketch, selected_line,
                                    inputs, state.fit_cache, state.rotation_state, state.flip_orientation,
                                    supports=insertion.created_planes)
                insertion.place(feature, 'feature', position=group_position)

        return True
    except feature_recipe.AirfoilFitError as exc:
        state.needs_refit = True
        app.log(str(exc))
        if not is_preview:
            app.userInterface.messageBox(str(exc))
        return False
    except TimelineInsertionError as exc:
        app.log(f'AirfoilSpline insertion failed: {traceback.format_exc()}')
        app.userInterface.messageBox(str(exc))
        return False  # Execute handler sets executeFailed to abort the transaction.
    except AirfoilPlaneError as exc:
        app.log(f"AirfoilSpline plane creation failed: {traceback.format_exc()}")
        app.userInterface.messageBox(t("failed_create_airfoil_plane", error=str(exc)))
        return False
    except:
        app.log(f"Error: {traceback.format_exc()}")
        app.userInterface.messageBox(t("generic_error"))
        return False
