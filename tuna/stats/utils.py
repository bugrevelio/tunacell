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
import csv
import warnings
import numpy as np

from tuna.base.parser import Parser
from tuna.base.experiment import Experiment
from tuna.io import text


def iter_timeseries_(exp, observable, conditions, size=None):
    """Iterator over :class:`TimeSeries` instances from lineages in exp.

    TimeSeries are generated by browing Lineages instances from exp,
    retrieving observable values as defined un Observable, under different
    conditions defined in Conditions

    Parameters
    ----------
    exp : :class:`Experiment` instance
    observable : :class:`Observable` instance
    conditions : list of :class:`FilterSet` instances

    size : int (default None)
        when not None, limit the iterator to size items.

    Yields
    ------
    :class:`TimeSeries` instance
    """
    for lineage in exp.iter_lineages(size=size):
        ts = lineage.get_timeseries(observable, conditions)
        yield ts
    return


def iter_timeseries_2(exp, obs1, obs2, conditions, size=None):
    """Iterator over couples :class:`TimeSeries` instances

    :class:`TimeSeries` are generated by browing :class:`Lineage` instances
    from exp, retrieving observable values as defined in obs1 and obs2,
    under different conditions.

    Parameters
    ----------
    exp : :class:`Experiment` instance
    obs1 : :class:`Observable` instance
    obs2 : :class:`Observable` instance
    conditions : list of :class:`FilterSet` instances
    size : int (default None)
        when not None, limit the iterator to size items.

    Yields
    ------
    Couple of :class:`TimeSeries` instances
    """
    for lineage in exp.iter_lineages(size=size):
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


class Region(object):
    """Minimal object that store region parameters

    Parameters
    ----------
    name : str
        name of region
    tmin : str, int, or float
        lower bound for acquisition time values
    tmax : float
        upper bound for acquisition time values
    """

    def __init__(self, name=None, tmin=None, tmax=None):
        self.name = name
        if isinstance(tmin, str):
            self.tmin = eval(tmin)  # will evaluate as int or float
        else:
            self.tmin = tmin
        if isinstance(tmax, str):
            self.tmax = eval(tmax)
        else:
            self.tmax = tmax
        return
    
    def as_dict(self):
        return {'name': self.name, 'tmin': self.tmin, 'tmax': self.tmax}

    def __repr__(self):
        msg = 'Region : {{name: {}, tmin: {}, tmax: {}}}'.format(self.name, self.tmin, self.tmax)
        return msg


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
        self._regions = {}  # dictionary name: region
        try:
            self.load()
        except RegionsIOError:
            print('No regions have been saved yet. '
                  'Looking for experiment boundaries...')
            tmin, tmax = _find_time_boundaries(self.exp)
            self.add(name='ALL', tmin=tmin, tmax=tmax, verbose=True)
        return

    @property
    def names(self):
        return list(self._regions)  # return list of keys

    def __repr__(self):
        text_file = self._path_to_file(write=False)
        with open(text_file, 'r') as f:
            msg = f.read()
        return msg

    def _path_to_file(self, write=False):
        analysis_path = text.get_analysis_path(self.exp, write=write)
        text_file = os.path.join(analysis_path, 'regions.tsv')
        if not os.path.exists(text_file) and not write:
            raise RegionsIOError
        return text_file

    def load(self):
        text_file = self._path_to_file(write=False)
        with open(text_file, 'r') as f:
            items = csv.DictReader(f, delimiter='\t')
            for item in items:  # item is a dict with keys name, tmin, tmax
                name = item['name']
                self._regions[name] = item
        return

    def save(self):
        if self._regions is not None:
            text_file = self._path_to_file(write=True)
            with open(text_file, 'w') as f:
                fieldnames = ['name', 'tmin', 'tmax']
                writer = csv.DictWriter(f, fieldnames, delimiter='\t')
                writer.writeheader()
                # sort rows
                names = sorted(self._regions.keys())
                for name in names:
                    item = self._regions[name]
                    writer.writerow(item)
        return

    def add(self, region=None, name=None, tmin=None, tmax=None, verbose=True):
        """Add a new region to existing frame.

        Parameters
        ----------
        region : :class:`Region` instance
            when left to None, following keyword arguments are used
        name : str
            name of region to be added
        tmin : float
            lower bound for acquisition time values
        tmax : float
            upper bound for acquisition time values
        verbose : bool {True, False}
            whether to display information on screen
        """
        item = {}  # dict of 3 items name, tmin, tmax
        if region is not None and isinstance(region, Region):
            # check that name is not used yet
            if region.name in self.names:
                msg = ('name {} already exists.'.format(name) + '\n'
                       'Change name to add this region.')
                if verbose:
                    print(msg)
                else:
                    warnings.warn(msg)
                return
            item = region.as_dict()
        # otherwise use other keyword arguments
        else:
            # check that name is not used yet
            if name is not None and name in self.names:
                msg = ('name {} already exists.'.format(name) + '\n'
                       'Change name to add this region.')
                if verbose:
                    print(msg)
                else:
                    warnings.warn(msg)
                return
            item = {'name': name, 'tmin': tmin, 'tmax': tmax}
        # check that these parameters do not correspond to a stored item
        for key, reg in self._regions.items():
            if (reg['tmin'] == item['tmin'] and reg['tmax'] == item['tmax']):
                msg = 'Input params correspond to region {}'.format(reg.name)
                msg += ' Use this name in .get()'
                if verbose:
                    print(msg)
                return
        # okay we can add the region to the list of regions
        # find a name starting with 'A', 'B', ..., 'Z', then 'A1', 'B1', ...
        if item['name'] is None:
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
                    if letter not in self.names:
                        got_it = True
                        break
                    index += 1
                num += 1
            item['name'] = letter
        if verbose:
            msg = ('Adding region {} with parameters:'.format(item['name']) + '\n'
                   'tmin: {}'.format(item['tmin']) + '\n'
                   'tmax: {}'.format(item['tmax']))
            print(msg)
        self._regions[item['name']] = item
        # automatic saving
        self.save()
        return

    def delete(self, name):
        """Delete name region

        Parameters
        ----------
        name : str
            name of the region to delete
        """
        if name in self.names:
            del self._regions[name]
        self.save()
        return

    def reset(self):
        """Delete all regions except 'ALL'"""
        names = self.names[:]
        for name in names:
            if name != 'ALL':
                self.delete(name)
        return

    def get(self, name):
        """Get region parameters corresponding to name

        Parameters
        ----------
        name : str
            name of region

        Returns
        -------
        :class:`Region` instance

        Raises
        ------
        :class:`UndefinedRegion` when name is not in the list
        """
        if name not in self.names:
            raise UndefinedRegion(name)
        item = self._regions[name]
        return Region(**item)


def _find_time_boundaries(exp):
    """Returns min and max value for time values

    Parameters
    ----------
    exp : :class:`tuna.base.experiment.Experiment` instance
    """
    tleft, tright = np.infty, -np.infty
    for container in exp.iter_containers(read=True, build=False):
        tmin = np.nanmin(container.data['time'])
        tmax = np.nanmax(container.data['time'])
        if tmin < tleft:
            tleft = tmin
        if tmax > tright:
            tright = tmax
    return tleft, tright
