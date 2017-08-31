#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""
This module sets up:
    * iterating over timeseries
    * defining regions for stationary analysis
    * defining computation options for stationary analysis
"""
import os
import string
import warnings
import numpy as np
import pandas as pd

from tuna import Parser
from tuna.base.experiment import Experiment
from tuna.io import text


def iter_timeseries_(parser, observable, conditions, size=None):
    """Iterator over :class:`TimeSeries` instances from lineages in parser.

    TimeSeries are generated by browing Lineages instances from parser,
    retrieving observable values as defined un Observable, under different
    conditions defined in Conditions

    Parameters
    ----------
    parser : :class:`Parser` instance
    observable : :class:`Observable` instance
    conditions : list of :class:`FilterSet` instances

    size : int (default None)
        when not None, limit the iterator to size items.

    Yields
    ------
    :class:`TimeSeries` instance
    """
    for lineage in parser.iter_lineages(mode='all', size=size):
        ts = lineage.get_timeseries(observable, conditions)
        yield ts
    return


def iter_timeseries_2(parser, obs1, obs2, conditions, size=None):
    """Iterator over couples :class:`TimeSeries` instances

    :class:`TimeSeries` are generated by browing :class:`Lineage` instances
    from parser, retrieving observable values as defined in obs1 and obs2,
    under different conditions.

    Parameters
    ----------
    parser : :class:`Parser` instance
    obs1 : :class:`Observable` instance
    obs2 : :class:`Observable` instance
    conditions : list of :class:`FilterSet` instances
    size : int (default None)
        when not None, limit the iterator to size items.

    Yields
    ------
    Couple of :class:`TimeSeries` instances
    """
    for lineage in parser.iter_lineages(mode='all', size=size):
        ts1 = lineage.get_timeseries(obs1, conditions)
        ts2 = lineage.get_timeseries(obs2, conditions)
        yield (ts1, ts2)
    return


class CompuParamsError(ValueError):
    pass


class CompuParams(object):
    """Options for the computation of statistics under stationary hypothesis
    """

    def __init__(self, adjust_mean='global', disjoint=True):
        if adjust_mean not in ['global', 'local']:
            raise CompuParamsError('adjust mean must one of global, local')
        self.adjust_mean = adjust_mean
        if not isinstance(disjoint, bool):
            raise CompuParamsError('disjoint must be boolean: True, False')
        self.disjoint = disjoint
        return

    def as_string_code(self):
        code = ''
        code += self.adjust_mean[0]
        if self.disjoint:
            code += 'd'
        return code

    def load_from_string_code(self, code):
        if not isinstance(code, str):
            raise CompuParamsError('argument must be a string')
        if code[0] == 'g':
            self.adjust_mean = 'global'
        elif code[0] == 'l':
            self.adjust_mean = 'local'
        else:
            raise CompuParamsError('adjust_mean not valid in {}'.format(code))
        self.disjoint = False
        if len(code) > 1:
            if code[1] == 'd':
                self.disjoint = True
            else:
                raise CompuParamsError('string {} not valid'.format(code))
        return


class RegionsIOError(IOError):
    pass


class UndefinedRegion(ValueError):
    pass


class Regions(object):
    """Class that stores regions for stationary analysis.

    A region is defined by lower- and upper-bound for times.

    Parameters
    ----------
    exp : :class:`Experiment` instance or :class:`Parser` instance
    """

    def __init__(self, exp):
        if isinstance(exp, Experiment):
            self.exp = exp
        elif isinstance(exp, Parser):
            self.exp = exp.experiment
        else:
            raise TypeError('first arg must be either Experiment or Parser')
        self._df = pd.DataFrame({'tmin': [], 'tmax': []},
                                columns=['tmin', 'tmax'],
                                index=pd.Index([], name='label')
                                )
        try:
            self.load_from_text()
        except RegionsIOError:
            print('No regions have been saved yet. '
                  'Looking for experiment boundaries...')
            tmin, tmax = _find_time_boundaries(self.exp)
            self.add(label='ALL', tmin=tmin, tmax=tmax, verbose=True)
        return

    def __repr__(self):
        return repr(self._df)

    def load_from_text(self):
        analysis_path = text.get_analysis_path(self.exp, write=False)
        text_file = os.path.join(analysis_path, 'regions.tsv')
        if not os.path.exists(text_file):
            raise RegionsIOError
        regs = pd.read_csv(text_file, sep='\t', index_col='label')
        self._df = regs[['tmin', 'tmax']]
        return

    def save_to_text(self):
        if self._df is not None:
            analysis_path = text.get_analysis_path(self.exp, write=True)
            text_file = os.path.join(analysis_path, 'regions.tsv')
            self._df.to_csv(text_file, sep='\t',
                            index_label=self._df.index.name)
        return

    def add(self, label=None, tmin=None, tmax=None, verbose=True):
        """Add a new region to existing frame.

        Parameters
        ----------
        params : dict
            keys: label, tmin, tmax
        """
        # check that label is not used yet
        if label is not None and label in self._df.index:
            msg = ('Label {} already exists.'.format(label) + '\n'
                   'Change label to add this region.')
            if verbose:
                print(msg)
            else:
                warnings.warn(msg)
            return
        params = {}
        if tmin is None:
            params['tmin'] = -np.infty
        else:
            params['tmin'] = tmin
        if tmax is None:
            params['tmax'] = np.infty
        else:
            params['tmax'] = tmax
        # check that these parameters do not correspond to a stored item
        for item in self._df.itertuples():
            if (item.tmin == params['tmin'] and item.tmax == params['tmax']):
                msg = 'Input params correspond to region {}'.format(item.Index)
                msg += ' Use this label in .get()'
                if verbose:
                    print(msg)
                return
        if label is not None:
            letter = label
        # find a label starting with 'A', 'B', ..., 'Z', then 'A1', 'B1', ...
        else:
            got_it = False
            num = 0
            while not got_it:
                upper = string.ascii_uppercase
                index = 0
                while index < 26:
                    if num == 0:
                        letter = upper[index]
                    else:
                        letter = upper[index] + '{}'.format(num)
                    if letter not in self._df.index:
                        got_it = True
                        break
                    index += 1
                num += 1
        if verbose:
            msg = ('Adding region {} with parameters:'.format(letter) + '\n'
                   'tmin: {}'.format(params['tmin']) + '\n'
                   'tmax: {}'.format(params['tmax']))
            print(msg)
        self._df = self._df.append(pd.Series(params, name=letter))
        # automatic saving
        self.save_to_text()
        return

    def delete(self, label):
        """Delete label region

        Parameters
        ----------
        label : str
            label of the region to delete
        """
        self._df = self._df.drop(label)
        self.save_to_text()
        return

    def get(self, label):
        """Get region parameters corresponding to label
        """
        if label not in self._df.index:
            raise UndefinedRegion(label)
        return self._df.loc[label]


def _find_time_boundaries(exp):
    """Returns min and max value for time values

    Parameters
    ----------
    exp : :class:`tuna.base.experiment.Experiment` instance
    """
    tleft, tright = np.infty, -np.infty
    for container in exp.iter_container(read=True, build=False):
        tmin = np.nanmin(container.data['time'])
        tmax = np.nanmax(container.data['time'])
        if tmin < tleft:
            tleft = tmin
        if tmax > tright:
            tright = tmax
    return tleft, tright
