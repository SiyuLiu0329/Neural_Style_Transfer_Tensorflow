import tensorflow as tf
from vgg_model import Model
from utilities import load_image
import numpy as np
from matplotlib.pyplot import imshow
import matplotlib.pyplot as plt
import scipy.misc


class NSTModel():
    def __init__(self, output_layer='conv5_2', h=300, w=400, style_path=None, content_path=None, input_image_path=None, style_weights=[0.5, 1, 2, 3, 4]):
        '''
        :param output_layer: layer to use when computing content loss
        :param h: height of image
        :param w: width of image
        :param style_path: path of the style image
        :param content_path: path of the content image
        :param style_weights: an list of 5 numbers
        :param input_image_path: initial image, usually a check point image generated by the last training session
        '''

        # layers from which the style features will be extracted
        self.STYLE_LAYERS = [
            ('conv1_1', style_weights[0]),
            ('conv2_1', style_weights[1]),
            ('conv3_1', style_weights[2]),
            ('conv4_1', style_weights[3]),
            ('conv5_1', style_weights[4])
        ]

        self._content_img = load_image(content_path, shape=[h, w], preprocess=True, bgr=False)
        self._style_img = load_image(style_path, shape=[h, w], preprocess=True, bgr=False)
        self._generated_img = None
        self._sess = tf.Session()
        
        # if the initial image is not sepcified, generate a new image and initialise it
        if input_image_path:
            self._generated_img = load_image(input_image_path, shape=[h, w], preprocess=True, bgr=False)
        else:
            self._generated_img = self._init_generated_image()

        # construct a vgg model with desired height and width
        self._vgg = Model('imagenet-vgg-verydeep-19.mat', img_h=h, img_w=w)

        # build the model and save the output node of the graph
        self._out = self._vgg.build_model(output=output_layer)
        self._sess.run(tf.global_variables_initializer())

        self._content_features = self._compute_content_features()

        # array to save layer outputs from layers specifed in 'self.STYLE_LAYERS'
        self._style_features = []
        self._compute_style_features()

    def run(self, num_iter=1000, output_folder="output", beta=1, alpha=2000, learning_rete=2.0):
        '''
        Start generating images and save the output every 10 iterations
        :param num_iter: number of iterations the optmiser will run
        :param output_folder: name of the folder to store generated images
        :param beta: content weight
        :param alpha: style weight
        '''
        content_loss = self._compute_content_loss(self._out)
        style_loss = self._compute_total_style_loss()
        total_loss = beta * content_loss + alpha * style_loss

        # L-BFGS-B generates better results than Adam in this use case
        optimizer = tf.contrib.opt.ScipyOptimizerInterface(total_loss, 
        method='L-BFGS-B', options={'maxiter': 10})

        self._sess.run(tf.global_variables_initializer())
        self._sess.run(self._vgg.tf_layers['input'].assign(self._generated_img))
        for i in range(num_iter):

            optimizer.minimize(self._sess)
            generated_img = self._sess.run(self._vgg.tf_layers['input'])
            current_loss = self._sess.run(total_loss)
            print('Iter' + str(i) + '0, Loss: ' + str(current_loss))
            self._save_image(output_folder + "/" + str(i * 10) + ".png", generated_img)

        self._sess.close()

    def _gram_mat(self, M):
        '''
        Compute the gram matrix of a given matrix
        :param M: matrix of which the gram matrix is to be computed
        :return: the gram matrix of the give matrix
        '''
        return tf.matmul(tf.transpose(M), M)

    def _save_image(self, path, image):
        '''
        Save an image to a specific path
        :param path: path to save the image to
        :param image: an image matrix, preprocessed for vgg networks
        '''

        # add the vgg means back to de-precess the image
        MEAN = [123.68, 116.779, 103.939]
        image = image + MEAN

        # save image to path
        image = np.clip(image[0], 0, 255).astype('uint8')
        scipy.misc.imsave(path, image)

    def _compute_layer_style_loss(self, ori_features, gen_features):
        '''
        computes the style loss of a layer
        :param ori_features: the layer output of the original style image
        :param gen_features: the layer output of the generated image
        :return: the style loss of the layer
        '''
        _, h, w, c = ori_features.shape
        # unroll before computing gram
        O = self._gram_mat(tf.reshape(ori_features, [h * w , c]))
        G = self._gram_mat(tf.reshape(gen_features, [h * w , c]))
        loss = (1./(4. * c**2 * (h * w) **2)) * tf.reduce_sum(tf.pow((G - O), 2))
        return loss

    def _compute_total_style_loss(self):
        '''
        :return: the total style loss across all layers specified in 'self.STYLE_LAYERS'
        
        '''
        loss = 0
        for i in range(len(self.STYLE_LAYERS)):
            ori_style_features = self._style_features[i]
            layer, coeff = self.STYLE_LAYERS[i]
            gen_style_features = self._vgg.tf_layers[layer]
            loss += coeff * self._compute_layer_style_loss(ori_style_features, gen_style_features)
        
        return loss

    def _compute_content_loss(self, generated_features):
        '''
        :param generated_features: layer output of the generated image
        :return: the content loss of the output layer
        '''
        _, h, w, c = self._content_features.shape
        loss = (1./ (2. * (h * w)**0.5 * c**0.5)) * tf.reduce_sum(tf.pow((generated_features - self._content_features), 2))
        return loss


    def _compute_content_features(self):
        '''
        :return: the layer output of the content image it the output layer
        '''
        op_assign_content_img = self._vgg.tf_layers['input'].assign(self._content_img)
        self._sess.run(op_assign_content_img)
        res = self._sess.run(self._out)
        return res
            
    def _compute_style_features(self):
        '''
        Computes layer outputs for all layers in 'self.STYLE_LAYERS' and append the results to 'self._style_features'
        '''
        op_assign_style_img = self._vgg.tf_layers['input'].assign(self._style_img)
        self._sess.run(op_assign_style_img)
        for layer, coeff in self.STYLE_LAYERS:
            out = self._vgg.tf_layers[layer]
            self._style_features.append(self._sess.run(out))

    def _init_generated_image(self, noise_ratio=0.1):
        noise = np.random.uniform(
        self._content_img.mean() - self._content_img.std(), self._content_img.mean() + self._content_img.std(),
        (self._content_img.shape)).astype('float32')
        input_image = noise * noise_ratio + self._content_img * (1 - noise_ratio)
        return input_image


