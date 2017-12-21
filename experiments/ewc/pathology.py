#!/usr/bin/env python3
import argparse
import logging
from types import SimpleNamespace

import numpy as np
import torch

import datasets as D
import estimators as E
import metrics as M
import networks as N
import optim as O


logger = logging.getLogger()


def seed(n):
    '''Seed the RNGs of stdlib, numpy, and torch.'''
    import random
    import numpy as np
    import torch
    random.seed(n)
    np.random.seed(n)
    torch.manual_seed(n)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(n)


def main(**kwargs):
    kwargs.setdefault('data_size', 500)
    kwargs.setdefault('folds', 5)
    kwargs.setdefault('epochs', 600)
    kwargs.setdefault('learning_rate', 0.001)
    kwargs.setdefault('patience', None)
    kwargs.setdefault('ewc', 0)
    kwargs.setdefault('batch_size', 128)
    kwargs.setdefault('cuda', None)
    kwargs.setdefault('dry_run', False)
    kwargs.setdefault('name', None)
    kwargs.setdefault('seed', 1337)
    kwargs.setdefault('verbose', 'WARN')
    kwargs.setdefault('tasks', ['+nuclei', '-nuclei'])
    args = SimpleNamespace(**kwargs)

    logging.basicConfig(
        level=args.verbose,
        style='{',
        format='[{levelname:.4}][{asctime}][{name}:{lineno}] {msg}',
    )

    logger.debug('parameters of this experiment')
    for key, val in args.__dict__.items():
        logger.debug(f' {key:.15}: {val}')

    seed(args.seed)

    datasets = {
        'nuclei': D.pathology.NucleiSegmentation(n=args.data_size, k=args.folds, size=32),
        'epi': D.pathology.EpitheliumSegmentation(n=args.data_size, k=args.folds, size=32),
        'tubule': D.pathology.TubuleSegmentation(n=args.data_size, k=args.folds, size=32),
    }

    if args.name is None:
        now = np.datetime64('now')
        args.name = f'exp-{now}'
        logger.info(f'experiment name not given, defaulting to {args.name}')

    # In some cases, we must move the network to it's cuda device before
    # constructing the optimizer. This is annoying, and this logic is
    # duplicated in the estimator class. Ideally, I'd like the estimator to
    # handle cuda allocation _after_ the optimizer has been constructed...
    net = N.AlexNet((3, 32, 32), ndim=2)
    if args.cuda is None:
        args.cuda = 0 if torch.cuda.is_available() else False
    if args.cuda is not False:
        net = net.cuda(args.cuda)

    for f in range(args.folds):
        print(f'================================ Fold {f} ================================')
        opt = O.Adagrad(net.parameters(), lr=args.learning_rate, weight_decay=0.004)
        loss = N.CrossEntropyLoss()
        model = E.ewc.Classifier(net, opt, loss, name=args.name, cuda=args.cuda, dry_run=args.dry_run)

        for task in args.tasks:
            data = datasets[task[1:]]
            train, validation, test = data.load(f)

            if task[0] == '+':
                print(f'-------- Fitting {task[1:]} --------')
                reports = {'f-score': M.FScore()}
                model.fit(train, validation, epochs=args.epochs, patience=args.patience, reports=reports, batch_size=args.batch_size)
                model.consolidate(validation, alpha=args.ewc, batch_size=args.batch_size)
                print()

            if task[0] == '-':
                print(f'-------- Scoring {task[1:]} --------')
                scores = {
                    'accuracy': M.Accuracy(),
                    'true positives': M.TruePositives(),
                    'false positives': M.FalsePositives(),
                    'true negatives': M.TrueNegatives(),
                    'false negatives': M.FalseNegatives(),
                    'precision': M.Precision(),
                    'recall': M.Recall(),
                    'f-score': M.FScore(),
                }
                for metric, criteria in scores.items():
                    score = model.test(test, criteria, batch_size=args.batch_size)
                    print(f'{metric:15}: {score}')
                print()

            if args.dry_run:
                break


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        add_help=False,
        argument_default=argparse.SUPPRESS,
        formatter_class=argparse.RawTextHelpFormatter,
        description=(
            'Runs an experiment.\n'
            '\n'
            'Tasks are specified with either a plus (+) or a minus (-) followed by the\n'
            'name of a dataset. Tasks beginning with a plus fit the model to the dataset,\n'
            'while tasks beginning with a minus test the model against a dataset.\n'
            '\n'
            'For example, the default task list of `+nuclei -nuclei` will first fit the\n'
            'model to the nuclei dataset, then test against against the nuclei dataset.\n'
            'EWC terms are computed after each fitting and are used for subsequent fits.\n'
            '\n'
            'Since tasks may begin with a minus (-) you need to separate the task list\n'
            'from the other arguments by using a double-dash (--). For example:\n'
            '\n'
            '    python -m experiments.pathology --cuda=0 -- +nuclei -nuclei\n'
            '\n'
            'Note that the experiment is intended to be executed from the root of the\n'
            'repository using `python -m`.'
        ),
        epilog=(
            'Datasets:\n'
            '  nuclei   A nuclei segmentation dataset\n'
            '  epi      An epithelium segmentation dataset\n'
        ),
    )

    group = parser.add_argument_group('Hyper-parameters')
    group.add_argument('-n', '--data-size', metavar='X', type=int)
    group.add_argument('-k', '--folds', metavar='X', type=int)
    group.add_argument('-e', '--epochs', metavar='X', type=int)
    group.add_argument('-l', '--learning-rate', metavar='X', type=float)
    group.add_argument('-p', '--patience', metavar='X', type=int)
    group.add_argument('-w', '--ewc', metavar='X', type=float)

    group = parser.add_argument_group('Performance')
    group.add_argument('-b', '--batch-size', metavar='X', type=int)
    group.add_argument('-c', '--cuda', metavar='X', type=int)

    group = parser.add_argument_group('Debugging')
    group.add_argument('-d', '--dry-run', action='store_true')
    group.add_argument('-v', '--verbose', action='store_const', const='DEBUG')

    group = parser.add_argument_group('Other')
    group.add_argument('--seed')
    group.add_argument('--name', type=str)
    group.add_argument('--help', action='help')

    group = parser.add_argument_group('Positional')
    group.add_argument('tasks', metavar='TASK', nargs='*')

    args = parser.parse_args()
    main(**vars(args))
