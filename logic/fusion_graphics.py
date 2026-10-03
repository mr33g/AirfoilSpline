"""
Fusion graphics utilities for airfoil fitting visualization.

This module contains low-level graphics helper functions for transforming vectors,
computing spline normals, and creating text labels in Fusion's coordinate system.
"""

import adsk.core, adsk.fusion
import numpy as np
from airfoil_splines_core import bspline_helper
from logic import state


def transform_vector_2d_to_world(vec_2d, transform_matrix):
    """
    Transform a 2D vector (rotation only, no translation) to world coordinates.
    
    Args:
        vec_2d: 2D vector as numpy array [x, y]
        transform_matrix: Transformation matrix from airfoil space to world space
        
    Returns:
        Vector3D in world coordinates (not normalized)
    """
    # Transform as a point at origin, then subtract transformed origin to get just rotation
    vec_pt = adsk.core.Point3D.create(vec_2d[0], vec_2d[1], 0)
    origin = adsk.core.Point3D.create(0, 0, 0)
    vec_pt.transformBy(transform_matrix)
    origin.transformBy(transform_matrix)
    return adsk.core.Vector3D.create(
        vec_pt.x - origin.x,
        vec_pt.y - origin.y,
        vec_pt.z - origin.z
    )


def compute_spline_normal_world(curve, u_param, airfoil_to_world):
    """
    Compute the spline normal vector in world coordinates at a given parameter value.
    
    Args:
        curve: B-spline curve (scipy.interpolate.BSpline)
        u_param: Parameter value on the curve
        airfoil_to_world: Transformation matrix from airfoil space to world space
        
    Returns:
        Normalized Vector3D in world coordinates, or None if calculation fails
    """
    # Get tangent vector at the parameter value
    tangent = curve.derivative(1)(u_param)
    tangent = bspline_helper.normalize_vector(tangent)
    if tangent is None:
        return None
    
    # Normal is perpendicular to tangent: rotate 90 degrees counterclockwise
    normal_airfoil = np.array([-tangent[1], tangent[0]])
    
    # Transform normal to world coordinates
    normal_world_vec = transform_vector_2d_to_world(normal_airfoil, airfoil_to_world)
    # Transform to component-local space if needed (direction only, no translation)
    if state.graphics_world_to_local:
        normal_world_vec.transformBy(state.graphics_world_to_local)
    normal_world_vec.normalize()
    return normal_world_vec


def create_error_text_label(graphics_group, error_text, marker_point, normal_vec, 
                            offset_distance, font_size=14, view_scale_factor=1.0):
    """
    Create a text label and leader line for an error marker.
    
    Args:
        graphics_group: CustomGraphicsGroup to add the label to
        error_text: Text string to display
        marker_point: Point3D where the error marker is located
        normal_vec: Normalized Vector3D indicating the offset direction
        offset_distance: Distance to offset the text from the marker
        font_size: Font size for the text
        view_scale_factor: View scale factor for the text
        
    Returns:
        Tuple of (text_anchor_point, cg_text_object) or (None, None) if creation fails
    """
    # Calculate offset vector
    offset_vec = normal_vec.copy()
    offset_vec.scaleBy(offset_distance)
    
    # Text anchor position (leader line will terminate here at bottom-left of text)
    text_anchor = adsk.core.Point3D.create(
        marker_point.x + offset_vec.x,
        marker_point.y + offset_vec.y,
        marker_point.z + offset_vec.z
    )
    
    # Create text matrix
    mat = adsk.core.Matrix3D.create()
    mat.translation = adsk.core.Vector3D.create(text_anchor.x, text_anchor.y, text_anchor.z)
    
    # Add text
    cg_text = graphics_group.addText(error_text, 'Arial', font_size, mat)
    if cg_text:
        cg_text.color = adsk.fusion.CustomGraphicsSolidColorEffect.create(adsk.core.Color.create(0, 0, 0, 255))
        billboard = adsk.fusion.CustomGraphicsBillBoard.create(marker_point)
        billboard.billBoardStyle = adsk.fusion.CustomGraphicsBillBoardStyles.ScreenBillBoardStyle
        cg_text.billBoarding = billboard
        cg_text.viewScale = adsk.fusion.CustomGraphicsViewScale.create(view_scale_factor, adsk.core.Point3D.create(0, 0, 0))
        cg_text.depthPriority = 1100
    
    # Draw leader line from marker to text anchor
    line_coords = [
        marker_point.x, marker_point.y, marker_point.z,
        text_anchor.x, text_anchor.y, text_anchor.z
    ]
    cg_coords_line = adsk.fusion.CustomGraphicsCoordinates.create(line_coords)
    cg_line = graphics_group.addLines(cg_coords_line, [0, 1], False)
    if cg_line:
        cg_line.color = adsk.fusion.CustomGraphicsSolidColorEffect.create(adsk.core.Color.create(0, 0, 0, 255))
        cg_line.lineStylePattern = adsk.fusion.LineStylePatterns.continuousLineStylePattern
        cg_line.depthPriority = 1050
    
    return text_anchor, cg_text


def draw_error_labels(graphics_group, upper_curve, lower_curve, u_param_u, u_param_l,
                     max_err_data_pt_u, max_err_data_pt_l, p_world_u, p_world_l,
                     airfoil_to_world, chord_length, y_axis_world, fit_cache):
    """
    Draw error markers and text labels for upper and lower surfaces.
    
    Args:
        graphics_group: CustomGraphicsGroup to add graphics to
        upper_curve: Upper surface B-spline curve
        lower_curve: Lower surface B-spline curve
        u_param_u: Parameter value for upper surface max error point
        u_param_l: Parameter value for lower surface max error point
        max_err_data_pt_u: Data point with max error on upper surface
        max_err_data_pt_l: Data point with max error on lower surface
        p_world_u: World coordinates of upper surface max error point on spline
        p_world_l: World coordinates of lower surface max error point on spline
        airfoil_to_world: Transformation matrix from airfoil space to world space
        chord_length: Chord length for scaling
        y_axis_world: Y-axis vector in world coordinates (for fallback)
        fit_cache: Fit cache dictionary containing error values
    """
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    units_mgr = design.unitsManager
    def_units = units_mgr.defaultLengthUnits
    decimals = 2 if 'in' not in def_units else 4
    
    # Text rendering settings
    font_size = 14
    view_scale_factor = 1.0
    normal_offset = chord_length * 0.03
    
    # Calculate spline normals
    normal_u_world_vec = compute_spline_normal_world(upper_curve, u_param_u, airfoil_to_world)
    if normal_u_world_vec is None:
        normal_u_world_vec = y_axis_world.copy()
        normal_u_world_vec.normalize()
    
    normal_l_world_vec = compute_spline_normal_world(lower_curve, u_param_l, airfoil_to_world)
    if normal_l_world_vec is None:
        normal_l_world_vec = y_axis_world.copy()
        normal_l_world_vec.normalize()
    
    # Create upper error text label
    err_u_text = f"{units_mgr.convert(fit_cache['err_u'] * chord_length, 'cm', def_units):.{decimals}f} {def_units}"
    create_error_text_label(
        graphics_group, err_u_text, p_world_u, normal_u_world_vec,
        normal_offset, font_size, view_scale_factor
    )
    
    # Create lower error text label (inward direction, so negative offset)
    err_l_text = f"{units_mgr.convert(fit_cache['err_l'] * chord_length, 'cm', def_units):.{decimals}f} {def_units}"
    create_error_text_label(
        graphics_group, err_l_text, p_world_l, normal_l_world_vec,
        -normal_offset, font_size, view_scale_factor
    )

