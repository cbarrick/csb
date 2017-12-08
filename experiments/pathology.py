#!/usr/bin/env python3
import argparse
import logging
from types import SimpleNamespace

import numpy as np
import sklearn.metrics

import torch
import torch.nn as N
import torch.optim as O

from datasets.pathology import NucleiSegmentation
from datasets.pathology import EpitheliumSegmentation
from datasets.pathology import TubuleSegmentation
from networks import AlexNet
from estimators.ewc import EwcClassifier
from metrics import true_positives, false_positives, true_negatives, false_negatives
from metrics import accuracy, precision, recall, f_score


logger = logging.getLogger()


def seed(n):
    '''Seed the RNGs of stdlib, numpy, and torch.'''
    import random
    import numpy as np
    import torch
    random.seed(n)
    np.random.seed(n)
    torch.manual_seed(n)
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
    kwargs.setdefault('task', ['+nuclei', '-nuclei'])
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
        'nuclei': NucleiSegmentation(n=args.data_size, k=args.folds, size=32),
        'epi': EpitheliumSegmentation(n=args.data_size, k=args.folds, size=32),
        'tubule': TubuleSegmentation(n=args.data_size, k=args.folds, size=32),
    }

    if args.name is None:
        now = np.datetime64('now')
        args.name = f'{args.tasks}-{now}'
        logger.info(f'experiment name not given, defaulting to {args.name}')

    # In some cases, we must move the network to it's cuda device before
    # constructing the optimizer. This is annoying, and this logic is
    # duplicated in the estimator class. Ideally, I'd like the estimator to
    # handle cuda allocation _after_ the optimizer has been constructed...
    net = AlexNet(2, shape=(3, 32, 32))
    if args.cuda is None:
        args.cuda = 0 if torch.cuda.is_available() else False
    if args.cuda is not False:
        net = net.cuda(args.cuda)

    for f in range(args.folds):
        print(f'================================ Fold {f} ================================')
        opt = O.Adagrad(net.parameters(), lr=args.learning_rate, weight_decay=0.004)
        loss = N.CrossEntropyLoss()
        model = EwcClassifier(net, opt, loss, name=args.name, cuda=args.cuda, dry_run=args.dry_run)

        for task in args.tasks:
            data = datasets[task[1:]]
            train, validation, test = data.load(f)

            if task[0] == '+':
                print(f'-------- Fitting {task[1:]} --------')
                model.fit(train, validation, epochs=args.epochs, patience=args.patience, batch_size=args.batch_size)
                model.consolidate(validation, alpha=args.ewc, batch_size=args.batch_size)
                print()

            if task[0] == '-':
                print(f'-------- Scoring {task[1:]} --------')
                scores = {
                    'accuracy': model.test(test, accuracy, batch_size=args.batch_size),
                    'true_positives': model.test(test, true_positives, batch_size=args.batch_size),
                    'false_positives': model.test(test, false_positives, batch_size=args.batch_size),
                    'true_negatives': model.test(test, true_negatives, batch_size=args.batch_size),
                    'false_negatives': model.test(test, false_negatives, batch_size=args.batch_size),
                    'precision': model.test(test, precision, batch_size=args.batch_size),
                    'recall': model.test(test, recall, batch_size=args.batch_size),
                    'f-score': model.test(test, f_score, batch_size=args.batch_size),
                }
                for metric in scores:
                    print(f'{metric:.10}: {scores[metric]}')
                print()

            if args.dry_run:
                break


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Run an experiment.',
        add_help=False,
        argument_default=argparse.SUPPRESS,
    )

    group = parser.add_argument_group('Required')
    group.add_argument('tasks', metavar='TASK', nargs='+', help='The tasks for this experiment.')

    group = parser.add_argument_group('Hyper-parameters')
    group.add_argument('-n', '--data-size', metavar='N', type=int, help='The number of training samples is a function of N.')
    group.add_argument('-k', '--folds', metavar='N', type=int, help='The number of cross-validation folds.')
    group.add_argument('-e', '--epochs', metavar='N', type=int, help='The maximum number of epochs per task.')
    group.add_argument('-l', '--learning-rate', metavar='N', type=float, help='The learning rate.')
    group.add_argument('-p', '--patience', metavar='N', type=int, help='Higher patience may help avoid local minima.')
    group.add_argument('-w', '--ewc', metavar='N', type=float, help='The regularization strength of ewc. Defaults to 0.')

    group = parser.add_argument_group('Performance')
    group.add_argument('-b', '--batch-size', metavar='N', type=int, help='The batch size.')
    group.add_argument('-c', '--cuda', metavar='N', type=int, help='Use the Nth cuda device.')

    group = parser.add_argument_group('Debugging')
    group.add_argument('-d', '--dry-run', action='store_true', help='Do a dry run to check for errors.')
    group.add_argument('-v', '--verbose', action='store_const', const='DEBUG', help='Turn on debug logging.')

    group = parser.add_argument_group('Other')
    group.add_argument('--seed', help='Sets the random seed for the experiment. Defaults to 1337.')
    group.add_argument('--name', type=str, help='Sets a name for the experiment.')
    group.add_argument('--help', action='help', help='Show this help message and exit.')

    args = parser.parse_args()
    main(**vars(args))
