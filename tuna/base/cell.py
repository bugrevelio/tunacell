#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""
This module defines how cells are stored as tuna's objects
"""
from __future__ import print_function

import numpy as np
import warnings
from copy import deepcopy

import treelib as tlib


from tuna.datatools import (Coordinates, compute_rates,
                            extrapolate_endpoints,
                            derivative, logderivative, ExtrapolationError)


class CellError(Exception):
    pass


class CellChildsError(CellError):
    pass


class CellParentError(CellError):
    pass


class CellDivisionError(CellError):
    pass


class Cell(tlib.Node):
    """General class to handle cell data structure.

    Inherits from treelib.Node class to facilitate tree building.

    Parameters
    ----------
    identifier : str
        cell identifier
    container : :class:`Container` instance
        container to which cell belongs

    Attributes
    ----------
    container : :class:`Container` instance
        container to chich cell belongs
    childs : list of :class:`Cell` instances
        daughter cells of current cell
    parent : :class:`Cell` instance
        mother cell of current cell
    birth_time : float (default None)
        time of cell birth (needs to be computed)
    division_time : float (default None)
        time of cell division (needs to be computed)

    Methods
    -------
    set_division_events()
        computes birth/division times when possible
    build(obs)
        builds timeseries, uses one of the following methods depending on obs
    build_timelapse(obs)
        builds and stores timeseries associated to obs, in 'dynamics' mode
    build_cyclized(obs)
        builds and stores cell-cycle value associated to obs, not in 'dynamics'
        mode
    """

    def __init__(self, identifier=None, container=None):

        tlib.Node.__init__(self, identifier=identifier)

        self._childs = []
        self._parent = None
        self._birth_time = None
        self._division_time = None
        self._sdata = {}  # dictionary to contain computed data
        self.container = container  # point to Container instance
        # cells are built from a specific container instance
        # container can be a given field of view, a channel, a microcolony, ...

        return

    # We add few definitions to be able to chain between Cell instances
    @property
    def childs(self):
        "Get list of child instances."
        return self._childs

    @childs.setter
    def childs(self, value):
        if value is None:
            self._childs = []
        elif isinstance(value, list):
            for item in value:
                self.childs = item
        elif isinstance(value, Cell):
            self._childs.append(value)
        else:
            raise CellChildsError

    @property
    def parent(self):
        "Get parent instance."
        return self._parent

    @parent.setter
    def parent(self, pcell):
        if pcell is None:
            self._parent = None
        elif isinstance(pcell, Cell):
            self._parent = pcell
        else:
            raise CellParentError

    @property
    def birth_time(self):
        "Get cell cycle start time. See below for Setter."
        return self._birth_time

    @birth_time.setter
    def birth_time(self, value):
        "Set cell cycle start time. See above for Getter."
        self._birth_time = value

    @property
    def division_time(self):
        "Get cell cycle end time. See below for Setter."
        return self._division_time

    @division_time.setter
    def division_time(self, value):
        "Set cell cycle end time. See above for Getter."
        if self.birth_time is not None:
            if value < self.birth_time:
                raise CellDivisionError
        self._division_time = value

    def set_division_event(self):
        "method to call when parent is identified"
        previous_frame = None
        if (self.parent is not None) and (self.parent.data is not None):
            previous_frame = self.parent.data['time'][-1]

        first_frame = None
        if self.data is not None:
            first_frame = self.data['time'][0]

        if previous_frame is not None and first_frame is not None:
            div_time = (previous_frame + first_frame)/2.  # halfway
            self.birth_time = div_time
            self.parent.division_time = div_time

        return

    def __repr__(self):
        cid = str(self.identifier)
        if self.parent:
            pid = str(self.parent.identifier)
        else:
            pid = '-'
        if self.childs:
            ch = ','.join([c.identifier for c in self.childs])
        else:
            ch = '-'
        return cid+';p:'+pid+';ch:'+ch

    def info(self):
        dic = {}
        dic['a. Identifier'] = '{}'.format(self.identifier)
        pid = 'None'
        if self.parent:
            pid = '{}'.format(self.parent.identifier)
        dic['b. Parent id'] = pid
        chids = 'None'
        if self.childs:
            chids = ', '.join(['{}'.format(ch.identifier)
                               for ch in self.childs])
        dic['c. Childs'] = chids
        dic['d. Birth time'] = '{}'.format(self.birth_time)
        dic['e. Division time'] = '{}'.format(self.division_time)
        if self.data is not None:
            dic['f. N_frames'] = '{}'.format(len(self.data))
        return dic

    def build(self, obs):
        """Builds timeseries"""
        if obs.mode == 'dynamics':
            return self.build_timelapse(obs)
        else:
            return self.compute_cyclized(obs)

    def build_timelapse(self, obs):
        """Builds timeseries corresponding to observable of mode 'dynamics'.

        Result is an array of same length as time array, stored in a dictionary
        _sdata, which keys are obs.label(). When using sliding windows,
        estimate in a given cell actualize data in its parent cell, if and only
        if it has not been actualized before (check disjoint time intervals).

        Parameters
        ----------
        obs : Observable instance
            mode must be 'dynamics'

        Notes
        -----
        Some observables carry the 'local_fit' option True. In this case,
        local fits over shifting time-windows are performed. If one would keep
        only a given cell's data, then the constraints on shifting time-window
        would let some 'empty' times, at which no evaluation can be performed.
        This is solved by getting data from the cell's parent cell's data. This
        operation computes time-window fiited data in the cell's parent cycle.
        Two precautions must then be taken:
            1. a given cell's data must be used only once for evaluating parent
               cell's data,
            2. when data has been used from one daughter cell, concatenate
               the current cell's evaluated data to it.

        .. warning::
           For some computations, the time interval between consecutive
           acquisitions is needed. If it's defined in the container or the
           experiment metadata, this parameter will be imported; otherwise if
           there are at least 2 consecutive values, it will be inferred from
           data (at the risk of making mistakes if there are too many missing
           values)
        """
        label = str(obs.label())
        raw = obs.raw
        coords = Coordinates(self.data['time'], self.data[raw])
        if self.parent is not None and len(self.parent.data) > 0:
            anteriors = Coordinates(self.parent.data['time'],
                                    self.parent.data[raw])
        else:
            anteriors = Coordinates(np.array([], dtype=float),
                                    np.array([], dtype=float))
        # if empty, return empty array of appropriate type
        if len(self.data) == 0:  # there is no data, but it has some dtype
            return Coordinates(np.array([], dtype=float),
                               np.array([], dtype=float))

        dt = self.container.period
        if dt is None:
            # automatically finds dt
            if len(self.data) > 1:
                arr = self.data['time']
                time_increments = arr[1:] - arr[:-1]
                dt = np.round(np.amin(np.abs(time_increments)), decimals=2)

        # case : no local fit, use data, or finite differences
        if not obs.local_fit:
            if obs.differentiate:
                if obs.scale == 'linear':
                    if len(self.data) > 1:
                        new = derivative(coords)
                elif obs.scale == 'log':
                    if len(self.data) > 1:
                        new = logderivative(coords)
            else:
                new = coords
            self._sdata[label] = new.y

        # case : local estimates using  compute_rates
        else:
            r, f, ar, af, xx, yy = compute_rates(coords.x, coords.y,
                                                 x_break=self.birth_time,
                                                 anterior_x=anteriors.x,
                                                 anterior_y=anteriors.y,
                                                 scale=obs.scale,
                                                 time_window=obs.time_window,
                                                 dt=dt,
                                                 join_points=obs.join_points)
            if obs.differentiate:
                to_cell = r
                to_parent = ar
            else:
                to_cell = f
                to_parent = af
            self._sdata[label] = to_cell

            addendum = Coordinates(anteriors.x, to_parent)
            if label not in self.parent._sdata.keys():
                self.parent._sdata[label] = to_parent
            elif len(addendum.valid) > 0:
                existing = Coordinates(anteriors.x, self.parent._sdata[label])
                # test for disjoint time ranges
                if _disjoint_time_sets(existing.clear_x, addendum.clear_x):
                    self.parent._sdata[label][addendum.valid] = addendum.clear_y

        return

    def compute_cyclized(self, obs):
        """Computes observable when mode is different from 'dynamics'.

        Parameters
        ----------
        obs : Observable instance
            mode must be different from 'dynamics'

        Returns
        -------
        float corresponding to desired observable

        Raises
        ------
        ValueError
            when Observable mode is 'dynamics'
        """
        scale = obs.scale
        npts = obs.join_points
        label = obs.label()
        if obs.mode == 'dynamics':
            raise ValueError('Called build_cyclized for dynamics mode')
        # associate continous observable and build corresponding ._sdata
        cobs = deepcopy(obs)
        cobs.mode = 'dynamics'
        cobs.timing = 't'
        clabel = cobs.label()
        # discard result as it can mix cell, and parent cell data
        _ = self.build_timelapse(cobs)
        # now we compute cell cycle observable using created _sdata: only cell
        time = self._sdata[clabel]['time']
        array = self._sdata[clabel][clabel]
        # get value
        try:
            if obs.mode == 'birth':
                value = extrapolate_endpoints(self,
                                              zip(time, array),
                                              scale=scale,
                                              end_point='birth',
                                              join_points=npts)
            elif obs.mode == 'division':
                value = extrapolate_endpoints(self,
                                              zip(time, array),
                                              scale=scale,
                                              end_point='division',
                                              join_points=npts)
            elif 'net-increase' in obs.mode:
                dval = extrapolate_endpoints(self,
                                             zip(time, array),
                                             scale=scale,
                                             end_point='division',
                                             join_points=npts)
                bval = extrapolate_endpoints(self,
                                             zip(time, array),
                                             scale=scale,
                                             end_point='birth',
                                             join_points=npts)
                if obs.mode == 'net-increase-additive':
                    value = dval - bval
                elif obs.mode == 'net-increase-multiplicative':
                    value = dval/bval
            elif obs.mode == 'average':
                value = np.nanmean(array)
            elif obs.mode == 'rate':
                if obs.scale == 'log':
                    array = np.log(array)
                value, intercept = np.polyfit(time, array, 1)
        except ExtrapolationError as err:
            msg = '{}'.format(err)
            warnings.warn(msg)
            value = np.nan  # missing information
        self._sdata[label] = value
        return value


def _disjoint_time_sets(ts1, ts2):
    if len(ts1) == 0 or len(ts2) == 0:
        return True
    min1, min2 = map(np.nanmin, [ts1, ts2])
    max1, max2 = map(np.nanmax, [ts1, ts2])
    return max1 < min2 or max2 < min1
