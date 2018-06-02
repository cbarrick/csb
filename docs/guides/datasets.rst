Datasets
==================================================

The :py:class:`~toys.typing.Dataset` protocol is borrowed from PyTorch and is the boundary between the preprocess and the model. The protocol is quite easy to implement. A dataset need only have methods :py:meth:`~object.__len__` and :py:meth:`~object.__getitem__` with integer indexing. Most simple collections can be used as datasets, including :py:class:`list`, :py:class:`tuple`, and :py:class:`~numpy.ndarray`.

We use the following vocabulary to describe datasets:

:Row: The value at ``dataset[i]`` is called the |ith| row of the dataset. Each row must be a sequence of arrays and/or scalars, and each array may be of different shape.

:Column: The positions in a row are called the columns.

:Supervised: A supervised dataset has at least two columns and further distinguishes between the **target column** and the **feature columns**. The target column is always the last; the rest are considered feature columns. In unsupervised datasets, all columns are considered feature columns.

:Feature: The data in any one feature column of a row is called a feature of that row.

:Target: Likewise, the data in the target column of a row is called the target of that row.

:Instance: The features of a row are collectively called an instance.

:Shape: The shape of a row is the sequence of shapes of its columns. The shape of a dataset is the shape of its rows.

For example, the :py:class:`~toys.datasets.CIFAR10` dataset is a supervised dataset with two columns. The feature column contains 32x32 pixel RGB images, and the target column contains integer class labels. The shape of the feature is ``(32, 32, 3)``, and the shape if the target is ``()`` (i.e. the target is a scalar). The shape of the CIFAR10 dataset is thus ``((32,32,3), ())``.

.. note::
    Unlike arrays, the columns of a dataset need not have the same shape across all rows. In fact, rows may have different shapes in the same column, or even different columns all together. The shape of a dataset (as opposed to a row or instance) may contain ``None`` to represent a variable sub-shape. Additionally, the shape of a dataset *does not include its length*.

.. |ith| replace:: i\ :sup:`th`


Combining datasets
--------------------------------------------------

The primary functions for combining datasets are :py:func:`toys.concat` and :py:func:`toys.zip` which concatenate datasets by rows and columns respectively.

.. todo::
	Add examples


Batching and iteration
--------------------------------------------------

The function :py:func:`toys.batches` iterates over mini-batches of a dataset by delegating to PyTorch's :py:class:`torch.utils.data.DataLoader` class. The :py:func:`~toys.batches` function forwards all of its arguments to the :py:class:`~torch.utils.data.DataLoader` constructor, but it allows the dataset to recommend default values through the :py:attr:`Dataset.hints` attribute. This allows the dataset to, e.g. specify an appropriate collate function or sampling strategy.

The most common arguments are:

:batch_size: The maximum number of rows per batch.

:shuffle: A boolean set to true to sample batches at random without replacement.

:collate_fn: A function to merge a list of samples into a mini-batch. This is required if the shape of the dataset is variable, e.g. to pad or pack a sequence length.

:pin_memory: If true, batches are loaded into CUDA pinned memory. Unlike vanilla PyTorch, this defaults to true whenever CUDA is available.

.. note::
	Most estimators will require an explicit ``batch_size`` argument when it can effect model performance. Thus the ``batch_size`` hint provided by the dataset is more influential to scoring functions than to estimators. Therefore the hinted value should be for scoring purposes and can be quite large.

.. seealso::
	See :py:class:`torch.utils.data.DataLoader` for a full description of all possible arguments.

.. todo::
	Add examples