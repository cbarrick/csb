from abc import ABC, abstractmethod
from io import StringIO
from typing import *

import numpy as np
import pandas as pd

import torch
from torch.nn import Module, DataParallel
from torch.utils.data import DataLoader

# The Protocol type does not exist until Python 3.7.
# TODO: Remove the try-except when Python 3.6 support is dropped.
try:
    from typing import Protocol
except ImportError:
    from abc import ABC as Protocol


class Dataset(Protocol):
    '''The dataset protocol.
    '''
    @abstractmethod
    def __len__(self):
        raise NotImplementedError

    @abstractmethod
    def __getitem__(self, index):
        raise NotImplementedError


class Estimator(Protocol):
    '''The estimator protocol.
    '''
    @abstractmethod
    def __call__(*args, **kwargs):
        raise NotImplementedError


class Model(Protocol):
    '''The model protocol.
    '''
    @abstractmethod
    def __call__(*args, **kwargs):
        raise NotImplementedError


class Metric(Protocol):
    '''The model protocol.
    '''
    @abstractmethod
    def __call__(*args, **kwargs):
        raise NotImplementedError


ArrayShape = Tuple[int, ...]
DatasetShape = Union[Tuple[Union[ArrayShape, None], ...], None]
CrossValSplitter = Callable[[Dataset], Iterable[Tuple[Sequence[int], Sequence[int]]]]
ParamGrid = Mapping[str, Sequence]


class BaseEstimator(ABC):
    '''A useful base class for estimators.

    An estimator is any callable that returns a model. The `BaseEstimator` base
    class provides a convenient API for implementing estimators.

    Instances of `BasesEstimator` follow the estimator protocol: they are
    functions that take a dataset to fit and keyword arguments for any
    hyperparameters. The constructor of a `BaseEstimator` accepts the very
    same keyword arguments. When a `BaseEstimator` is called directly (or via
    `__call__`), it delegates to `fit`, forwarding all keyword arguments as
    well as those passed to the constructor. In case of conflict, the arguments
    passed directly take priority.

    This upshot is that the constructor allows you to set the default
    hyperparameters.
    '''

    def __init__(self, **kwargs):
        '''Construct an estimator.

        Arguments:
            **kwargs:
                Overrides the default keyword arguments.
        '''
        super().__init__()
        self._kwargs = kwargs

    def __call__(self, *inputs, **kwargs):
        '''Construct a model, delegating to `fit`.

        Returns:
            model (Model):
                The model returned by `fit`.
        '''
        kwargs = {**self._kwargs, **kwargs}
        return self.fit(*inputs, **kwargs)

    @abstractmethod
    def fit(self, *inputs, **kwargs):
        '''Constructs a model.

        Subclasses must implement this method.

        The return value can be any callable, and is usually some learned
        function. Meta-estimators like `GridSearchCV` return other estimators.

        Arguments:
            inputs (Dataset):
                The inputs to fit.
            **kwargs:
                The hyperparameters to use while training the model.

        Returns:
            model (Model):
                Any arbitrary callable.
        '''
        raise NotImplementedError()


class TunedEstimator(BaseEstimator):
    '''A wrapper to override the default hyperparameters of an estimator.

    The new hyperparameters supplied by a `TunedEstimator`s are often learned
    by a meta-estimator, like `toys.model_selection.GridSearchCV`.

    Attributes:
        estimator (Estimator):
            The underlying estimator.
        params (Dict[str, Any]):
            The best hyperparameters found by the parameter search.
        cv_results (Dict[str, Any] or None):
            Overall results of the search which generated this estimator.
    '''
    def __init__(self, estimator, params, cv_results=None):
        super().__init__()
        self.estimator = estimator
        self.params = params
        self.cv_results = pd.DataFrame(cv_results)

    def fit(self, *inputs, **hyperparams):
        params = {**self.params, **hyperparams}
        model = self.estimator(*inputs, **params)
        return model


class TorchModel(Module):
    '''A convenience wrapper around PyTorch modules.

    .. todo::
        Document the conveniences.

    Arguments:
        module (Module):
            The module being wrapped.
        device_ids (Sequence[int]):
            A list of CUDA device IDs to use. The default is all devices.
        dtype (str or torch.dtype):
            The dtype to which the module and inputs are cast.
    '''
    def __init__(self, module, device_ids=None, dtype='float32'):
        from toys.parsers import parse_dtype

        super().__init__()

        if not isinstance(module, DataParallel):
            module = DataParallel(module, device_ids)

        self.device_ids = module.device_ids
        self.dtype = parse_dtype(dtype)
        self.module = module.to(self.dtype)
        self._train_mode = True

        self.train()

    def forward(self, *inputs):
        dtype = self.dtype
        module = self.module
        train_mode = self._train_mode

        inputs = list(inputs)
        for i, x in enumerate(inputs):
            if isinstance(x, np.ndarray):
                x = torch.from_numpy(x, dtype=dtype)
            x = x.to(dtype)
            inputs[i] = x

        with torch.autograd.set_grad_enabled(train_mode):
            y = module(*inputs)

        if not train_mode:
            y = y.numpy()

        return y

    def train(self, mode=True):
        self._train_mode = mode
        self.module.train(mode)
        return self


# Dataset utils
# --------------------------------------------------

def common_shape(shape1, shape2):
    if shape1 == shape2:
        return shape1
    if np.isscalar(shape1) or np.isscalar(shape2):
        return None
    if len(shape1) != len(shape2):
        return None
    return tuple(common_shape(a, b) for a, b in zip(shape1, shape2))


def shape(dataset):
    '''Infer the shape of the dataset.

    This function will sample up to four rows from the dataset to identify
    if any part of the shape is variable.

    Arguments:
        dataset (Dataset):
            The dataset whose shape will be checked.

    Returns:
        shape (DatasetShape):
            A tuple of array shapes, one for each column. If any part of the
            overall shape is variable, it is replaced by ``None``.
    '''
    get_shape = lambda x: getattr(x, 'shape', ())

    n = len(dataset)
    if n == 0: return None

    row1 = dataset[np.random.randint(n)]
    row2 = dataset[np.random.randint(n)]
    row3 = dataset[np.random.randint(n)]
    row4 = dataset[np.random.randint(n)]

    shape1 = tuple(get_shape(a) for a in row1)
    shape2 = tuple(get_shape(a) for a in row2)
    shape3 = tuple(get_shape(a) for a in row3)
    shape4 = tuple(get_shape(a) for a in row4)

    shape5 = common_shape(shape1, shape2)
    shape6 = common_shape(shape3, shape4)

    return common_shape(shape5, shape6)


# Subset
# --------------------------------------------------

class Subset(Dataset):
    '''A non-empty subset of some other dataset.

    Attributes:
        dataset (Dataset):
            The source dataset.
        indices (Sequence[int]):
            The indices of elements contained in this subset.
    '''
    def __init__(self, dataset, indices):
        assert 0 <= max(indices) < len(dataset)
        assert 0 <= min(indices) < len(dataset)
        self.dataset = dataset
        self.indices = indices

    def __len__(self):
        return len(self.indices)

    def __getitem__(self, index):
        i = self.indices[index]
        cols = self.dataset[i]
        return cols

    def __repr__(self):
        return f'Subset({repr(self.dataset)}, {repr(self.indices)})'

    @property
    def hints(self):
        return getattr(self.dataset, 'hints', {})


def subset(dataset, indices):
    '''Select a subset of some dataset by row indices.

    Attributes:
        dataset (Dataset):
            The source dataset.
        indices (Sequence[int]):
            The indices of elements contained in this subset.
    '''
    return Subset(dataset, indices)


# Zip
# --------------------------------------------------

class Zip(Dataset):
    '''Combines the columns of many datasets into one.
    '''
    def __init__(self, *datasets):
        if len(datasets) == 0:
            raise TypeError('Zip() requires at least 1 dataset.')

        for d in datasets:
            if len(d) != len(datasets[0]):
                raise ValueError('Zip() requires all datasets to be the same length.')

        self.datasets = datasets

    def __len__(self):
        return len(self.datasets[0])

    def __getitem__(self, index):
        columns = []
        for dataset in self.datasets:
            x = dataset[index]
            columns.extend(x)
        return tuple(columns)

    def __repr__(self):
        buf = StringIO()
        buf.write('Zip(')
        datasets = (repr(ds) for ds in self.datasets)
        print(*datasets, sep=', ', end=')', file=buf)
        return buf.getvalue()

    @property
    def hints(self):
        ret = {}
        for ds in reversed(self.datasets):
            sub = getattr(ds, 'hints', {})
            ret.update(sub)
        return ret


# This is reexported as toys.zip.
# The underscore is used here to prevent overriding builtins.zip.
def zip_(*datasets):
    '''Returns a dataset with all of the columns of the given datasets.

    Arguments:
        datasets (Dataset):
            The datasets to combine.

    Returns:
        zipped (Dataset):
            The combined dataset.
    '''
    if len(datasets) == 0:
        raise TypeError('zip() requires at least 1 dataset.')
    if len(datasets) == 1:
        return datasets[0]
    else:
        return Zip(*datasets)


# Concat
# --------------------------------------------------

class Concat(Dataset):
    '''Combines the rows of many datasets into one.
    '''
    def __init__(self, *datasets):
        if len(datasets) == 0:
            raise TypeError('Concat() requires at least 1 dataset.')

        self.lens = tuple(len(d) for d in datasets)
        self.datasets = datasets

    def __len__(self):
        return sum(self.lens)

    def __getitem__(self, index):
        for i, n in enumerate(self.lens):
            if n <= index:
                index -= n
            else:
                return self.datasets[i][index]

    def __repr__(self):
        buf = StringIO()
        buf.write('Concat(')
        datasets = (repr(ds) for ds in self.datasets)
        print(*datasets, sep=', ', end=')', file=buf)
        return buf.getvalue()

    @property
    def hints(self):
        ret = {}
        for ds in reversed(self.datasets):
            sub = getattr(ds, 'hints', {})
            ret.update(sub)
        return ret


def concat(*datasets):
    '''Returns a dataset with all of the rows of the given datasets.

    Arguments:
        datasets (Dataset):
            The datasets to combine.

    Returns:
        concatenated (Dataset):
            The combined dataset.
    '''
    if len(datasets) == 0:
        raise TypeError('concat() requires at least 1 dataset.')
    if len(datasets) == 1:
        return datasets[0]
    else:
        return Concat(*datasets)


# Flatten
# --------------------------------------------------

class Flat(Dataset):
    '''Flatten and concatenate the columns of a dataset.

    If ``supervised=True``, then the rightmost column is flattened but not
    concatenated to the others, e.g. treat that column as the targets.
    '''
    def __init__(self, base, supervised=True):
        super().__init__()
        self.base = base
        self.supervised = supervised

    def __len__(self):
        return len(self.base)

    def __getitem__(self, index):
        *inputs, target = self.base[index]
        target = target.reshape(-1)
        inputs = [x.reshape(-1) for x in inputs]

        if self.supervised:
            inputs = np.concatenate(inputs)
            return inputs, target
        else:
            inputs.append(target)
            inputs = np.concatenate(inputs)
            return (inputs,)

    def __repr__(self):
        return f'Flat({repr(self.base)}, supervised={repr(self.supervised)})'

    @property
    def hints(self):
        return self.base.hints


def flatten(dataset, supervised=True):
    '''Returns a dataset whose columns are flattened and concatenated together.

    In supervised mode, the rightmost column is flattened but is kept as a
    separate column. This is for supervised estimators which expect a target
    value in a separate column.

    Arguments:
        dataset (Dataset):
            The dataset to flatten.
        supervised (bool):
            Operate in supervised mode.

    Returns:
        flattened (Dataset):
            The combined dataset. If supervised is False, the dataset contains
            a single column with a flat shape. If supervised is True, the
            dataset contains two columns with flat shape.
    '''
    cols = dataset[0]

    if supervised:
        assert 2 <= len(cols)

    if 3 <= len(cols):
        return Flat(dataset, supervised)

    if 2 == len(cols) and not supervised:
        return Flat(dataset, supervised)

    for col in cols:
        if len(col.shape) != 1:
            return Flat(dataset, supervised)

    # If we've got this far, the dataset is already flat
    return dataset


# Batching
# --------------------------------------------------

def batches(dataset, batch_size=0, **kwargs):
    '''Iterates over a dataset in batches.

    TODO: Document dataset hints.

    Arguments:
        dataset (Dataset):
            The dataset to iterate over.
        batch_size (int):
            The maximum size of the batches.

    Keyword Arguments:
        **kwargs:
            Keyword arguments are forwarded to `torch.utils.data.DataLoader`.

    Returns:
        batches (DataLoader):
            A PyTorch data loader.
    '''
    hints = getattr(dataset, 'hints', {})
    kwargs = {**hints, **kwargs}

    if batch_size is 0 and 'batch_size' not in hints:
            batch_size = len(dataset)

    kwargs.setdefault('pin_memory', torch.cuda.is_available())
    kwargs.setdefault('batch_size', batch_size)
    return DataLoader(dataset, **kwargs)
