"""Persistent, versioned airfoil input and fitting without Fusion/UI state."""
import json
import math
from pathlib import Path
import tempfile
from functools import lru_cache

from core.airfoil_processor import AirfoilProcessor
from core.bspline_processor import BSplineProcessor
from utils.bspline_helper import apply_te_thickness_to_reference


SCHEMA = 1
PARAMETERS = (
    ('te', 'TE thickness', 'mm'),
    ('smoothness', 'Smoothness', ''),
    ('upper_count', 'Upper control points', ''),
    ('lower_count', 'Lower control points', ''),
    ('continuity', 'LE continuity (1/2/3)', ''),
)


def read_source(path):
    # Match the existing loader's text encoding; JSON preserves the decoded data.
    return {'filename': Path(path).name, 'dat': Path(path).read_text()}


def encode(recipe):
    return json.dumps(recipe, ensure_ascii=True, allow_nan=False)


def decode(text):
    recipe = json.loads(text)
    if recipe.get('schema') != SCHEMA or not isinstance(recipe.get('dat'), str):
        raise ValueError('Unsupported or missing AirfoilSpline feature data.')
    return recipe


def validate(values, chord_length):
    if not math.isfinite(chord_length) or chord_length <= 1e-9:
        raise ValueError('The chord must have a positive length.')
    if not all(math.isfinite(values[key]) for key, _, _ in PARAMETERS):
        raise ValueError('Airfoil parameters must be finite.')
    if values['te'] < 0 or values['smoothness'] < 0:
        raise ValueError('TE thickness and smoothness must not be negative.')
    for key in ('upper_count', 'lower_count'):
        if values[key] != int(values[key]) or not 4 <= values[key] <= 19:
            raise ValueError('Control point counts must be whole numbers from 4 to 19.')
    if values['continuity'] not in (1, 2, 3):
        raise ValueError('LE continuity must be 1, 2 or 3.')


def fit(recipe, values, chord_length):
    """Refit embedded data; an external file is never needed for recompute."""
    validate(values, chord_length)
    fitted = _fit_cached(recipe['dat'], values['te'] / chord_length,
                         values['smoothness'], int(values['upper_count']),
                         int(values['lower_count']), int(values['continuity']))
    # Callers must not be able to modify another feature's cached result.
    return tuple(value.copy() if hasattr(value, 'copy') else value for value in fitted)


@lru_cache(maxsize=64)
def _fit_cached(dat, te, smoothness, upper_count, lower_count, continuity):
    # Only pure numerical inputs belong in this bounded cache. Placement and
    # Fusion entities are deliberately excluded; Undo/recompute still reapplies
    # geometry in the current occurrence and sketch coordinates.
    with tempfile.TemporaryDirectory(prefix='airfoil_feature_') as directory:
        path = Path(directory) / 'source.dat'
        path.write_text(dat)
        processor = AirfoilProcessor(logger_func=lambda message: None)
        if not processor.load_airfoil_data_and_initialize_model(str(path)):
            raise ValueError('Cannot load the embedded airfoil data.')
    upper, lower = apply_te_thickness_to_reference(
        processor.upper_data, processor.lower_data, te)
    bspline = BSplineProcessor()
    bspline.smoothing_weight = smoothness
    if not bspline.fit_bspline(
            upper, lower,
            num_control_points=(upper_count, lower_count),
            is_thickened=te > 1e-9,
            upper_te_tangent_vector=processor.upper_te_tangent_vector,
            lower_te_tangent_vector=processor.lower_te_tangent_vector,
            enforce_g2=continuity >= 2,
            enforce_g3=continuity == 3, single_span=True):
        raise RuntimeError('Airfoil fitting failed.')
    return (bspline.upper_control_points, bspline.upper_knot_vector, bspline.degree_upper,
            bspline.lower_control_points, bspline.lower_knot_vector, bspline.degree_lower)
