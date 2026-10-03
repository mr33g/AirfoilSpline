import adsk.core, adsk.fusion
import traceback
import math
import os
from ui.dialog import create_ui_inputs
from logic import state
from logic.fitter import run_fitter
import airfoil_splines_settings as config
from utils.i18n import t

def _set_selected_file_button_text(inputs, file_path: str) -> None:
    try:
        select_file = inputs.itemById('select_file')
        if not select_file:
            return
        if file_path:
            select_file.text = os.path.splitext(os.path.basename(file_path))[0]
        else:
            select_file.text = t("select_airfoil")
    except Exception:
        pass


_updating_cp_labels = False


def update_cp_count_labels(inputs):
    """Refresh labels without treating programmatic changes as button clicks."""
    global _updating_cp_labels
    if _updating_cp_labels:
        return
    _updating_cp_labels = True
    try:
        for surface in ('upper', 'lower'):
            button = inputs.itemById('cp_count_' + surface)
            if button:
                count = getattr(state, 'current_cp_count_' + surface)
                text = f'  {count if count is not None else get_initial_cp_count(inputs)}'
                if button.text != text:
                    button.text = text
    finally:
        _updating_cp_labels = False


def get_initial_cp_count(inputs):
    """Return the selected initial control point count."""
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

def reset_fitter_settings_to_defaults(inputs, resetAll=False):
    """Reset all fitter settings to their default values. Preserves import settings."""
    try:
        # Reset control point counts in state (these are stored in state, not in the UI controls)
        initial_cp_count = get_initial_cp_count(inputs)
        state.fit_cache = {}
        if state.preview_graphics:
            state.preview_graphics.deleteMe()
            state.preview_graphics = None
        state.current_cp_count_upper = initial_cp_count
        state.current_cp_count_lower = initial_cp_count

        # Update labels to show default values
        update_cp_count_labels(inputs)

        if resetAll:
            # Reset soothness penalty
            smoothness = inputs.itemById('smoothness_input')
            if smoothness:
                smoothness.valueOne = config.DEFAULT_SMOOTHNESS_PENALTY

            # Reset to the application continuity default
            continuity_dropdown = inputs.itemById('continuity_level')
            if continuity_dropdown:
                for i in range(continuity_dropdown.listItems.count):
                    continuity_dropdown.listItems.item(i).isSelected = (i == config.DEFAULT_CONTINUITY - 1)

    except Exception as e:
        pass

class AirfoilSplinesCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            event_args = adsk.core.CommandCreatedEventArgs.cast(args)
            cmd = event_args.command
            cmd.setDialogSize(300, 0)

            from AirfoilSplines import check_for_updates
            check_for_updates(adsk.core.Application.get().userInterface)

            on_execute = AirfoilSplinesCommandExecuteHandler()
            cmd.execute.add(on_execute)
            state.handlers.append(on_execute)

            on_input_changed = AirfoilSplinesCommandInputChangedHandler()
            cmd.inputChanged.add(on_input_changed)
            state.handlers.append(on_input_changed)

            on_execute_preview = AirfoilSplinesCommandExecutePreviewHandler()
            cmd.executePreview.add(on_execute_preview)
            state.handlers.append(on_execute_preview)

            on_destroy = AirfoilSplinesCommandDestroyedHandler()
            on_destroy.command_handlers = [on_execute, on_input_changed, on_execute_preview, on_destroy]
            cmd.destroy.add(on_destroy)
            state.handlers.append(on_destroy)

            create_ui_inputs(cmd.commandInputs)

        except Exception as e:
            app = adsk.core.Application.get()
            app.userInterface.messageBox(t("command_created_failed", error=traceback.format_exc()))

class AirfoilSplinesCommandExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            event_args = adsk.core.CommandEventArgs.cast(args)
            if not run_fitter(event_args.command.commandInputs, False):
                event_args.executeFailed = True
                event_args.executeFailedMessage = 'AirfoilSplines creation failed. See Text Commands for details.'
        except Exception as e:
            app = adsk.core.Application.get()
            args.executeFailed = True
            args.executeFailedMessage = str(e)
            app.userInterface.messageBox(t("execution_error", error=traceback.format_exc()))

class AirfoilSplinesCommandInputChangedHandler(adsk.core.InputChangedEventHandler):
    def __init__(self, preserve_fit_settings=False):
        super().__init__()
        self.preserve_fit_settings = preserve_fit_settings
    def notify(self, args):
        self.handle(args)

    def handle(self, args, inputs=None, changed_id=None):
        try:
            if args is not None:
                event_args = adsk.core.InputChangedEventArgs.cast(args)
                inputs = event_args.inputs
                # Get the root command inputs
                app = adsk.core.Application.get()
                try:
                    cmd = event_args.firingEvent.sender
                    if cmd:
                        inputs = cmd.commandInputs
                except:
                    pass

                changed_id = event_args.input.id

            if _updating_cp_labels:
                return
            if changed_id == 'initial_cp_count':
                # This is the count to use on the next Reset, not a fit request.
                return

            if changed_id == 'select_file':
                ui = adsk.core.Application.get().userInterface
                dlg = ui.createFileDialog()
                dlg.filter = t("file_filter")
                if dlg.showOpen() == adsk.core.DialogResults.DialogOK:
                    file_input = inputs.itemById('file_path')
                    file_input.value = dlg.filename
                    _set_selected_file_button_text(inputs, dlg.filename)
                    state.fit_cache['selected_file_path'] = dlg.filename
                    # file_input.isVisible = True

                    if not self.preserve_fit_settings:
                        # Reset fitter settings to defaults when a new file is selected
                        reset_fitter_settings_to_defaults(inputs)
                        te_input = inputs.itemById('te_thickness')
                        if te_input:
                            te_input.value = 0.0

                        # Reset state variables related to fitting
                        state.fit_cache = {}
                        initial_cp_count = get_initial_cp_count(inputs)
                        state.current_cp_count_upper = initial_cp_count
                        state.current_cp_count_lower = initial_cp_count
                    else:
                        # Replacing the source in an edit must not silently change
                        # TE topology or the selected control-point counts.
                        state.fit_cache = {}

                    # Trigger preview update when file is selected (if line is also selected)
                    line_select = inputs.itemById('chord_line')
                    if line_select and line_select.selectionCount > 0:
                        state.needs_refit = True

            elif changed_id in ['continuity_level', 'smoothness_input', 'cp_count_upper', 'cp_count_lower']:
                if changed_id in ['continuity_level']:
                    state.fit_cache = {}

                # Correct CP count values before triggering refit
                if changed_id =='cp_count_upper' and state.current_cp_count_upper is not None:
                    state.current_cp_count_upper = min(config.MAX_CP_COUNT, state.current_cp_count_upper + 1)
                    update_cp_count_labels(inputs)
                elif changed_id =='cp_count_lower' and state.current_cp_count_lower is not None:
                    state.current_cp_count_lower = min(config.MAX_CP_COUNT, state.current_cp_count_lower + 1)
                    update_cp_count_labels(inputs)

                state.needs_refit = True
            elif changed_id == 'rotate_airfoil':
                state.rotation_state = (state.rotation_state + 1) % 4

            elif changed_id == 'flip_airfoil':
                state.flip_orientation = not state.flip_orientation
            elif changed_id == 'curvature_comb':

                # Show/hide comb settings based on checkbox
                comb_checked = inputs.itemById('curvature_comb').value
                comb_scale_item = inputs.itemById('comb_scale')
                comb_density_item = inputs.itemById('comb_density')
                if comb_scale_item:
                    comb_scale_item.isVisible = comb_checked
                if comb_density_item:
                    comb_density_item.isVisible = comb_checked

            elif changed_id == 'reset_button':
                reset_fitter_settings_to_defaults(inputs, False)
                state.needs_refit = True

            chord_line_input = inputs.itemById('chord_line')
            file_path_input = inputs.itemById('file_path')
            has_selection = chord_line_input.selectionCount > 0 and file_path_input.value != ""

            toggle_ids = ['initial_cp_count', 'cp_count_upper', 'cp_count_lower', 'te_thickness', 'smoothness_input', 'continuity_level',
                          'import_raw',
                          'rotate_airfoil', 'flip_airfoil', 'curvature_comb',
                          'comb_scale', 'comb_density', 'fitter_settings', 'import_settings', 'reset_button']

            for input_id in toggle_ids:
                item = inputs.itemById(input_id)
                if item:
                    item.isVisible = has_selection

            # Handle comb settings visibility based on checkbox state
            if has_selection:
                comb_checked = inputs.itemById('curvature_comb').value if inputs.itemById('curvature_comb') else False
                comb_scale_item = inputs.itemById('comb_scale')
                comb_density_item = inputs.itemById('comb_density')
                if comb_scale_item:
                    comb_scale_item.isVisible = comb_checked and has_selection
                if comb_density_item:
                    comb_density_item.isVisible = comb_checked and has_selection

            if changed_id in ['chord_line', 'select_file', 'rotate_airfoil', 'flip_airfoil']:
                import_settings_group = inputs.itemById('import_settings')
                if import_settings_group and has_selection:
                    import_settings_group.isVisible = True

                te_input = adsk.core.DistanceValueCommandInput.cast(inputs.itemById('te_thickness'))
                chord_line_input = inputs.itemById('chord_line')
                if te_input and chord_line_input.selectionCount > 0:
                    selected_line = adsk.fusion.SketchLine.cast(chord_line_input.selection(0).entity)
                    if selected_line:
                        start_pt = selected_line.startSketchPoint.worldGeometry
                        end_pt = selected_line.endSketchPoint.worldGeometry
                        chord_vec = adsk.core.Vector3D.create(end_pt.x - start_pt.x,
                                                             end_pt.y - start_pt.y,
                                                             end_pt.z - start_pt.z)
                        sketch = selected_line.parentSketch
                        mat = sketch.transform
                        if sketch.assemblyContext:
                            mat.transformBy(sketch.assemblyContext.transform2)

                        sketch_normal_world = adsk.core.Vector3D.create(mat.getCell(0, 2),
                                                                       mat.getCell(1, 2),
                                                                       mat.getCell(2, 2))
                        sketch_normal_world.normalize()
                        theta = state.rotation_state * (math.pi / 2.0)
                        x_axis = chord_vec.copy()
                        x_axis.normalize()
                        y_axis_in_plane = sketch_normal_world.crossProduct(x_axis)
                        y_axis_in_plane.normalize()
                        mani_dir = y_axis_in_plane.copy()
                        mani_dir.scaleBy(math.cos(theta))
                        z_part = sketch_normal_world.copy()
                        z_part.scaleBy(math.sin(theta))
                        mani_dir.add(z_part)
                        mani_dir.normalize()

                        # Trailing edge position depends on flip orientation
                        # When not flipped: TE is at end_pt (normal orientation)
                        # When flipped: TE is at start_pt (reversed orientation)
                        te_position = end_pt if not state.flip_orientation else start_pt
                        te_input.setManipulator(te_position, mani_dir)

            # Always trigger preview when parameters change (if line and file are selected)
            if has_selection:
                refit_ids = ['cp_count_upper', 'cp_count_lower', 'smoothness_input', 'continuity_level',
                             'file_path', 'chord_line', 'te_thickness']
                update_ids = ['import_raw', 'rotate_airfoil', 'flip_airfoil',
                              'curvature_comb', 'comb_scale', 'comb_density']
                if changed_id in refit_ids:
                    state.needs_refit = True
                elif changed_id in update_ids:
                    # Visualization-only changes must never trigger a fit.
                    # Clear any stale refit flag and let executePreview redraw from cache only.
                    state.needs_refit = False

        except Exception as e:
            pass

class AirfoilSplinesCommandExecutePreviewHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            event_args = adsk.core.CommandEventArgs.cast(args)
            run_fitter(event_args.command.commandInputs, True)
            # Update labels after fit completes (counts may have changed)
            update_cp_count_labels(event_args.command.commandInputs)
        except Exception as e:
            pass

class AirfoilSplinesCommandDestroyedHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        """Clean up when command is destroyed (finished or cancelled)."""
        try:
            # Reset all state to default values (includes preview graphics cleanup)
            state.reset_state()
        except Exception as e:
            pass
        finally:
            for handler in getattr(self, 'command_handlers', ()):
                if handler in state.handlers:
                    state.handlers.remove(handler)
            self.command_handlers = []
