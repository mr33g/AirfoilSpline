# Airfoil Splines MSI installer setup

The Windows installer uses WiX and Autodesk's `.bundle` structure.

## Prerequisites

- Python 3
- WiX with the WixToolset.UI.wixext and WixToolset.Util.wixext extensions

Install these tools locally before building. Airfoil Splines does not use GitHub Actions.

## Local build

From this folder, run:

```bat
build.bat 2.0.2
```

Replace the example version with the release version. The script generates the
file list, sets the package and manifest versions for the build, and restores
the source version files afterward. The output is `AirfoilSplines-<version>.msi`.
Dependencies are excluded; the add-in offers to install numpy and scipy on first run.

The WiX source is `AirfoilSplinesAddin.wxs`.

## Installation and removal

Close Fusion before installing or uninstalling. Uninstall an existing Airfoil Splines version
through Windows Settings > Apps before manually installing the new package.
Uninstall legacy add-in (AF) before installing Airfoil Splines (AS).
The installer blocks installation when it detects the legacy MSI and never removes it automatically. Remove any manually installed legacy add-in from Fusion before using Airfoil Splines.
To remove Airfoil Splines, use Installed Apps or run its MSI again.

## Separate application identity

Airfoil Splines installs to
`%AppData%\Autodesk\ApplicationPlugins\AirfoilSplines.bundle\`.
The bundle contains `Contents/AirfoilSplines.py` and
`Contents/AirfoilSplines.manifest`. The macOS archive uses an `Airfoil Splines` folder.

The manifest ID, bundle product code, MSI upgrade code, component GUIDs, and
registry keys belong to AirfoilSplines. Installing or uninstalling it must not
replace or remove Airfoil Splines. No legacy feature migration is performed.

## Troubleshooting

Check that the bundle contains `PackageContents.xml` and
`Contents/AirfoilSplines.py`. In Fusion's Scripts and Add-Ins dialog, look for
Airfoil Splines, verify it is running, and check Text Commands for errors.
