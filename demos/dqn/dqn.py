import numpy as np
import scipy as sp
import tensorflow as tf

import csb


class ReplayMemory:
    '''A class for storing and sampling experience replay memories.'''

    def __init__(self, cap, obs_shape):
        self.index = 0
        self.len = 0
        self.cap = cap
        self.data = np.zeros(
            cap,
            dtype=[
                ('old_obs', 'f4', obs_shape),
                ('new_obs', 'f4', obs_shape),
                ('action', 'i4'),
                ('reward', 'f4'),
                ('done', 'bool'),
            ])

    def __len__(self):
        return self.len

    def push(self, old_obs, action, new_obs, reward, done):
        if self.len < self.cap:
            self.len += 1
        self.index = (self.index + 1) % self.cap
        row = self.data[self.index]
        row['old_obs'] = old_obs
        row['new_obs'] = new_obs
        row['action'] = action
        row['reward'] = reward
        row['done'] = done

    def sample(self, n):
        return np.random.choice(self.data[:self.len], n)


class DQN(csb.Model):
    def __init__(
            self,
            obs_shape,
            n_actions,
            memory_size=2**16,
            minibatch_size=32,
            learn_freq=4,
            target_update_freq=10000,
            replay_start=50000,
            discount_factor=0.99,
            exploration_initial=1,
            exploration_final=0.1,
            exploration_steps=1000000,
            optimizer=tf.train.AdamOptimizer(0.00025),
            name='dqn', ):

        # Hyper-parameters
        self.obs_shape = obs_shape
        self.n_actions = n_actions
        self.memory_size = memory_size
        self.minibatch_size = minibatch_size
        self.learn_freq = learn_freq
        self.target_update_freq = target_update_freq
        self.replay_start = replay_start
        self.discount_factor = discount_factor
        self.exploration_initial = exploration_initial
        self.exploration_final = exploration_final
        self.exploration_steps = exploration_steps
        self.optimizer = optimizer

        # Runtime state
        self.name = name
        self.memory = ReplayMemory(self.memory_size, self.obs_shape)
        self.online = self.new_session()
        self.offline = self.new_session()

    def act(self, obs):
        exploration = self.online.run(self.exploration)

        if len(self.memory) < self.memory_size:
            # Play randomly until memory buffer is full.
            action = np.random.randint(self.n_actions)

        elif np.random.random() < exploration:
            # Sometimes perform a random action.
            # The exploration value is annealed over time.
            action = np.random.randint(self.n_actions)

        else:
            # Otherwise choose the best predicted action.
            obs = np.expand_dims(obs, 0)
            q = self.online.run(self.q, {self.input: obs})
            action = np.argmax(q)

        return action

    def observe(self, obs, action, obs_next, reward, done, info):
        global_step = self.online.run(self.increment_global_step)

        # Clip the reward.
        if reward > 1: reward = 1.0
        elif reward < -1: reward = -1.0

        # Record the new memory.
        self.memory.push(obs, action, obs_next, reward, done)

        # Update the target network.
        if global_step % self.target_update_freq == 0:
            self.update_target()

        # Do the training, but only after an initial waiting period.
        if self.replay_start < global_step and global_step % self.learn_freq == 0:
            # Get the experiences and predictions to train on.
            replay = self.memory.sample(self.minibatch_size)
            prediction = self.online.run(self.q, {self.input: replay['old_obs']})

            # Compute the targets using the Double DQN technique.
            # 1. Decide on future actions using the online network.
            # 2. Compute their value using the target network.
            # 3. Construct the label as: reward + discount * future_value.
            online_q = self.online.run(self.q, {self.input: replay['new_obs']})
            offline_q = self.offline.run(self.q, {self.input: replay['new_obs']})
            actions = np.argmax(online_q, axis=1)
            future_value = np.choose(actions, offline_q.T)
            future_value = future_value * np.invert(replay['done'])
            q_label = replay['reward'] + self.discount_factor * future_value

            # Train!
            self.online.run(self.train, {
                self.input: replay['old_obs'],
                self.q_label: q_label,
                self.action_label: replay['action'],
            })

    def update_target(self):
        ckpt = self.save()
        self.load(ckpt)

    def save(self, ckpt=None):
        ckpt = ckpt or self.name + '.ckpt'
        return self.saver.save(self.online, ckpt, global_step=self.global_step)

    def load(self, ckpt):
        self.saver.restore(self.online, ckpt)
        self.saver.restore(self.offline, ckpt)

    def load_latest(self, ckpt_dir='.'):
        ckpt = tf.train.latest_checkpoint(ckpt_dir)
        self.load(ckpt)

    @csb.graph_property
    def input(self, scope):
        return tf.placeholder(tf.float32, (None, *self.obs_shape))

    @csb.graph_property
    def q(self, scope):
        defaults = {
            'activation': tf.nn.elu,
            'kernel_initializer': tf.contrib.layers.variance_scaling_initializer(),
        }
        y = self.input
        y = tf.layers.conv2d(y, filters=32, kernel_size=8, strides=4, **defaults)
        y = tf.layers.conv2d(y, filters=64, kernel_size=4, strides=2, **defaults)
        y = tf.layers.conv2d(y, filters=64, kernel_size=3, strides=1, **defaults)
        y = tf.contrib.layers.flatten(y)
        y = tf.layers.dense(y, units=512, **defaults)
        y = tf.layers.dense(y, units=self.n_actions, activation=None)
        return y

    @csb.graph_property
    def q_label(self, scope):
        return tf.placeholder(tf.float32, (None, ))

    @csb.graph_property
    def action_label(self, scope):
        return tf.placeholder(tf.int32, (None, ))

    @csb.graph_property
    def loss(self, scope):
        action_label = tf.one_hot(self.action_label, self.n_actions)
        q_label = tf.expand_dims(self.q_label, 1) * action_label
        q = self.q * action_label
        error = tf.losses.mean_squared_error(q_label, q)
        return tf.clip_by_value(error, -1, 1)

    @csb.graph_property
    def global_step(self, scope):
        return tf.train.create_global_step()

    @csb.graph_property
    def increment_global_step(self, scope):
        return tf.assign_add(self.global_step, 1)

    @csb.graph_property
    def exploration(self, scope):
        initial = float(self.exploration_initial)
        global_step = self.global_step
        steps = self.exploration_steps
        final = float(self.exploration_final)
        power = 1.0
        return tf.train.polynomial_decay(initial, global_step, steps, final, power)

    @csb.graph_property
    def train(self, scope):
        return self.optimizer.minimize(self.loss)

    @csb.graph_property
    def saver(self, scope):
        return tf.train.Saver()
