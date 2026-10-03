import adsk.core, adsk.fusion
import traceback
import os
from logic import state
import airfoil_splines_settings as config
from utils.i18n import t

def create_ui_inputs(inputs, smoothness_max=0.1):
    """Defines all the UI controls for the Fusion Fitter command."""
    try:
        # 1. Line Selection (Chord Line)
        line_select = inputs.addSelectionInput('chord_line', t("select_chord_line"), t("select_chord_line_help"))
        line_select.addSelectionFilter('SketchLines')
        line_select.setSelectionLimits(1, 1)
        
        # 2. File Selection
        select_file = inputs.addBoolValueInput('select_file', t("select_airfoil"), False, '', True)
        current_file_path = state.fit_cache.get('selected_file_path', '') if isinstance(state.fit_cache, dict) else ''
        if current_file_path:
            select_file.text = os.path.splitext(os.path.basename(current_file_path))[0]
        file_path_input = inputs.addStringValueInput('file_path', t("selected_file"), '')
        file_path_input.isReadOnly = True
        file_path_input.isVisible = False
        

        # 3. Import Settings (Initially Hidden)
        groupImportSettings = inputs.addGroupCommandInput('import_settings', t("import_settings"))
        groupImportSettings.isExpanded = True
        groupImportSettings.isEnabledCheckBoxDisplayed = False
        groupImportSettings.isVisible = False
        groupImportSettingsChildInputs = groupImportSettings.children

        # Rotation Button (Cycles 0, 90, 180, 270) - use rotate.svg icon
        rotate = groupImportSettingsChildInputs.addBoolValueInput('rotate_airfoil', t("turn_90"), False, 'resources/AirfoilSplinesCommand/rotate', False)
        rotate.isVisible = False
        
        # Flip Button (Reverses nose to tail orientation) - use flip.svg icon
        flip = groupImportSettingsChildInputs.addBoolValueInput('flip_airfoil', t("flip"), False, 'resources/AirfoilSplinesCommand/flip', False)
        flip.isVisible = False

        # TE Thickness (Distance Manipulator)
        te_thickness = groupImportSettingsChildInputs.addDistanceValueCommandInput('te_thickness', t("te_thickness"), adsk.core.ValueInput.createByReal(0))
        te_thickness.isVisible = False
        te_thickness.minimumValue = 0
        te_thickness.isMinimumValueInclusive = True
        te_thickness.maximumValue = 10
        te_thickness.isMaximumValueInclusive = True

        # 4. Fitting Parameters (Initially Hidden)
        
        groupFitterSettings = inputs.addGroupCommandInput('fitter_settings', t("fitter_settings"))
        groupFitterSettings.isExpanded = True
        groupFitterSettings.isEnabledCheckBoxDisplayed = False
        groupFitterSettings.isVisible = False
        groupFitterSettingsChildInputs = groupFitterSettings.children

        # Reset row
        reset_button = groupFitterSettingsChildInputs.addBoolValueInput('reset_button', t("reset"), False, 'resources/AirfoilSplinesCommand/reset', False)
        reset_button.isVisible = False

        initial_cp_count = groupFitterSettingsChildInputs.addIntegerSpinnerCommandInput(
            'initial_cp_count', t("initial_cp_count"), config.INITIAL_CP_MIN, config.INITIAL_CP_MAX, 1, config.DEFAULT_CP_COUNT
        )
        initial_cp_count.isVisible = False
        
        # Control Point Count (Integer Slider/Spinner)
        cp_count_upper = groupFitterSettingsChildInputs.addBoolValueInput('cp_count_upper', t("cp_count_upper"), False, 'resources/AirfoilSplinesCommand/add', False)
        cp_count_upper.text = f'  {state.current_cp_count_upper if state.current_cp_count_upper is not None else config.DEFAULT_CP_COUNT}'
        cp_count_upper.isVisible = False
        cp_count_lower = groupFitterSettingsChildInputs.addBoolValueInput('cp_count_lower', t("cp_count_lower"), False, 'resources/AirfoilSplinesCommand/add', False)
        cp_count_lower.text = f'  {state.current_cp_count_lower if state.current_cp_count_lower is not None else config.DEFAULT_CP_COUNT}'
        cp_count_lower.isVisible = False

        # Smoothness penalty
        smoothness = groupFitterSettingsChildInputs.addFloatSliderCommandInput('smoothness_input', t("smoothness_penalty"), "", 0, smoothness_max, False)
        smoothness.valueOne = config.DEFAULT_SMOOTHNESS_PENALTY
        smoothness.isVisible = False

        # Options (Initially Hidden)
        # Continuity dropdown (G1, G2, G3)
        continuity_dropdown = groupFitterSettingsChildInputs.addDropDownCommandInput('continuity_level', t("le_continuity"), adsk.core.DropDownStyles.TextListDropDownStyle)
        continuity_dropdown.listItems.add('G1', False)
        continuity_dropdown.listItems.add('G2', False)
        continuity_dropdown.listItems.add('G3', False)
        continuity_dropdown.listItems[config.DEFAULT_CONTINUITY - 1].isSelected = True
        continuity_dropdown.isVisible = False

        # 5. Curvature Comb (Initially Hidden)
        curvature_comb = inputs.addBoolValueInput('curvature_comb', t("curvature_comb"), True, 'resources/AirfoilSplinesCommand/comb', False)
        curvature_comb.isVisible = False
        # Curvature Comb Settings (Initially Hidden)
        comb_scale = inputs.addFloatSliderCommandInput('comb_scale', t("comb_scale"), "", 0.0001, 0.05, False)
        comb_scale.valueOne = 0.005
        comb_scale.isVisible = False

        comb_density = inputs.addIntegerSliderCommandInput('comb_density', t("comb_density"), 10, 500, False)
        comb_density.valueOne = 200
        comb_density.isVisible = False

        raw = inputs.addBoolValueInput('import_raw', t("show_input_data"), True, '', False)
        raw.isVisible = False

    except Exception as e:
        app = adsk.core.Application.get()
        app.userInterface.messageBox(t("ui_creation_failed", error=traceback.format_exc()))
