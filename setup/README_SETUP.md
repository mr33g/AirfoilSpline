# AirfoilSpline MSI installer setup

The Windows installer uses WiX and Autodesk's `.bundle` structure.

## Prerequisites

- Python 3
- WiX with the WixToolset.UI.wixext and WixToolset.Util.wixext extensions

Install these tools locally before building. AirfoilSpline does not use GitHub Actions.

## Local build

From this folder, run:

```bat
build.bat 2.0.2
```

Replace the example version with the release version. The script generates the
file list, sets the package and manifest versions for the build, and restores
the source version files afterward. The output is `AirfoilSpline-<version>.msi`.
Dependencies are excluded; the add-in offers to install numpy and scipy on first run.

The WiX source is `AirfoilSplineAddin.wxs`.

## Installation and removal

Close Fusion before installing or uninstalling. Uninstall an existing AirfoilSpline version
through Windows Settings > Apps before manually installing the new package.
Uninstall legacy Airfoil Fitter (AF) before installing AirfoilSpline (AS).
The installer blocks installation when it detects the legacy MSI, an AirfoilFitter
bundle in the user or machine ApplicationPlugins folder, or a manual installation
in the standard Fusion API AddIns folder. It asks the user to uninstall AF first;
it never removes AF automatically. AS removal remains available if AF is present.
Copies registered from arbitrary development folders cannot be detected by these
searches and must also be removed from Fusion before using AS.
To remove AirfoilSpline, use Installed Apps or run its MSI again.

## Separate application identity

AirfoilSpline installs to
`%AppData%\Autodesk\ApplicationPlugins\AirfoilSpline.bundle\`.
The bundle contains `Contents/AirfoilSpline.py` and
`Contents/AirfoilSpline.manifest`. The macOS archive uses an `AirfoilSpline` folder.

The manifest ID, bundle product code, MSI upgrade code, component GUIDs, and
registry keys belong to AirfoilSpline. Installing or uninstalling it must not
replace or remove Airfoil Fitter. No legacy feature migration is performed.

## Troubleshooting

Check that the bundle contains `PackageContents.xml` and
`Contents/AirfoilSpline.py`. In Fusion's Scripts and Add-Ins dialog, look for
AirfoilSpline, verify it is running, and check Text Commands for errors.
