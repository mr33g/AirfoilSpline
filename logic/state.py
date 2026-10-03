# Global state for the AirfoilSplines add-in
handlers = []
needs_refit = True
fit_cache = {}
rotation_state = 0
flip_orientation = False  # Flip airfoil nose to tail along chord line
preview_graphics = None  # Custom graphics group for control polygon preview
graphics_world_to_local = None  # Transform for graphics when sketch is in sub-component
current_cp_count_upper = None  # Track current control point count to detect changes
current_cp_count_lower = None  # Track current control point count to detect changes
bspline_processor = None  # Store the processor instance for refinement operations

def reset_state():
    """Reset all state variables to their default values."""
    global needs_refit, fit_cache, rotation_state, flip_orientation, preview_graphics, graphics_world_to_local, current_cp_count_upper, current_cp_count_lower, bspline_processor
    needs_refit = True
    fit_cache = {}
    rotation_state = 0
    flip_orientation = False
    graphics_world_to_local = None
    current_cp_count_upper = None
    current_cp_count_lower = None
    bspline_processor = None
    if preview_graphics:
        try:
            preview_graphics.deleteMe()
        except:
            pass
    preview_graphics = None
