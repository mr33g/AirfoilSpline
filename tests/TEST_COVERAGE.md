# Test review — 2026-10-01

The suites are useful regression protection, but not comprehensive product validation.
No runtime code was changed during this review.

## Measured coverage

Measured with coverage.py 7.16.2 and branch tracking. Percentages combine executed
statements and branches; they are not percentages of supported behavior.

| Suite | Before | After | Tests after review |
| --- | ---: | ---: | ---: |
| AirfoilFit (`src/airfoil_fit`) | 69% | 73% | 22 |
| AirfoilSpline (`logic`, `ui`, `utils`) | 47% | 53% | 65 |

The add-in total excludes the entry-point loader, installer tools, settings module,
and bundled third-party/core packages. Those exclusions matter: installation and
startup are not validated by this number. Both complete suites passed; the core
suite also passed against the actual `_vendor` package, without forcing source imports.

## Stronger coverage added

- Independent closed-form vertical error and inverse-x checks, including the
  zero-leading-edge-derivative case that forces bracketing.
- Finite-difference gradient checks away from a fitted optimum, for the vertical
  objective, TE handle penalty and leading-edge derivative calculations.
- Cambered, blunt-TE fitting with different upper/lower degrees, checking actual
  endpoints, monotonicity and G1/G2/G3 constraints rather than only solver flags.
- Knot insertion preserves sampled geometry and first/second derivatives.
- Empty/malformed DAT rejection.
- All four quarter-turns with and without flip, non-unit chord length and
  translated/rotated component coordinates, checked with numerical transforms.
- Support-plane reuse versus offsets, rejected-sketch fallback and retry veto,
  occurrence-aware sketch creation, and exact control-point/knot transfer to Fusion.

Selected improvements: vertical metrics 64% -> 85%, TE handle penalty 20% -> 100%,
chord-frame code 0% -> 100%, Fusion spline adapter 0% -> 95%, sketch supports 0% -> 63%.
Even 100% execution coverage does not establish correctness for all inputs.

## Remaining gaps, in priority order

1. **Real Fusion integration.** Mocked events do not establish native event timing,
   label-change notifications, transaction rollback, Undo/Redo, save/reopen or
   downstream feature propagation. The existing DeferredSketchPropagation script
   covers one native scenario; insertion/edit/reset/count controls need a broader
   repeatable Fusion smoke suite.
2. **Representative source data.** Core tests remain synthetic, mainly NACA-like
   profiles. Add a curated real-profile corpus with camber/thickness extremes,
   uneven spacing, duplicate points and problematic leading edges. Test numerical
   invariants and convergence, not identical control points across SciPy versions.
3. **Refinement edge cases.** Insertion operations are 54% covered. Spacing fallback,
   repeated/boundary knots, both-surface refinement and failures after partial
   progress need broader coverage.
4. **Complete add-in execution and lifecycle.** Fitter 46%, UI handlers 48%, preview
   renderer 27%, graphics/state/dialog creation 0%. Existing tests favor feature
   updates and deferred history handling over first insertion, startup/shutdown,
   document changes and every user-input sequence.
5. **Packaging/startup.** Installer inclusion was checked separately, but automated
   tests do not yet install an MSI or exercise dependency bootstrapping, restart,
   missing/corrupt bundles or different supported Fusion/Python versions.

The saved control-point baseline is useful for detecting algorithm drift, but
must remain supplementary to independent geometry/error assertions.

## Run offline tests from AirfoilSpline

```powershell
$env:PYTHONPATH = (Resolve-Path .\_vendor).Path
python -m unittest discover -s tests
```

With coverage installed in the test environment:

```powershell
python -m coverage run --branch --source=logic,ui,utils -m unittest discover -s tests
python -m coverage report
```

These tests never launch Fusion. Native geometry and event behavior still require
Fusion validation; passing mocks must not be reported as a Fusion smoke-test pass.
