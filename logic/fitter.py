import adsk.core, adsk.fusion
import os
import traceback
import numpy as np
from logic import state
from core import config
from core.airfoil_processor import AirfoilProcessor
from core.bspline_processor import BSplineProcessor
from utils.fusion_geometry_helper import create_fusion_spline
from logic.airfoil_frame import chord_frame
from logic import custom_feature
from logic.timeline_insertion import TimelineInsertion, TimelineInsertionError
from utils import bspline_helper
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
        if is_preview:
            state.needs_refit = False

        def calc_max_err(curve, data, exponent):
            """Calculate maximum error against the displayed normalized input."""
            if not curve:
                return 0.0, np.array([0.0, 0.0])

            _, max_error, max_error_idx, _ = bspline_helper.calculate_bspline_fitting_error(
                curve, data, param_exponent=exponent, return_max_error=True
            )
            return max_error, data[max_error_idx].copy()

        def set_error_reference_for_te(cache, te_thickness_normalized):
            upper_ref, lower_ref = bspline_helper.apply_te_thickness_to_reference(
                cache['raw_upper'],
                cache['raw_lower'],
                te_thickness_normalized,
            )
            cache['error_upper'] = upper_ref
            cache['error_lower'] = lower_ref

        def current_te_thickness_normalized():
            te_input = inputs.itemById('te_thickness')
            if not te_input or chord_length <= 1.0e-12:
                return 0.0
            return max(0.0, te_input.value / chord_length)

        def selected_initial_cp_count():
            try:
                initial_cp_count = inputs.itemById('initial_cp_count')
                if initial_cp_count:
                    if hasattr(initial_cp_count, 'value'):
                        return max(4, min(19, int(initial_cp_count.value)))
                    if initial_cp_count.selectedItem:
                        return max(4, min(19, int(initial_cp_count.selectedItem.name)))
            except Exception:
                pass
            return config.DEFAULT_CP_COUNT

        if do_new_fit:
            file_path = inputs.itemById('file_path').value
            if not file_path or not os.path.exists(file_path):
                return False

            # Get continuity level from dropdown
            continuity_dropdown = inputs.itemById('continuity_level')
            enforce_g2 = False
            enforce_g3 = False
            if continuity_dropdown:
                selected_item = continuity_dropdown.selectedItem
                if selected_item:
                    if selected_item.name == 'G2':
                        enforce_g2 = True
                        enforce_g3 = False
                    elif selected_item.name == 'G3':
                        enforce_g2 = True  # G3 requires G2
                        enforce_g3 = True
                    # G1: enforce_g2 = False, enforce_g3 = False (already set)
            
            smoothness = inputs.itemById('smoothness_input').valueOne
            
            processor = AirfoilProcessor(logger_func=lambda msg: None)
            if not processor.load_airfoil_data_and_initialize_model(file_path):
                app.userInterface.messageBox(t("failed_load_airfoil_data"))
                return False
            error_upper_data, error_lower_data = processor.error_reference_data()
            
            # Determine operation type based on state
            is_initial_fit = (
                not state.fit_cache
                or state.current_cp_count_upper is None
                or state.current_cp_count_lower is None
            )

            # Set TE thickness input to match the newly loaded airfoil on initial load.
            # This must also write zero so a previous file's TE value cannot leak.
            if is_initial_fit and initialize_te:
                te_input = inputs.itemById('te_thickness')
                if te_input:
                    te_input.value = processor.get_te_thickness() * chord_length

            te_thickness_normalized = current_te_thickness_normalized()
            fit_upper_data, fit_lower_data = bspline_helper.apply_te_thickness_to_reference(
                processor.upper_data,
                processor.lower_data,
                te_thickness_normalized,
            )
            fit_is_thickened = te_thickness_normalized > 1.0e-9

            initial_cp_count = selected_initial_cp_count()
            cp_count_upper = (
                state.current_cp_count_upper
                if state.current_cp_count_upper is not None
                else initial_cp_count
            )
            cp_count_lower = (
                state.current_cp_count_lower
                if state.current_cp_count_lower is not None
                else initial_cp_count
            )

            bspline = BSplineProcessor()
                
            if is_initial_fit:
                # Initial fit: use fit_bspline with actual UI values
                bspline.smoothing_weight = smoothness
                
                success = bspline.fit_bspline(
                    fit_upper_data, fit_lower_data,
                    num_control_points=(cp_count_upper, cp_count_lower),
                    is_thickened=fit_is_thickened,
                    upper_te_tangent_vector=processor.upper_te_tangent_vector,
                    lower_te_tangent_vector=processor.lower_te_tangent_vector,
                    enforce_g2=enforce_g2, enforce_g3=enforce_g3,
                    single_span=True
                )
                if not success: 
                    app.userInterface.messageBox(t("failed_fit_airfoil"))
                    return False
                
                # Store processor and CP count in state
                state.current_cp_count_upper = cp_count_upper
                state.current_cp_count_lower = cp_count_lower
                
            else:
                # Refinement: add or remove control points
                bspline.smoothing_weight = smoothness
                bspline.enforce_g2 = enforce_g2
                bspline.enforce_g3 = enforce_g3 if enforce_g2 else False
                
                current_cp_upper = state.current_cp_count_upper
                current_cp_lower = state.current_cp_count_lower
                cp_diff_upper = cp_count_upper - current_cp_upper
                cp_diff_lower = cp_count_lower - current_cp_lower
                
                # Save current state to fit_cache before refinement (so we can restore when removing)
                # This preserves the state before we modify it
                if bspline.is_fitted():
                    state.fit_cache['upper_cp_raw'] = bspline.upper_control_points.copy()
                    state.fit_cache['lower_cp_raw'] = bspline.lower_control_points.copy()
                    state.fit_cache['upper_knots'] = bspline.upper_knot_vector.copy() if bspline.upper_knot_vector is not None else None
                    state.fit_cache['lower_knots'] = bspline.lower_knot_vector.copy() if bspline.lower_knot_vector is not None else None
                    state.fit_cache['degree_u'] = bspline.degree_upper
                    state.fit_cache['degree_l'] = bspline.degree_lower
                    state.fit_cache['is_sharp'] = bspline.is_sharp_te
                
                def add_control_points(cp_diff, surface):
                    # Adding control points: insert knots at max error locations
                    for i in range(cp_diff):
                        success = bspline.insert_knot_at_max_error(surface, single_span=True)
                        if not success:
                            app.userInterface.messageBox(t("failed_insert_knot", surface=surface))
                            return False
                
                def remove_control_points(cp_diff, surface):
                    # Removing control points: re-fit with new desired count for the changed surface
                    # Keep the other surface's current count unchanged
                    if surface == 'upper':
                        target_upper = cp_count_upper  # New desired count
                        target_lower = current_cp_lower  # Keep current
                    else:  # lower
                        target_upper = current_cp_upper  # Keep current
                        target_lower = cp_count_lower  # New desired count
                    
                    success = bspline.fit_bspline(
                        fit_upper_data, fit_lower_data,
                        num_control_points=(target_upper, target_lower),
                        is_thickened=fit_is_thickened,
                        upper_te_tangent_vector=processor.upper_te_tangent_vector,
                        lower_te_tangent_vector=processor.lower_te_tangent_vector,
                        enforce_g2=enforce_g2, enforce_g3=enforce_g3,
                        single_span=True
                    )
                    if not success:
                        app.userInterface.messageBox(t("failed_refit_surface", surface=surface))
                        return False
                    # Update state for the changed surface
                    if surface == 'upper':
                        state.current_cp_count_upper = cp_count_upper
                    else:
                        state.current_cp_count_lower = cp_count_lower
                    return True
                
                # Handle upper surface changes
                if cp_diff_upper > 0:
                    add_control_points(cp_diff_upper, 'upper')
                    state.current_cp_count_upper = cp_count_upper
                elif cp_diff_upper < 0:
                    remove_control_points(cp_diff_upper, 'upper')
                
                # Handle lower surface changes
                if cp_diff_lower > 0:
                    add_control_points(cp_diff_lower, 'lower')
                    state.current_cp_count_lower = cp_count_lower
                elif cp_diff_lower < 0:
                    remove_control_points(cp_diff_lower, 'lower')
                
                # If both counts are unchanged but other parameters changed, re-fit
                if cp_diff_upper == 0 and cp_diff_lower == 0:
                    bspline.fit_bspline(
                        fit_upper_data, fit_lower_data,
                        num_control_points=(cp_count_upper, cp_count_lower),
                        is_thickened=fit_is_thickened,
                        upper_te_tangent_vector=processor.upper_te_tangent_vector,
                        lower_te_tangent_vector=processor.lower_te_tangent_vector,
                        enforce_g2=enforce_g2, enforce_g3=enforce_g3,
                        single_span=True
                    )
                
                # Update state (only if not already updated in remove_control_points)
                if cp_diff_upper >= 0:
                    state.current_cp_count_upper = cp_count_upper
                if cp_diff_lower >= 0:
                    state.current_cp_count_lower = cp_count_lower
                
            initial_error_upper_data, initial_error_lower_data = (
                bspline_helper.apply_te_thickness_to_reference(
                    error_upper_data,
                    error_lower_data,
                    te_thickness_normalized,
                )
            )
            err_u, max_err_pt_u = calc_max_err(
                bspline.upper_curve,
                initial_error_upper_data,
                bspline.param_exponent_upper,
            )
            err_l, max_err_pt_l = calc_max_err(
                bspline.lower_curve,
                initial_error_lower_data,
                bspline.param_exponent_lower,
            )
            
            state.fit_cache = {
                'upper_cp_raw': bspline.upper_control_points.copy(),
                'lower_cp_raw': bspline.lower_control_points.copy(),
                'upper_knots': bspline.upper_knot_vector, 'lower_knots': bspline.lower_knot_vector,
                'degree_u': bspline.degree_upper, 'degree_l': bspline.degree_lower,
                'is_sharp': bspline.is_sharp_te,
                'err_u': err_u, 'err_l': err_l,
                'max_err_pt_u': max_err_pt_u, 'max_err_pt_l': max_err_pt_l,  # Store coordinates of max deviation points
                'raw_upper': error_upper_data.copy(), 'raw_lower': error_lower_data.copy(),
                'error_upper': initial_error_upper_data.copy(), 'error_lower': initial_error_lower_data.copy(),
                'fit_upper': fit_upper_data.copy(), 'fit_lower': fit_lower_data.copy(),
                'param_exponent_upper': bspline.param_exponent_upper,
                'param_exponent_lower': bspline.param_exponent_lower,
                'te_value': te_thickness_normalized,
                'enforce_g2': enforce_g2,
                'enforce_g3': enforce_g3
            }
            set_error_reference_for_te(state.fit_cache, state.fit_cache['te_value'])

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
            if design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
                raise RuntimeError('AirfoilSpline custom features require design history.')
            source_sketch = selected_line.parentSketch
            planes = source_sketch.parentComponent.constructionPlanes
            insertion = TimelineInsertion(design.timeline, planes)
            # Track newly created supports explicitly; existing support geometry
            # must never become part of the AF-owned group.
            normal_world = adsk.core.Vector3D.create(
                airfoil_to_world.getCell(0, 2), airfoil_to_world.getCell(1, 2),
                airfoil_to_world.getCell(2, 2))
            target_plane = resolve_airfoil_plane(
                selected_line, state.rotation_state, selected_line.startSketchPoint.worldGeometry,
                normal_world, design.rootComponent, sketch_name)
            insertion.place_new_planes(planes)
            target_sketch = add_airfoil_sketch(source_sketch, target_plane, sketch_name)
            # Sketch creation may create an additional fallback support plane.
            insertion.place_new_planes(planes)
            output_position = insertion.place(target_sketch, 'output sketch')
            target_sketch.is3D = True
            u_final = transform_pts(upper_cp, target_sketch)
            l_final = transform_pts(lower_cp, target_sketch)
            upper = create_fusion_spline(target_sketch, u_final,
                state.fit_cache['upper_knots'], state.fit_cache['degree_u'])
            lower = create_fusion_spline(target_sketch, l_final,
                state.fit_cache['lower_knots'], state.fit_cache['degree_l'])
            custom_feature.tag(upper, 'upper')
            custom_feature.tag(lower, 'lower')
            u_end = adsk.core.Point3D.create(*u_final[-1])
            l_end = adsk.core.Point3D.create(*l_final[-1])
            if u_end.distanceTo(l_end) > 1e-7:
                custom_feature.tag(target_sketch.sketchCurves.sketchLines.addByTwoPoints(
                    u_end, l_end), 'trailing')
            group_position = (insertion.created_planes[0].timelineObject.index
                              if insertion.created_planes else output_position)
            feature = custom_feature.wrap(target_sketch, selected_line,
                                inputs, state.fit_cache, state.rotation_state, state.flip_orientation,
                                supports=insertion.created_planes)
            insertion.place(feature, 'feature', position=group_position)

        return True
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
