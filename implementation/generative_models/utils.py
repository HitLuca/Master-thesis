import keras.backend as K
from keras import initializers, regularizers, constraints
from keras.engine import Layer, InputSpec
import numpy as np
from scipy.misc import imresize

import matplotlib
# matplotlib.use('Agg')
from matplotlib import pyplot as plt


def set_model_trainable(model, trainable):
    model.trainable = trainable
    for l in model.layers:
        l.trainable = trainable


def save_samples(generated_data, rows, columns, filenames, is_image):
    if is_image:
        plt.subplots(rows, columns, figsize=(7, 7))
    else:
        plt.subplots(rows, columns, figsize=(columns*3, rows))

    k = 1
    for i in range(rows):
        for j in range(columns):
            plt.subplot(rows, columns, k)
            if is_image:
                plt.imshow((generated_data[k - 1].reshape(10, 10) + 1.0) / 2.0)
            else:
                plt.plot(generated_data[k - 1].T)
                plt.ylim(-1, 1)
            plt.xticks([])
            plt.yticks([])
            k += 1
    plt.tight_layout()
    plt.subplots_adjust(wspace=0, hspace=0)
    for filename in filenames:
        plt.savefig(filename)
    plt.clf()
    plt.close()


def save_losses(losses, filename):
    plt.subplots(2, 1, figsize=(15, 9))
    plt.subplot(2, 1, 1)
    plt.plot(losses[0])
    plt.plot(losses[1])
    plt.legend(['generator', 'critic'])
    plt.subplot(2, 1, 2)
    plt.plot(losses[0][-1000:])
    plt.plot(losses[1][-1000:])
    plt.legend(['generator', 'critic'])
    plt.savefig(filename)
    plt.clf()
    plt.close()


def save_latent_space(generated_data, grid_size, filenames, is_image):
    if is_image:
        plt.subplots(grid_size, grid_size, figsize=(grid_size, grid_size))
    else:
        plt.subplots(grid_size, grid_size, figsize=(grid_size * 3, grid_size))

    for i in range(grid_size):
        for j in range(grid_size):
            plt.subplot(grid_size, grid_size, i * grid_size + j + 1)
            if is_image:
                plt.imshow((generated_data[i*grid_size + j].reshape(10, 10) + 1.0) / 2.0)
            else:
                plt.plot((generated_data[i * grid_size + j]).T)
                plt.ylim(-1, 1)
            plt.xticks([])
            plt.yticks([])
    plt.tight_layout()
    plt.subplots_adjust(wspace=0, hspace=0)
    for filename in filenames:
        plt.savefig(filename)
    plt.clf()
    plt.close()

    
def split_data(dataset, timesteps):
    D = dataset.shape[1]
    if D < timesteps:
        return None
    elif D == timesteps:
        return dataset
    else:
        splitted_data, remaining_data = np.hsplit(dataset, [timesteps])
        remaining_data = split_data(remaining_data, timesteps)
        if remaining_data is not None:
            return np.vstack([splitted_data, remaining_data])
        return splitted_data


def load_splitted_dataset(filepath, timesteps):
    dataset = np.load(filepath)
    dataset = split_data(dataset, timesteps)
    return dataset


def load_resized_mnist(size):
    from keras.datasets import mnist
    (x_train, y_train), _ = mnist.load_data()
    dataset = np.empty((60000, size, size))
    for row in range(x_train.shape[0]):
        dataset[row] = imresize(x_train[row], (size, size))
    dataset = (dataset / 255.0) * 2.0 - 1.0
    dataset = dataset.reshape(60000, size * size)
    return dataset


def clip_weights(model, clip_value):
    for l in model.layers:
        weights = [np.clip(w, -clip_value, clip_value) for w in l.get_weights()]
        l.set_weights(weights)


def wasserstein_loss(y_true, y_pred):
    return K.mean(y_true * y_pred)


class MinibatchDiscrimination(Layer):
    """Concatenates to each sample information about how different the input
    features for that sample are from features of other samples in the same
    minibatch, as described in Salimans et. al. (2016). Useful for preventing
    GANs from collapsing to a single output. When using this layer, generated
    samples and reference samples should be in separate batches."""

    def __init__(self, nb_kernels, kernel_dim, init='glorot_uniform', weights=None,
                 W_regularizer=None, activity_regularizer=None,
                 W_constraint=None, input_dim=None, **kwargs):
        self.init = initializers.get(init)
        self.nb_kernels = nb_kernels
        self.kernel_dim = kernel_dim
        self.input_dim = input_dim

        self.W_regularizer = regularizers.get(W_regularizer)
        self.activity_regularizer = regularizers.get(activity_regularizer)

        self.W_constraint = constraints.get(W_constraint)

        self.initial_weights = weights
        self.input_spec = [InputSpec(ndim=2)]

        if self.input_dim:
            kwargs['input_shape'] = (self.input_dim,)
        super(MinibatchDiscrimination, self).__init__(**kwargs)

    def build(self, input_shape):
        assert len(input_shape) == 2

        input_dim = input_shape[1]
        self.input_spec = [InputSpec(dtype=K.floatx(),
                                     shape=(None, input_dim))]

        self.W = self.add_weight(shape=(self.nb_kernels, input_dim, self.kernel_dim),
            initializer=self.init,
            name='kernel',
            regularizer=self.W_regularizer,
            trainable=True,
            constraint=self.W_constraint)

        # Set built to true.
        super(MinibatchDiscrimination, self).build(input_shape)

    def call(self, x, mask=None):
        activation = K.reshape(K.dot(x, self.W), (-1, self.nb_kernels, self.kernel_dim))
        diffs = K.expand_dims(activation, 3) - K.expand_dims(K.permute_dimensions(activation, [1, 2, 0]), 0)
        abs_diffs = K.sum(K.abs(diffs), axis=2)
        minibatch_features = K.sum(K.exp(-abs_diffs), axis=2)
        # return K.concatenate([x, minibatch_features], 1)
        return minibatch_features

    def compute_output_shape(self, input_shape):
        assert input_shape and len(input_shape) == 2
        # return input_shape[0], input_shape[1]+self.nb_kernels
        return input_shape[0], self.nb_kernels

    def get_config(self):
        config = {'nb_kernels': self.nb_kernels,
                  'kernel_dim': self.kernel_dim,
                  # 'init': self.init.__name__,
                  'W_regularizer': self.W_regularizer.get_config() if self.W_regularizer else None,
                  'activity_regularizer': self.activity_regularizer.get_config() if self.activity_regularizer else None,
                  'W_constraint': self.W_constraint.get_config() if self.W_constraint else None,
                  'input_dim': self.input_dim}
        base_config = super(MinibatchDiscrimination, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))