import gym
import itertools
import numpy as np
import tensorflow as tf

import baselines.common.tf_util as U

from baselines import logger
from baselines import deepq
from baselines.deepq.replay_buffer import ReplayBuffer
from baselines.deepq.utils import BatchInput
from baselines.common.schedules import LinearSchedule

tf.logging.set_verbosity(tf.logging.INFO)


def convert_obs(obs):
    temp_s = np.zeros((32, 11, 2))
    s = list(obs)
    s[2] = int(s[2])

    temp_s[s[0], :, :] = 1
    temp_s[:, s[1], :] = 1
    temp_s[:, : s[2]] = 1

    return temp_s


def model(inpt, num_actions, scope, reuse=False):
    """This model takes as input an observation and returns values of all actions."""
    with tf.variable_scope(scope, reuse=reuse):
        out = tf.layers.conv2d(inpt, filters=32, kernel_size=[5, 5], padding='same', activation=tf.nn.relu)
        out = tf.layers.conv2d(out, filters=64, kernel_size=[5, 5], padding='same', activation=tf.nn.relu)
        out = tf.layers.conv2d(out, filters=128, kernel_size=[5, 5], padding='same', activation=tf.nn.relu)

        out = tf.contrib.layers.flatten(out)
        out = tf.layers.dense(out, 256, activation=tf.nn.relu)
        out = tf.layers.dense(out, 128, activation=tf.nn.relu)
        out = tf.layers.dense(out, num_actions)

        return out


if __name__ == '__main__':
    with U.make_session(8):
        env = gym.make('Blackjack-v0')

        act, train, update_target, debug = deepq.build_train(
            make_obs_ph=lambda name: BatchInput((32, 11, 2), name=name),
            q_func=model,
            num_actions=env.action_space.n,
            optimizer=tf.train.AdamOptimizer(learning_rate=5e-4),
        )

        # Create the replay buffer
        replay_buffer = ReplayBuffer(50000)
        # Create the schedule for exploration starting from 1 (every action is random) down to
        # 0.02 (98% of actions are selected according to values predicted by the model).
        exploration = LinearSchedule(schedule_timesteps=10000, initial_p=1.0, final_p=0.02)

        # Initialize the parameters and copy them to the target network.
        U.initialize()
        update_target()

        episode_rewards = [0.0]
        obs = convert_obs(env.reset())

        for t in itertools.count():
            # Take action and update exploration to the newest value
            action = act(obs[None], update_eps=exploration.value(t))[0]
            new_obs, rew, done, _ = env.step(action)
            new_obs = convert_obs(new_obs)

            # Store transition in the replay buffer.
            replay_buffer.add(obs, action, rew, new_obs, float(done))
            obs = new_obs

            episode_rewards[-1] += rew
            if done:
                obs = convert_obs(env.reset())
                episode_rewards.append(0)

            is_solved = t > 100 and np.mean(episode_rewards[-101:-1]) >= 200
            if is_solved:
                # Show off the result
                env.render()
            else:
                # Minimize the error in Bellman's equation on a batch sampled from replay buffer.
                if t > 1000:
                    obses_t, actions, rewards, obses_tp1, dones = replay_buffer.sample(32)
                    train(obses_t, actions, rewards, obses_tp1, dones, np.ones_like(rewards))
                # Update target network periodically.
                if t % 1000 == 0:
                    update_target()

            if done and len(episode_rewards) % 10 == 0:
                logger.record_tabular("steps", t)
                logger.record_tabular("episodes", len(episode_rewards))
                logger.record_tabular("mean episode reward", round(np.mean(episode_rewards[-101:-1]), 1))
                logger.record_tabular("% time spent exploring", int(100 * exploration.value(t)))
                logger.dump_tabular()
