# Airfoil Splines Add-In for Fusion

A Fusion add-in that imports airfoil coordinate data from `.dat` files and fits optimized BÃ©zier curves to it. The generated splines are aligned to the selected sketch line. The result maintains smooth curvature and geometric continuity at the leading edge and can be used immediately for lofts, sweeps, and other CAD operations.

Airfoil Splines brings the shared B-spline fitting library into Fusion with editable parametric features.

## Parametric Version

Each insertion creates one Airfoil Splines timeline feature containing its output
sketch and any required construction planes. Right-click it and choose **Edit
Feature** to change the settings.

The feature embeds the source `.dat` contents in the design. Moving or deleting
the original file does not remove that data; editing the file externally does
not automatically update the feature. Select the changed file in Edit Feature
to use it. Keep the add-in installed and running to edit or recompute these
custom features. Design history must be enabled for parametric features.

With design history disabled, the same fitting controls create an ordinary
sketch with fixed splines and a trailing-edge closing line when needed.

Previously inserted airfoils remain ordinary sketches. Installing this version
does not convert them into editable Airfoil Splines timeline features.

## Installation

The Airfoil Splines App Store listing is being prepared. The following link is
for the legacy add-in release:
https://apps.autodesk.com/FUSION/en/Detail/Index?id=7312110669169312529&appLang=en&os=Win64

### MSI Installer (Windows)

Uninstall legacy add-in (AF) before installing Airfoil Splines (AS). The
installer checks for AF and asks you to remove it first because the two add-ins
cannot be used together.

- **File**: `AirfoilSplines-<version>.msi`
1. Close Fusion
2. Download & run the installer
3. Start Fusion & confirm dependency installation
4. Restart Fusion

### Manual Installation (Windows)

1. Download or clone this repository
2. Copy the `AirfoilSplines` folder to your Fusion add-ins directory:
   - **Windows**: `%APPDATA%\Autodesk\Autodesk Fusion\API\AddIns\`
3. Go to **Utilities â†’ Add-Ins â†’ Scripts and Add-Ins** and enable **Airfoil Splines**
4. Confirm dependency installation
5. Restart Fusion

## Usage

1. **Create a sketch** with a line representing your desired chord position and length
2. **Launch the command** "Insert fitted airfoil" from the INSERT panel in the Solid or Surface workspace toolbar
3. **Select the chord line** in your sketch
4. **Select an airfoil file** (`.dat` format)
5. **Position the airfoil**:
   - Use **Rotate 90Â°** to orient the airfoil plane relative to the chord line
   - Use **Flip** to reverse nose/tail direction
   - Use **TE Thickness** manipulator to adjust trailing edge thickness
   - Preview is automatically displayed when both chord line and file are selected
6. **Adjust fitting parameters**:
   - **Initial Control Point Count** The default is 10 and achieves good results in most cases, however sometimes a better fit can be achieved by starting at a lower point count and inserting points as needed. 
   - **Control Point Count**: More points = higher accuracy but might introduce oscillations
   - **Smoothness**: Defaults to 0.001, higher values produce smoother control polygons at the cost of accuracy. Not all airfoils require smoothing, in those cases smoothing can be set to zero.
   - **LE Continuity**: Default is G2, if the curvature near the leading edge is not smooth ehough, G3 can be enforced additionally. G1 is available as a fallback.

7. **Curvature Comb**: analyze the airfoil's curvature in the preview.
8. **Show Input Data**: overlay the input coordinates for comparison.
9. **Click OK** to create one Airfoil Splines timeline feature, with a new output sketch in the chord line's component.
10. **Edit Feature** from its timeline context menu to revise the fit later. Existing downstream references are retained where Fusion can resolve them.

## Features

### Airfoil Data Import
- **Automatic format detection**: The loader analyzes coordinate patterns to determine the format. Currently Selig and Lednicer are supported.
- **Automatic normalization**: Coordinates are translated, rotated, and scaled so the leading edge is at origin and chord lies along the X-axis
- **Automatic repaneling**: The input data is repaneled to even out point spacing.

### BÃ©zier Fitting
- **Single-span B-Spline curves**: The fitted curves are stored as fixed NURBS splines in Fusion. Based on Dev Rajnarayan et al. 2019 (https://arc.aiaa.org/doi/10.2514/6.2018-3949).
- **Adjustable control point count**: 4 to 19 control points per surface (upper/lower fitted independently)
- **G1 continuity**: (fallback) Tangent continuity is always enforced at the leading edge between upper and lower surfaces
- **G2 continuity** (default): Curvature continuity at the leading edge via constrained optimization
- **G3 continuity** (optional): Curvature derivative continuity at the leading edge
- **Smoothness penalty**: Adjustable regularization to balance accuracy vs. smoothness of the control polygon

### Geometry Placement
- **Chord line selection**: Select any sketch line to define the chord position and length
- **Automatic scaling**: Airfoil is scaled to match the selected chord line length
- **Rotation**: Rotate the airfoil plane in 90Â° increments around the chord line (0Â°, 90Â°, 180Â°, 270Â°)
- **Flip orientation**: Reverse the nose-to-tail direction along the chord line
- **Trailing edge thickness**: Add symmetric trailing edge thickness with minimal distortion of the airfoil.

### Output
- **Parametric fit**: revise the source profile and fitting settings through Edit Feature.
- **Fixed splines**: exact curves created through the Fusion API and updated in place. Their control points are not manually editable.
- **Show input data**: Optionally display the original airfoil coordinate points for comparison

### Error Reporting
- **Max deviation display**: Shows the maximum fitting error for upper and lower surfaces in document units

### Dependencies

The add-in requires the following Python packages:
- `numpy`
- `scipy`  

**Automatic or manual installation (Windows only)**: If the dependencies are missing from the `lib/` folder, the add-in will prompt to install them automatically on first run. You can also install them manually (see Troubleshooting section).

## File Format Support

### Selig Format
```
NACA 2412
1.000000  0.001260
0.950000  0.011480
...
0.000000  0.000000   <- Leading edge (minimum x)
...
0.950000 -0.009330
1.000000 -0.001260
```

### Lednicer Format
```
NACA 2412
35.  35.              <- Optional: point counts (upper, lower)
0.000000  0.000000    <- Upper surface starts at LE
0.012500  0.012500
...
1.000000  0.001260    <- Upper surface ends at TE
0.000000  0.000000    <- Lower surface starts at LE
0.012500 -0.010000
...
1.000000 -0.001260    <- Lower surface ends at TE
```

## Troubleshooting

### Sketch supports and reference-plane errors

Face-supported sketches are accepted even when Fusion cannot retrieve their original reference plane at the current timeline position. The add-in first tries to reuse the source support; if it is unavailable, it first tries using the source sketch directly. Only if the consuming API rejects that reference does it create a zero-offset construction plane based on the sketch. Any such helper remains in the model because the output depends on it. The add-in does not redefine the source sketch or rearrange the timeline.

Final airfoils always go into a new sketch, including at 0 degrees. A 180-degree rotation reuses the same support as 0 degrees. At 90 or 270 degrees, an origin plane is reused when it coincides with the required plane; otherwise an angled plane is created.

If Fusion rejects support creation, the error dialog reports that operation and the Text Commands log (Ctrl+Alt+C) contains the underlying exception. This is a failure to create the output support, not an automatic diagnosis that the source sketch is broken.

### "Dependencies Missing" on startup

The add-in will offer to install numpy and scipy automatically. If this fails:

**Windows**
1. Locate Fusion's Python: typically in the Fusion installation directory and open a terminal there
2. Run: `python -m pip install --force-reinstall --target "<addin-path>/lib" numpy scipy` in that terminal
3. Restart Fusion

## Separate application

Airfoil Splines has its own loader, bundle, command IDs, saved-feature identifiers,
and installer upgrade identity. It does not replace the legacy add-in or adopt its
existing parametric features. Those features still require the original add-in.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Author

Michael Reeg

## Changelog

### Unreleased â€” parametric prototype
- Airfoil Splines timeline features with embedded source data and editable fitting settings.
- Preserve spline entities during normal edits to retain downstream references.
- Support face sketches and moved component occurrences; graphics-only previews.
- Remove the adjustable DXF workflow and the ezdxf dependency.
- Known issue: the reported wing design may require Compute All after upstream changes.

### v1.2.0
- Improved Error Objective
- Configurable initial control point count
- Improved smoothing
- UI Updates
- Various fixes

### v1.1.7
- Italian language support (Thanks Mirko!)
- Changed reference plane handling
- Fixed TE normalization

### v1.1.6 (2026-03-18)
- Fixed Reference plane bug

### v1.1.5 (2026-02-16)
- Performance optimizations

### v1.1.4 (2026-02-10)
- German language support
- UI Improvements
- Better default settings

### v1.1.3 (2026-02-06)
- Improved Input Normalization 
- Fixed MacOS package, removed .pyc and .pyo files
- Fixed deinstall on drives other than c:
- Improved TE thickening

### v1.1.2 (2026-01-23)
- Experimental bundle for MacOS
- Removed bundled installer for Windows
- Improved handling of thickened trailing edges
- Avoid creation of unnecessary planes
- Fix dependency updates
- README updates

### v1.1.1 (2026-01-21)
- Fixed DXF import alignment
- Fixed sub-component bug
- Added privacy policy
- Fixed the installer

### v1.1.0 (2026-01-11)
- Added curvature comb visualization
- Separate control point count controls for upper/lower surfaces
- Improved knot insertion algorithm
- New error display
- UI improvements
- Improved error handling and stage management

### v1.0.2 (2026-01-03)
- Optional static libs support

### v1.0.1 (2026-01-03)
- Fixed installer progress dialogs
- Deinstaller now removes all files

### v1.0 (2026-01-01)
- Initial release

## Shared fitting library

The shared headless library is being extracted in
airfoil-splines-core (the sibling local project).
This initial repository split preserves the tested local fitting implementation.
Consumer migration and pinned wheel packaging follow numerical parity checks;
see the library migration document for the four planned consumers.

## Local shared core

The fitting implementation lives in the sibling `airfoil-splines-core` project. Run
`python setup/prepare_core.py` to bundle it into the ignored `_vendor` directory
for Fusion. The installer build runs this step automatically. For offline tests,
set `PYTHONPATH` to `../airfoil-splines-core/src` or install that local package first.
