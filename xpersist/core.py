import os

import uuid

from toolz import curry

import xarray as xr
import dask

from . import settings

__all__ = ["persisted_Dataset", "persist_ds"]

_actions = {'read_cache_trusted', 'read_cache_verified', 'overwrite_cache', 'create_cache'}
_formats = {'nc'}

class persisted_Dataset(object):
    """
    Generate an `xarray.Dataset` from a function and cache the result to file.
    If the cache file exists, don't recompute, but read back in from file.

    Attempt to detect changes in the function and arguments used to generate the dataset,
    to ensure that the cache file is correct (i.e., it was produced by the same function
    called with the same arguments).

    On the first call, however, assume the cache file is correct, unless forced override.
    """

    # class property, dictionary: {cache_file: tokenized_name, ...}
    _tokens = {}

    # class property
    _actions = {}

    def __init__(self, func, name=None, path=None, format='nc', open_ds_kwargs={}):
        """set instance attributes"""
        self._func = func

        self._name = name
        if self._name is None:
            self._name = uuid.uuid4()

        self._path = path
        if self._path is None:
            self._path = settings['cache_dir']

        if format not in _formats:
            raise ValueError(f'unknown format: {format}')
        self._format = format

        self._open_ds_kwargs = open_ds_kwargs


    def _check_token_assign_action(self, token):
        """check for matching token, if appropriate"""

        if self._cache_exists:
            # if the cache file is present and we know about it,
            # check the token; if the token doesn't match, remove the file
            if self._cache_file in persisted_Dataset._tokens:
                if token != persisted_Dataset._tokens[self._cache_file]:
                    print(f'name mismatch, removing: {self._cache_file}')
                    os.remove(self._cache_file)
                    persisted_Dataset._actions[self._cache_file] = 'overwrite_cache'
                else:
                    persisted_Dataset._actions[self._cache_file] = 'read_cache_verified'

            # if we don't yet know about this file, assume it's the right one;
            # this enables usage on first call in a Python session, for instance
            else:
                print(f'assuming cache is correct')
                persisted_Dataset._tokens[self._cache_file] = token
                persisted_Dataset._actions[self._cache_file] = 'read_cache_trusted'
        else:
            persisted_Dataset._tokens[self._cache_file] = token
            persisted_Dataset._actions[self._cache_file] = 'create_cache'
            if os.path.dirname(self._cache_file):
                print('making '+os.path.dirname(self._cache_file))
                os.makedirs(os.path.dirname(self._cache_file), exist_ok=True)

        assert persisted_Dataset._actions[self._cache_file] in _actions

    @property
    def _basename(self):
        if self._name.endswith('.'+self._format):
            return self._name
        else:
            return f'{self._name}.{self._format}'

    @property
    def _cache_file(self):
        return os.path.join(self._path, self._basename)

    @property
    def _cache_exists(self):
        """does the cache exist?"""
        return os.path.exists(self._cache_file)

    def __call__(self, *args, **kwargs):
        """call function or read cache"""

        token = dask.base.tokenize(self._func, args, kwargs)
        self._check_token_assign_action(token)

        if {'read_cache_trusted', 'read_cache_verified'}.intersection({self._actions[self._cache_file]}):
            print(f'reading cached file: {self._cache_file}')
            return xr.open_dataset(self._cache_file, **self._open_ds_kwargs)

        elif {'create_cache', 'overwrite_cache'}.intersection({self._actions[self._cache_file]}):
            # generate dataset
            ds = self._func(*args, **kwargs)

            # write dataset
            print(f'writing cache file: {self._cache_file}')
            ds.to_netcdf(self._cache_file)

            return ds



@curry
def persist_ds(func, name=None, path=None, format='nc', open_ds_kwargs={}):
    """Wraps a function to produce a ``persisted_Dataset``.

    Parameters
    ----------

    func : callable
       The function to execute: ds = func(*args, **kwargs)
       Must return an `xarray.dataset`
    file_name : string, optional
       Name of the cache file.
    open_ds_kwargs : dict, optional
       Keyword arguments to `xarray.open_dataset`.

    Examples
    -------
    Apply to function:

    >>> def func(scaleby):
    ...   return xr.Dataset({'x': xr.DataArray(np.ones((50,))*scaleby)})

    >>> func(10)
    <xarray.Dataset>
    Dimensions:  (dim_0: 50)
    Dimensions without coordinates: dim_0
    Data variables:
        x        (dim_0) float64 10.0 10.0 10.0 10.0 10.0 ... 10.0 10.0 10.0 10.0

    >>> ds = xpersist(func, name='func_output')(10)
    >>> ds
    Dimensions:  (dim_0: 50)
    Dimensions without coordinates: dim_0
    Data variables:
        x        (dim_0) float64 10.0 10.0 10.0 10.0 10.0 ... 10.0 10.0 10.0 10.0

    Can be used as a decorator:

    >>> @xpersist(name='func_output')
    ... def func(scaleby):
    ...   return xr.Dataset({'x': xr.DataArray([np.ones(50)*scaleby])})

    """
    if not callable(func):
        raise ValueError('func must be callable')

    return persisted_Dataset(func, name, path, format, open_ds_kwargs)