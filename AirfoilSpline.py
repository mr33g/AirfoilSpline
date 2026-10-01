import adsk.core, adsk.fusion, adsk.cam, traceback
import os
import sys
import json
import re
import urllib.request

# Get the directory where this script is located
addin_dir = os.path.dirname(__file__)
manifest_path = os.path.join(addin_dir, 'AirfoilSpline.manifest')
update_manifest_url = 'https://raw.githubusercontent.com/mr33g/AirfoilSpline/main/AirfoilSpline.manifest'
app_store_url = 'https://apps.autodesk.com/FUSION/en/Detail/Index?id=5913630262916104681&appLang=en&os=Win32_64'
_update_check_attempted = False

# Add the add-in directory and bundled 'lib' to the path
if addin_dir not in sys.path:
    sys.path.insert(0, addin_dir)

vendor_dir = os.path.join(addin_dir, '_vendor')
if vendor_dir not in sys.path:
    sys.path.insert(0, vendor_dir)
lib_dir = os.path.join(addin_dir, 'lib')
if lib_dir not in sys.path:
    sys.path.insert(0, lib_dir)

# Local imports after path setup
from utils.i18n import t

# Now we can import our modular components
from logic import state


def _read_manifest_version(manifest_file):
    try:
        with open(manifest_file, 'r', encoding='utf-8') as handle:
            manifest_data = json.load(handle)
        version = manifest_data.get('version')
        return str(version).strip() if version else None
    except Exception:
        return None


def _parse_version(version_string):
    if not version_string:
        return ()
    numeric_parts = [int(part) for part in re.findall(r'\d+', version_string)]
    return tuple(numeric_parts)


def _is_remote_version_newer(local_version, remote_version):
    local_parts = _parse_version(local_version)
    remote_parts = _parse_version(remote_version)
    if local_parts and remote_parts:
        max_len = max(len(local_parts), len(remote_parts))
        local_parts += (0,) * (max_len - len(local_parts))
        remote_parts += (0,) * (max_len - len(remote_parts))
        return remote_parts > local_parts
    return bool(remote_version) and remote_version != local_version


def check_for_updates(ui):
    global _update_check_attempted
    if _update_check_attempted:
        return
    _update_check_attempted = True

    local_version = _read_manifest_version(manifest_path)
    if not local_version:
        return

    try:
        with urllib.request.urlopen(update_manifest_url, timeout=2.5) as response:
            remote_manifest = json.loads(response.read().decode('utf-8'))
    except Exception:
        return

    remote_version = str(remote_manifest.get('version', '')).strip()
    if not _is_remote_version_newer(local_version, remote_version):
        return

    ui.messageBox(
        t(
            "update_available",
            local_version=local_version,
            remote_version=remote_version,
            app_store_url=app_store_url
        )
    )


def _python_has_module(python_exe, module_name):
    import subprocess

    result = subprocess.run(
        [python_exe, '-c', f'import importlib.util, sys; sys.exit(0 if importlib.util.find_spec("{module_name}") else 1)'],
        capture_output=True,
        text=True
    )
    return result.returncode == 0


def ensure_dependencies():
    """Ensures required libraries are available. Prioritizes bundled 'lib' folder."""
    try:
        import numpy
        import scipy
        return True
    except ImportError:
        pass

    ui = adsk.core.Application.get().userInterface
    res = ui.messageBox(
        t("deps_missing_msg"),
        t("deps_missing_title"),
        adsk.core.MessageBoxButtonTypes.YesNoButtonType
    )

    if res == adsk.core.DialogResults.DialogNo:
        return False

    try:
        import subprocess
        python_exe = sys.executable
        # Handle cases where Fusion uses a subfolder for Python
        potential_exe = os.path.join(os.path.dirname(python_exe), 'Python', 'python.exe')
        if os.path.exists(potential_exe):
            python_exe = potential_exe

        if not os.path.exists(lib_dir):
            os.makedirs(lib_dir)

        bootstrap_pip_cmd = f'"{python_exe}" -m ensurepip --upgrade'
        # Install directly into the add-in's lib folder
        pip_cmd = f'"{python_exe}" -m pip install --upgrade --force-reinstall --target "{lib_dir}" numpy scipy'
        needs_pip_bootstrap = not _python_has_module(python_exe, 'pip')

        install_cmd = pip_cmd
        if needs_pip_bootstrap:
            install_cmd = f'{bootstrap_pip_cmd} && {pip_cmd}'

        if os.name == 'nt':
            os.system(f'start "AirfoilSpline Dependency Installer" cmd /c "{install_cmd} & pause"')
            ui.messageBox(t("deps_install_started"))
        else:
            if needs_pip_bootstrap:
                subprocess.check_call([python_exe, '-m', 'ensurepip', '--upgrade'])
            subprocess.check_call([python_exe, '-m', 'pip', 'install', '--upgrade', '--force-reinstall', '--target', lib_dir, 'numpy', 'scipy'])
            ui.messageBox(t("deps_install_complete"))

        return False
    except Exception as e:
        ui.messageBox(t("deps_install_failed", error=str(e)))
        return False

def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface
        # import debugpy
        # if not debugpy.is_client_connected():
        #     try:
        #         debugpy.listen(('localhost', 5678), in_process_debug_adapter=True)
        #         ui.messageBox('Debug server ready on port 5678.\nAttach VSCode now, then click OK.')
        #     except Exception as e:
        #         ui.messageBox(f'Debug setup warning: {str(e)}\nContinuing anyway...')

        if not ensure_dependencies():
            return

        # Import these here, after dependencies are checked and potentially installed
        from ui.handlers import AirfoilSplineCommandCreatedHandler
        from logic import custom_feature
        custom_feature.register(addin_dir)

        # 1. Create Command Definition
        cmd_def = ui.commandDefinitions.itemById('AirfoilSplineCommand')
        if not cmd_def:
            # Use absolute path for resources to be safe
            resource_path = os.path.join(addin_dir, 'resources', 'AirfoilSplineCommand')
            cmd_def = ui.commandDefinitions.addButtonDefinition(
                'AirfoilSplineCommand',
                t("cmd_button_name"),
                t("cmd_button_desc"),
                resource_path
            )
            toolClip_path = os.path.join(addin_dir, 'resources', 'AirfoilSplineCommand', 'tooltip.png')
            cmd_def.toolClipFilename = toolClip_path

        on_command_created = AirfoilSplineCommandCreatedHandler()
        cmd_def.commandCreated.add(on_command_created)
        state.handlers.append(on_command_created)

        # 2. Add to INSERT panel in Solid and Surface workspaces
        # We try both common panel IDs: 'InsertPanel' and 'SolidInsertPanel'
        for ws_id, tab_id, panel_ids in [
            ('FusionSolidEnvironment', 'SolidTab', ['InsertPanel', 'SolidInsertPanel']),
            ('FusionSurfaceEnvironment', 'SurfaceTab', ['InsertPanel', 'SurfaceInsertPanel'])
        ]:
            workspace = ui.workspaces.itemById(ws_id)
            if workspace:
                tab = workspace.toolbarTabs.itemById(tab_id)
                if tab:
                    for p_id in panel_ids:
                        panel = tab.toolbarPanels.itemById(p_id)
                        if panel:
                            existing_control = panel.controls.itemById('AirfoilSplineCommand')
                            if not existing_control:
                                panel.controls.addCommand(cmd_def)
                            break # Found the panel, move to next workspace

    except:
        if ui:
            ui.messageBox(t("failed_to_start", error=traceback.format_exc()))

def stop(context):
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

        from logic import custom_feature
        custom_feature.stop()

        # Cleanup from all possible panels
        for ws_id, tab_id, panel_ids in [
            ('FusionSolidEnvironment', 'SolidTab', ['InsertPanel', 'SolidInsertPanel']),
            ('FusionSurfaceEnvironment', 'SurfaceTab', ['InsertPanel', 'SurfaceInsertPanel'])
        ]:
            workspace = ui.workspaces.itemById(ws_id)
            if workspace:
                tab = workspace.toolbarTabs.itemById(tab_id)
                if tab:
                    for p_id in panel_ids:
                        panel = tab.toolbarPanels.itemById(p_id)
                        if panel:
                            control = panel.controls.itemById('AirfoilSplineCommand')
                            if control:
                                control.deleteMe()

        # Delete command definition
        cmd_def = ui.commandDefinitions.itemById('AirfoilSplineCommand')
        if cmd_def:
            cmd_def.deleteMe()
    except:
        pass
