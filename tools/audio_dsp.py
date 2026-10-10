"""Optional host FFT acceleration; the portable Python implementation remains."""
from musdsp import fft as python_fft
import math

try:
    import numpy as _numpy
except ImportError:
    _numpy = None

BACKEND = {'name': 'numpy', 'version': _numpy.__version__} if _numpy is not None else {'name': 'python'}


def fft(values):
    if _numpy is not None:
        return _numpy.fft.fft(values).tolist()
    return python_fft(values)


def correlation_peak(values, span, low, high):
    """Locate a fractional lag without rounding each individual cycle."""
    if _numpy is not None:
        data=_numpy.asarray(values,dtype=float)
        first=data[:span];power=float(_numpy.dot(first,first))
        def correlation(lag):
            other=data[lag:lag+span]
            return float(_numpy.dot(first,other))/math.sqrt(max(1e-30,power*float(_numpy.dot(other,other))))
    else:
        first=values[:span];power=sum(v*v for v in first)
        def correlation(lag):
            other=values[lag:lag+span]
            return sum(a*b for a,b in zip(first,other))/math.sqrt(max(1e-30,power*sum(v*v for v in other)))
    scores={lag:correlation(lag) for lag in range(low-1,high+2)}
    best=max(range(low,high+1),key=scores.get)
    left,center,right=(scores[best+i] for i in (-1,0,1))
    denominator=left-2*center+right
    fraction=max(-.5,min(.5,.5*(left-right)/denominator)) if denominator else 0.
    return best+fraction,center
