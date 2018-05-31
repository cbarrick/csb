from abc import ABC, abstractmethod
from typing import Any, Callable, Tuple

import numpy as np

import torch
from torch.nn import Module

import toys
from toys.datasets.utils import Dataset, DataLoader, Flat, Zip
from toys.metrics import Accumulator
from toys.parsers import parse_dtype, parse_metric


Model = Callable
Estimator = Callable


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
            **kwargs (Any):
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
        self.cv_results = cv_results or {}

    def fit(self, *inputs, **hyperparams):
        params = {**self.params, **hyperparams}
        model = self.estimator(*inputs, **params)
        return model


class TorchModel(Model):
    '''A wrapper around PyTorch modules.

    This wrapper extends `torch.nn.Module` to accept both numpy arrays, and
    torch tensors as input and to return numpy arrays as output.

    ..note:
        A `TorchModel` is NOT a `torch.nn.Module`. Backprop graphs are not
        created during prediction.
    '''

    def __init__(self, module, classifier=False, device='cpu', dtype='float32'):
        '''Construct a `TorchModel`.

        Arguments:
            module (Module):
                The module being wrapped.
            classifier (bool):
                If true, the model returns the argmax of the module's
                prediction along axis 1.
            device (str or torch.device):
                The device on which to execute the model.
            dtype (str or torch.dtype):
                The dtype to which the module and inputs are cast.
        '''
        self.classifier = classifier
        self.device = torch.device(device)
        self.dtype = parse_dtype(dtype)
        self.module = module.to(self.device, self.dtype)

    def __getattr__(self, name):
        '''Attribute access is delecated to the underlying module.
        '''
        return getattr(self.module, name)

    def __call__(self, *inputs):
        '''Evaluate the model on some inputs.
        '''
        with torch.no_grad():
            inputs = self._cast_inputs(inputs)
            y = self.module(*inputs)
            y = y.numpy()
            if self.classifier:
                y = y.argmax(axis=1)
            return y

    def _cast_inputs(self, inputs):
        '''Cast inputs to tensors of the expected dtype, device, and dimension.
        '''
        for i, x in enumerate(inputs):
            if np.isscalar(x): x = np.array(x)
            if isinstance(x, np.ndarray): x = torch.from_numpy(x)
            x = x.to(self.device, self.dtype)
            yield x


# NOTE: zip is overloaded in this module.
def zip(*datasets):
    '''Returns a dataset with all of the columns of the given datasets.

    Arguments:
        datasets (Dataset):
            The datasets to combine.

    Returns:
        zipped (Dataset):
            The combined dataset.
    '''
    if len(datasets) == 1:
        return datasets[0]
    else:
        return Zip(*datasets)


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
