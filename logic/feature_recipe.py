"""Persistent, versioned airfoil input and fitting without Fusion/UI state."""
import json
import math
from pathlib import Path
from functools import lru_cache
from copy import deepcopy
import airfoil_splines_settings as config
from airfoil_splines_core import bspline_helper

from airfoil_splines_core.airfoil_processor import AirfoilProcessor
from airfoil_splines_core.bspline_processor import BSplineProcessor
from airfoil_splines_core.bspline_helper import apply_te_thickness_to_reference


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
        raise ValueError('Unsupported or missing AirfoilSplines feature data.')
    return recipe


def validate(values, chord_length):
    if not math.isfinite(chord_length) or chord_length <= 1e-9:
        raise ValueError('The chord must have a positive length.')
    if not all(math.isfinite(values[key]) for key, _, _ in PARAMETERS):
        raise ValueError('Airfoil parameters must be finite.')
    if values['te'] < 0 or values['smoothness'] < 0:
        raise ValueError('TE thickness and smoothness must not be negative.')
    for key in ('upper_count', 'lower_count'):
        if values[key] != int(values[key]) or not config.MIN_CP_COUNT <= values[key] <= config.MAX_CP_COUNT:
            raise ValueError('Control point counts must be whole numbers from 4 to 19.')
    if values['continuity'] not in (1, 2, 3):
        raise ValueError('LE continuity must be 1, 2 or 3.')


class AirfoilFitError(RuntimeError):
    """The requested fit failed; AirfoilSplines does not accept weaker continuity."""


def fit_data(recipe, values, chord_length):
    """Common numerical path for preview, insertion and feature recompute."""
    validate(values, chord_length)
    return deepcopy(_fit_cached(recipe['dat'], values['te'] / chord_length,
                                values['smoothness'], int(values['upper_count']),
                                int(values['lower_count']), int(values['continuity'])))


def fit(recipe, values, chord_length):
    data = fit_data(recipe, values, chord_length)
    return (data['upper_cp_raw'], data['upper_knots'], data['degree_u'],
            data['lower_cp_raw'], data['lower_knots'], data['degree_l'])


@lru_cache(maxsize=16)
def _load_source(dat):
    processor = AirfoilProcessor(logger_func=lambda message: None)
    if not processor.load_text(dat):
        raise ValueError('Cannot load the embedded airfoil data.')
    return processor


def source_te_thickness(dat):
    return _load_source(dat).get_te_thickness()


@lru_cache(maxsize=64)
def _fit_cached(dat, te, smoothness, upper_count, lower_count, continuity):
    processor = _load_source(dat)
    upper, lower = apply_te_thickness_to_reference(
        processor.upper_data, processor.lower_data, te)
    # Choosing a single span is an AirfoilSplines policy, expressed numerically.
    bspline = BSplineProcessor(degree=(upper_count - 1, lower_count - 1))
    result = bspline.fit_bspline(
        upper, lower, num_control_points=(upper_count, lower_count),
        smoothing_weight=smoothness, continuity=continuity,
        upper_te_tangent_vector=processor.upper_te_tangent_vector,
        lower_te_tangent_vector=processor.lower_te_tangent_vector)
    if not result:
        raise AirfoilFitError(f'Cannot fit the airfoil with G{continuity} continuity: {result.message}')
    raw_upper, raw_lower = processor.error_reference_data()
    error_upper, error_lower = apply_te_thickness_to_reference(raw_upper, raw_lower, te)

    def error(curve, reference, exponent):
        _, maximum, index, _ = bspline_helper.calculate_bspline_fitting_error(
            curve, reference, param_exponent=exponent, return_max_error=True)
        return maximum, reference[index].copy()

    err_u, point_u = error(bspline.upper_curve, error_upper, bspline.param_exponent_upper)
    err_l, point_l = error(bspline.lower_curve, error_lower, bspline.param_exponent_lower)
    return dict(
        upper_cp_raw=bspline.upper_control_points, lower_cp_raw=bspline.lower_control_points,
        upper_knots=bspline.upper_knot_vector, lower_knots=bspline.lower_knot_vector,
        degree_u=bspline.degree_upper, degree_l=bspline.degree_lower,
        is_sharp=bspline.is_sharp_te, err_u=err_u, err_l=err_l,
        max_err_pt_u=point_u, max_err_pt_l=point_l,
        raw_upper=raw_upper, raw_lower=raw_lower, error_upper=error_upper, error_lower=error_lower,
        fit_upper=upper, fit_lower=lower,
        param_exponent_upper=bspline.param_exponent_upper,
        param_exponent_lower=bspline.param_exponent_lower,
        te_value=te, enforce_g2=continuity >= 2, enforce_g3=continuity == 3,
        fit_result=result)
