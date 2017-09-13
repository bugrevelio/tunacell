#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""
This module provides API class definition to define observables.

Classes
-------

* :class:`Observable`: main object to define observables.

"""
from __future__ import print_function

import collections
import warnings
import inspect
import dill
import re
from copy import deepcopy


_re_codestring = 'T([a-z])([a-z]*\d*[\.,]*\d*)M([a-z\-]+)J(\d+)'


def _is_valid_codestring(codestring):
    chain = re.compile(_re_codestring)
    m = chain.match(codestring)
    if m:
        return True
    else:
        return False


class ObservableError(Exception):
    pass


class ObservableStringError(ObservableError):
    pass


class Observable(object):
    """Defines how to retrieve observables.

    Parameters
    ----------
    name : str
        user name for this observable (can be one of the raw observable)
    raw : str (default None)
        raw name of the observable: must be a column name of raw data, i.e.
        first element of one entry of Experiment.datatype
    differentiate : boolean (default False)
        whether to differentiate raw observable
    scale : str {'linear', 'log'}
        expected scaling form as a function of time
        (used for extrapolating values at boundaries, including in the
        local_fit procedure)
    local_fit : boolean (default False)
        whether to perform local fit procedure
    time_window : float (default 20.)
        Time window over which local fit procedure is applied
        (used only when local_fit is activated)
    join_points : int (default 3)
        number of points over which extrapolation procedure is led by
        fitting linearly [the scale of] the observable w.r.t time
    mode : str {'dynamics', 'birth', 'division', 'net_increase', 'rate',
        'average'}
        mode used to retrieve data:
            * 'dynamics': all timepoints are retrieved
            * 'birth': only birth value is retrieved
            * 'division': only division value is retrieved
            * 'net-increase-additive': difference between division value
               and birth value
            * 'net-increase-multiplicative': ratio between division value
               and birth value
            * 'rate': rate of linear fit of [scale of] observable
            * 'average': average of observable over cell cycle
    timing : str {'t', 'b', 'd', 'm', 'g'}
        set the time at which cell cycle observable is associated:
            * 't' : time-lapse timing (associated to mode 'dynamics')
            * 'b' : cell cycle birth time
            * 'd' : cell cycle division time
            * 'm' : cell cycle midpoint (half time)
            * 'g' : cell cycle generation index
    tref : float or 'root' (default None)
        when timing is set to 'g', sets the 0th generation to the cell
        that bounds this reference time
        when timing is set to 't' (time-lapse timing), allows to translate time
        values by substracting floating point value (if given as a float), or
        aligns to the colony root cell last time value as origin.
    """

    def __init__(self, name=None, from_string=None,
                 raw=None, differentiate=False, scale='linear',
                 local_fit=False, time_window=0., join_points=3,
                 mode='dynamics', timing='t', tref=None):
        self._attr_names = ['name',
                            'raw',
                            'scale',
                            'differentiate',
                            'local_fit',
                            'time_window',
                            'join_points',
                            'mode',
                            'timing',
                            'tref']
        if from_string is not None:
            self.load_from_string(from_string)
        else:
            self.name = name
            self.raw = raw
#            # warn if raw is 'none'
#            if raw == 'none':
#                msg = ("'raw' is set to 'none'.\n"
#                       "Update to a valid column name of your experiment.")
#                warnings.warn(msg)
            self.differentiate = differentiate
            self.scale = scale
            self.local_fit = local_fit
            self.time_window = time_window
            self.join_points = join_points
            self.mode = mode
            self.timing = timing
            self.tref = tref
        return

    def as_timelapse(self):
        """Convert current observable to its dynamic counterpart

        This is needed when computing cell-cycle observables.
        """
        if self.mode == 'dynamics' and self.timing == 't':
            # everything's fine
            return self
        else:
            tobs = deepcopy(self)
            tobs.mode = 'dynamics'
            tobs.timing = 't'
            tobs.name = '_timelapsed_' + self.name
            return tobs

    @property
    def label(self):
        """Label is outputing a unique string representation

        This method creates a string label that specifies each parameter to
        re-construct the Observable. The output string is
        (kind-of) human readable. More importantly, it is suitable
        to be a filename (only alphanumeric caracters, and underscores), and in
        fact serves to name directories in analysis folder.

        Note
        ----
        :func:`__repr__` : returns another string representation, that can be
        called by the built-in :func:`eval()`, to instantiate a new object
        with identical functional parameters.
        """
        msg = ''
        # timing is in between T flags
        if self.tref is not None:
            if isinstance(self.tref, float):
                stref = '{:.2f}'.format(self.tref)
            elif isinstance(self.tref, int) or isinstance(self.tref, str):
                stref = '{}'.format(self.tref)
        else:
            stref = ''
        msg += 'T' + self.timing + stref
        # mode is in between M flags
        msg += 'M' + self.mode
        msg += 'J' + '{}'.format(self.join_points)
        msg += '_'
        if self.differentiate:
            msg += 'dot_'
        if self.local_fit:
            msg += 'W{:.2f}_'.format(self.time_window)
        if self.scale == 'log':
            msg += 'log_'
        msg += self.raw
        return msg

    @label.setter
    def label(self, value):
        """Set Observable instance using given codestring"""
        self.load_from_string(value)

    def load_from_string(self, codestring):
        """Set Observable instance from string code created by `label` method

        Parameters
        ----------
        codestring : str
            must follow some rules for parsing
        """
        # set options to default and update if found
        self.mode = 'dynamics'
        self.timing = 't'
        self.local_fit = False
        self.time_window = 0.
        self.join_points = 3  # default
        self.differentiate = False
        self.scale = 'linear'
        items = codestring.split('_')
        self.raw = items[-1]  # last item is always raw observable label
        if self.raw == 'none':
            msg = ("'raw' is set to 'none'.\n"
                   "Update to a valid column name of your experiment.")
            warnings.warn(msg)

        # test whether codestring is valid: must have T and M flags
        chain = re.compile(_re_codestring)
        m = chain.match(codestring)
        if m:
            timing, stref, mode, sjoin = m.groups()
            self.timing = timing
            if stref:
                if stref == 'root':
                    self.tref = 'root'
                else:  # convert to float
                    self.tref = float(stref.replace(',', '.'))  # if decimal is ,
            else:
                self.tref = None
            self.mode = mode
            self.join_points = int(sjoin)
        else:
            raise ObservableStringError('Not a valid codestring')

        # try to check whether local fit is performed and its parameters
        pfit = re.compile('W(\d*[.,]*\d*)')

        for item in items[:-1]:
            # local_fit?
            m = pfit.search(item)
            if m is not None:
                stime_window, = m.groups()
                # check that tw_str is not empty
                if stime_window:
                    self.time_window = float(stime_window.replace(',', '.'))
                    self.local_fit = True
            # log scale
            if item == 'log':
                self.scale = 'log'
            if item == 'dot':
                self.differentiate = True
        return

    def as_string_table(self):
        """Human readable output as a table.
        """
        msg = ''
        column_size = 14

        def formatting(items):
                out = ' | '.join(['{}'.format(items[0]).rjust(column_size),
                                  '{}'.format(items[1]).ljust(column_size)])
                return out

        msg += formatting(['parameter', 'value'])
        msg += '\n' + formatting(['----', '----'])
        for key in self._attr_names:
            val = self.__getattribute__(key)
            msg += '\n' + formatting([key, val])
        msg += '\n'
        return msg

    @property
    def as_latex_string(self):
        """Export as LaTeX string.
        """
        output = r'$'
        if self.name is not None:
            output += '\\mathrm{{ {} }}'.format(self.name.replace('-', '\, ').replace('_', '\ '))
        else:
            # give all details using raw and operations on it
            if self.differentiate:
                output += '\\frac{\\mathrm{d}}{\\mathrm{d}t}'
                if self.scale == 'log':
                    output += '\\log\\left['  # parenthesis started
            variable_name = '{}'.format(self.raw)
            output += '\\mathrm{{ {} }}'.format(variable_name.replace('_', '\ ').replace('-', '\, '))
            if self.differentiate and self.scale == 'log':
                output += '\\right]'  # parenthesis closed
            if self.mode != 'dynamics':
                output += '_{{\mathrm{{ {} }} }}'.format(self.mode)

        # timing character
        time_char = ''
        if self.timing == 't':
            time_char += 't'
        elif self.timing == 'b':
            time_char += 't_{\\mathrm{birth}}'
        elif self.timing == 'd':
            time_char += 't_{\\mathrm{div}}'
        elif self.timing == 'm':
            time_char += ('\\frac{t_{\\mathrm{birth}} + t_{\\mathrm{div}}}'
                          '{2}')
        elif self.timing == 'g':
            time_char += 'n_{\\mathrm{gen}}'
        # substract troot
        to_substract = ''
        if self.tref is None:
            to_substract += ''
        elif self.tref == 'root':
            if self.timing != 'g':
                to_substract += '- t^{\\mathrm{root}}_{\mathrm{div}}'
            else:
                to_substract += '- n^{\\mathrm{root}}_{\mathrm{gen}}'
        else:
            if self.timing != 'g':
                to_substract += '- {:.2f}'.format(self.tref)
            else:
                to_substract += '- n_{{\mathrm{{gen}} }}({:.2f})'.format(self.tref)
        within_parenthesis = time_char + to_substract
        
        output += '\\left( {} \\right)'.format(within_parenthesis)

        if self.local_fit:
            output += '\\ [window: {}]'.format(self.time_window)
        output += '$'
        return output

    def __str__(self):
        return self.label

    def __repr__(self):
        name = type(self).__name__
        chain = name + '('
        for key in self._attr_names:
            val = self.__getattribute__(key)
            chain += '{}={}, '.format(key, repr(val))
        chain += ')'
        return chain


class FunctionalObservable(object):
    """Combination of :class:`Observable` instances

    Parameters
    ----------
    name : str
        user defined name for this observable
    f : callable
        the function to apply to observables
    observables : list of :class:`Observable` instances
        parameters of the function f to be applied

    Warning
    -------
    Contrary to :class:`Observable`, instances of :class:`FunctionalObservable`
    cannot be represented as a string using :func:`repr()`, that could be
    turned into a new instance with identical parameters using :func:`eval()`.
    This is due to the applied function, difficult to serialize as a string
    AND keeping a human-readable format to read its definition.
    """

    def __init__(self, name=None, f=None, observables=[]):
        if name is None:
            raise ValueError('name must be a unique name string')
        self.name = name
        if not callable(f):
            raise ValueError('f must be callable')
        self.f = f
        self.source_f = dill.dumps(f)
        argspec = inspect.getargspec(f)
        self.observables = observables
        self.raw_observables = unroll_raw_obs(observables)
        if len(observables) != len(argspec.args):
            msg = ('length of observable list must match number of arguments of f ')
            raise ValueError(msg)
        for obs in observables:
            if not (isinstance(obs, Observable) or isinstance(obs, FunctionalObservable)):
                msg = ('observables argument must be a list of Observables '
                       'instances')
                raise TypeError(msg)
        return

    @property
    def timing(self):
        """Return timing depending on observables passed as parameters"""
        timings = []
        for item in self.observables:
            timings.append(item.timing)
        if 't' in timings:
            return 't'
        else:
            return timings[0]  # default

    @property
    def tref(self):
        # tref is used only when timing is 'g' (generations)
        if self.timing == 'g':
            t = self.observables[0].tref
        else:
            t = None
        return t

    @property
    def mode(self):
        """Returns mode depending on observables passed as parameters"""
        modes = []
        for item in self.observables:
            modes.append(item.mode)
        if 'dynamics' in modes:
            return 'dynamics'
        else:
            return 'cell-cycle'

    @property
    def label(self):
        """get unique string identifier"""
        msg = self.name + '('
        for item in self.observables:
            msg += item.label + ', '
        msg += ')'
        return msg
    
    @property
    def as_latex_string(self):
        args = r''
        for item in self.observables:
            args += item.as_latex_string + ', '
        args = args.replace('$', '').rstrip(',')
        msg = r'$f( {} )$'.format(args)
        return msg


def unroll_raw_obs(obs, flatten=[]):
    """Returns flattened list of Observable instances

    Parameters
    ----------
    obs : (list of) :class:`Observable` or :class:`FunctionalObservable` instances

    Returns
    -------
    flatten
        list of :class:`Observable` instances found in argument list, going
        into nested layers in the case of nested list, or for
        :class:`FunctionalObservable` instances
    """
    if isinstance(obs, Observable):
        flatten.append(obs)
    elif isinstance(obs, collections.Iterable):
        for item in obs:
            unroll_raw_obs(item, flatten)
    elif isinstance(obs, FunctionalObservable):
        for item in obs.observables:
            unroll_raw_obs(item, flatten)
    return flatten

def unroll_func_obs(obs, flatten=[]):
    """Returns flattened list of FunctionalObservable instances

    It inspect recursively the observable content of the argument to list
    all nested FunctionalObservable instances

    Parameters
    ----------
    obs : :class:`FunctionalObservable` instance
        the observable to inspect

    Returns
    -------
    flatten
        list of :class:`FunctionalObservable` instances found in nested layers.
        Note that flatten is directly ordered: run the build in direct order.
    """
    if isinstance(obs, FunctionalObservable):
        for item in obs:
            unroll_func_obs(item, flatten)
        flatten.append(obs)
    return flatten

def set_observable_list(*args, filters=[]):
    """Make raw, and functional observable lists for running analyses

    Parameters
    ----------
    args : list of :class:`Observable` or :class:`FunctionalObservable` instances
    filters : list of :class:`tuna.filters.main.FilterSet` isntances
        where observables may be hidden

    Returns
    -------
    raw_obs, func_obs
        lists of raw observables, functional observables (correctly ordered)
    """
    raw_obs = []
    func_obs = []
    # run through observables used in filtering
    for filt in filters:
        for obs in unroll_raw_obs(filt.obs):
            if obs not in raw_obs:
                raw_obs.append(obs)
        for obs in unroll_func_obs(filt.obs):
            if obs not in func_obs:
                func_obs.append(obs)
    for observable in args:
        # extend with all raw Observable instances found in obs
        for obs in unroll_raw_obs(observable):
            if obs not in raw_obs:
                raw_obs.append(obs)
        # extend with all FunctionalObservable instances found in obs
        for obs in unroll_func_obs(observable):
            if obs not in func_obs:
                func_obs.append(obs)
    return raw_obs, func_obs


if __name__ == '__main__':
    length = Observable('length', raw='length', scale='log')
    width = Observable('width', raw='width')
    def volume(x, y):
        return x * y**2
    combo = FunctionalObservable('volume', volume, [length, width])
    divlength = Observable('divlength', raw='length', scale='log',
                           mode='division', timing='d')
    newcombo = FunctionalObservable('resc_length', f=lambda x, y: x/y, observables=[length, divlength])
    print(length.label == divlength.as_timelapse().label)