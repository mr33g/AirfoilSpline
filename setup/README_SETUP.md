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

## Release workflow

1. Build and test the installer locally with the intended release version.
2. Submit that installer to Autodesk for review.
3. Wait for Autodesk to approve it and make it available in the store.
4. Only then update `version` in the root `AirfoilSpline.manifest`, commit it,
   and push it to `main` so installed copies notify users about the available update.

The installer contains the version passed to `build.bat`. The build restores the
source manifest afterward, so building a candidate does not announce it to users.
Keep the repository manifest at the currently available store version throughout
review. The update checker reads that file from `main`; a Git tag or local build
alone does not trigger notifications.

## Installation and removal

Close Fusion before installing or uninstalling. Uninstall an existing AirfoilSpline version
through Windows Settings > Apps before manually installing the new package.
Airfoil Fitter is a separate application and does not need to be uninstalled.
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
