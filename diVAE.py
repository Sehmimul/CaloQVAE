# -*- coding: utf-8 -*-
"""
Discrete Variational Autoencoder Class Structures

Author: Eric Drechsler (eric_drechsler@sfu.ca)

Based on work from Olivia di Matteo.
"""

import torch
import torch.nn as nn
import torch.distributions as dist
import numpy as np

from networks import Decoder,HierarchicalEncoder,SimpleEncoder,SimpleDecoder
from rbm import RBM

from copy import copy
import logging
logger = logging.getLogger(__name__)

torch.manual_seed(1)

class AEBase(nn.Module):
    def __init__(self, latent_dimensions=None, **kwargs):
        super(AEBase,self).__init__(**kwargs)
        self.type=None
        self._latent_dimensions=latent_dimensions

        # self.isTraining=isTraining

    def _create_encoder(self):
        raise NotImplementedError

    def _create_decoder(self):
        raise NotImplementedError
    
    def __repr__(self):
        parameter_string="\n".join([str(par) for par in self.__dict__.items()])
        return parameter_string
    
    def forward(self, x):
        raise NotImplementedError

    def print_model_info(self):
        for par in self.__dict__.items():
            logger.debug(par)

#AE implementation, base class for VAE and DiVAE
class AE(AEBase):

    def __init__(self, encoder_activation_fct=nn.ReLU(), **kwargs):
        super(AE,self).__init__(**kwargs)
        self.type="AE"
        
        self._encoder_nodes=[(784,128),(128,self._latent_dimensions)]
        self._decoder_nodes=[(self._latent_dimensions,128),(128,784)]
                
        # TODO replace the above with a more elegant solution
        # self.networkStructures={
        #     'encoder':[784,128,32],
        #     'decoder':[32,128,784]
        # }

        self.encoder=self._create_encoder(act_fct=encoder_activation_fct)
        self.decoder=self._create_decoder()
        
        #TODO which is the best loss function for AE? Research.
        # nn.BCELoss(x_true,x_recon)
        self._loss_fct= nn.functional.binary_cross_entropy

    def _create_encoder(self,act_fct=None):
        logger.debug("_create_encoder")
        # from networks import Unit
        return SimpleEncoder(node_sequence=self._encoder_nodes, activation_fct=act_fct)

    def _create_decoder(self):
        logger.debug("_create_decoder")
        return SimpleDecoder(node_sequence=self._decoder_nodes, activation_fct=nn.ReLU(), output_activation_fct=nn.Sigmoid())

    def forward(self, x):
        zeta = self.encoder.encode(x.view(-1, 784))
        x_recon = self.decoder.decode(zeta)
        return x_recon, zeta
    
    def loss(self, x_true, x_recon):
        return self._loss_fct(x_recon, x_true.view(-1, 784), reduction='sum')


#VAE implementation
class VAE(AEBase):
    def __init__(self, encoder_activation_fct=nn.ReLU(), **kwargs):
        super(VAE, self).__init__(**kwargs)
        
        self.type="VAE"

        self._encoder_nodes=[(784,128)]
        self._reparamNodes=(128,self._latent_dimensions)   
        self._decoder_nodes=[(self._latent_dimensions,128),(128,784)]

        self._reparamLayers=nn.ModuleDict(
            {'mu':nn.Linear(self._reparamNodes[0],self._reparamNodes[1]),
             'var':nn.Linear(self._reparamNodes[0],self._reparamNodes[1])
             })

        self.encoder=self._create_encoder(act_fct=encoder_activation_fct)
        self.decoder=self._create_decoder()

    def _create_encoder(self,act_fct=None):
        logger.debug("_create_encoder")
        return SimpleEncoder(node_sequence=self._encoder_nodes, activation_fct=act_fct)

    def _create_decoder(self):
        logger.debug("_create_decoder")
        return SimpleDecoder(node_sequence=self._decoder_nodes, activation_fct=nn.ReLU(), output_activation_fct=nn.Sigmoid())
        
    def reparameterize(self, mu, logvar):
        """ Sample from the normal distributions corres and return var * samples + mu
        """
        eps = torch.randn_like(mu)
        return mu + eps*torch.exp(0.5 * logvar)
        
    def loss(self, x, x_recon, mu, logvar):
        logger.debug("loss")
        # Autoencoding term
        auto_loss = torch.nn.functional.binary_cross_entropy(x_recon, x.view(-1, 784), reduction='sum')
        
        # KL loss term assuming Gaussian-distributed latent variables
        kl_loss = 0.5 * torch.sum(1 + logvar - mu.pow(2) - torch.exp(logvar))
        return auto_loss - kl_loss
                            
    def forward(self, x):
        x_prime = self.encoder.encode(x.view(-1, 784))
        mu = self._reparamLayers['mu'](x_prime)
        logvar = self._reparamLayers['var'](x_prime)
        zeta = self.reparameterize(mu, logvar)
        x_recon = self.decoder.decode(zeta)
        return x_recon, mu, logvar, zeta

class DiVAE(AEBase):
    def __init__(self, encoder_activation_fct=nn.ReLU(), n_hidden_units=256, **kwargs):
        super(DiVAE, self).__init__(**kwargs)
        self.type="DiVAE"

        self._encoder_nodes=[(784,128),]
        self._reparamNodes=(128,self._latent_dimensions)  
        self._decoder_nodes=[(self._latent_dimensions,128),]
        self._outputNodes=(128,784)     

        self._n_hidden_units=n_hidden_units

        #TODO change names globally
        #configs from DWave
        #TODO one wd factor for both SimpleDecoder and encoder
        self.weight_decay_factor=1e-4
        
        self.encoder_activation_fct=encoder_activation_fct
        self.encoder=self._create_encoder(act_fct=encoder_activation_fct)
        self.decoder=self._create_decoder()
        self.prior=self._create_prior()

    
    def _create_encoder(self,act_fct=None):
        logger.debug("ERROR _create_encoder dummy implementation")
        node_sequence=self._encoder_nodes+[self._reparamNodes]
        
        #number of hierarchy levels in encoder. This is the number of latent
        #layers. At each hiearchy level an output layer is formed.
        self.num_latent_hierarchy_levels=4

        #number of latent units in the prior - output units for each level of
        #the hierarchy. Also number of input nodes to the SimpleDecoder, first layer
        self.num_latent_units=100

        #each hierarchy has NN with num_det_layers_enc layers
        #number of deterministic units in each encoding layer. These layers map
        #input to the latent layer. 
        self.num_det_units=200
        
        # number of deterministic layers in each conditional p(z_i | z_{k<i})
        self.num_det_layers=2 

        # for all layers except latent (output)
        self.activation_fct=nn.Tanh()

        encoder=HierarchicalEncoder()
        return encoder

    def _create_decoder(self):
        logger.debug("_create_decoder")
        return Decoder()

    def _create_prior(self):
        logger.debug("_create_prior")
        return RBM(n_visible=self._latent_dimensions,n_hidden=self._n_hidden_units)
   
    def sigmoid_cross_entropy_with_logits(self,x_true,x_recon):
            logger.debug("WARNING sigmoid_cross_entropy_with_logits preliminary")
            # this is the equivalent to the DWave code's
            # sigmoid_cross_entropy_with_logits(): return logits * labels +
            # tf.nn.softplus(-logits)
            #z- logits (=output)
            #x- labels (=input data?)
            # TODO this implentation follows sigmoid_cross_entropy_with_logits
            # EXACTLY like DWave implementation
            #TODO check https://discuss.pytorch.org/t/equivalent-of-tensorflows-sigmoid-cross-entropy-with-logits-in-pytorch/1985/13
            #https://www.tensorflow.org/api_docs/python/tf/nn/sigmoid_cross_entropy_with_logits
            #max(x, 0) - x * z + log(1 + exp(-abs(x)))
            sp=torch.nn.Softplus()
            return torch.max(x_recon,torch.zeros(x_recon.size()))-x_recon*x_true-sp(torch.abs(x_recon))
 
    def weight_decay_loss(self):
        #TODO
        logger.debug("ERROR weight_decay_loss NOT IMPLEMENTED")
        return 0

    def loss(self, x, x_recon, posterior_distribution,posterior_samples):
        logger.debug("ERROR loss NOT CORRECTLY IMPLEMENTED")
        hierarchical_posterior=posterior_distribution
        prior=self.prior
        #this should be the equivalent to log_prob_per_var() which is the
        #sigmoid cross entropy with logits
        #log p(x|z) = logits - logits * labels + tf.nn.softplus(-logits)
        #=x-x*z+log(1+exp(-x))
        # cost = - output_dist.log_prob_per_var(input)
        #this returns a matrix 100x784 (samples times var)
        ae_loss_matrix = self.sigmoid_cross_entropy_with_logits(x_true=x.view(-1, 784)[0], x_recon=x_recon)
        #loss is the sum of all variables (pixels) per sample (event in batch)
        ae_loss=torch.sum(ae_loss_matrix, axis=1)
        if self.training:
            #kld per sample
            # total_kl = self.prior.kl_dist_from(posterior, post_samples, is_training)
            kl_loss=self.kl_divergence(hierarchical_posterior,posterior_samples)
            # # weight decay loss
            # enc_wd_loss = self.encoder.get_weight_decay()
            # dec_wd_loss = self.decoder.get_weight_decay()
            # prior_wd_loss = self.prior.get_weight_decay() if isinstance(self.prior, RBM) else 0
            weight_decay_loss=self.weight_decay_loss()
            neg_elbo_per_sample =  ae_loss+kl_loss 
        else:
            #kld per sample
            # total_kl = self.prior.kl_dist_from(posterior, post_samples, is_training)
            #TODO during evaluation - why is KLD necessary?
            kl_loss=self.kl_divergence(hierarchical_posterior,posterior_samples)
            # # weight decay loss
            # enc_wd_loss = self.encoder.get_weight_decay()
            # dec_wd_loss = self.decoder.get_weight_decay()
            # prior_wd_loss = self.prior.get_weight_decay() if isinstance(self.prior, RBM) else 0
            neg_elbo_per_sample =  ae_loss+kl_loss 
            #since we are not training
            weight_decay_loss=0 
        #the mean of the elbo over all samples is taken as measure for loss
        neg_elbo=torch.mean(neg_elbo_per_sample)    
        #include the weight decay regularisation in the loss to penalise complexity
        loss=neg_elbo+weight_decay_loss
        # return loss
        return loss

    def kl_div_prior_gradient(self, posterior , prior):
        logger.debug("ERROR kl_div_prior_gradient")
        return 0

    def kl_div_posterior_gradient(self, posterior , prior):
        logger.debug("ERROR kl_div_posterior_gradient")
        return 0

    def kl_divergence(self, posterior , posterior_samples):
        logger.debug("ERROR kl_divergence")
        if len(posterior)>1 and self._model.training: #this posterior has multiple latent layers
            logger.debug("ERROR kld for training posterior with more than one latent layer")
            kl_div_prior=self.kl_div_prior_gradient() #DVAE Eq11 - gradient of AE model
            kl_div_posterior=self.kl_div_posterior_gradient() #DVAE Eq12 - gradient of prior
            kld=kl_div_prior+kl_div_posterior
        else: # either this posterior only has one latent layer or we are not looking at training
            #this posterior is not hierarchical - a closed analytical form for the KLD term can be constructed
            #the mean-field solution (num_latent_hierarchy_levels == 1) reduces to log_ratio = 0.
            logger.debug("ERROR kld for evaluation/training of one layer posterior")
            entropy=0
            entropy_reduced=0
            cross_entropy=0
            # cross_entropy_reduced=0
            #TODO implement these functions in distributions!   
            # for factorial in posterior:
            for factorial, samples in zip(posterior, posterior_samples):
                entropy += factorial.entropy(samples)
                # print(entropy.size()) #returns [number samples, number latent layers]
                entropy_reduced=torch.sum(entropy,dim=1)
                # print(entropy_reduced) # number of samples times a float
                #TODO why is this only "samples" in DWave code? Looks like
                #they'd only take the last element of the posterior_samples list.
                cross_entropy+=self.prior.cross_entropy(samples)
            return cross_entropy - entropy_reduced

    def generate_samples(self, n_samples=100):
        logger.debug("ERROR generate_samples")
        """ It will randomly sample from the model using ancestral sampling. It first generates samples from p(z_0).
        Then, it generates samples from the hierarchical distributions p(z_j|z_{i < j}). Finally, it forms p(x | z_i).  
        
         Args:
             num_samples: an integer value representing the number of samples that will be generated by the model.
        """
        logger.debug("ERROR generate_samples")
        prior_samples = self.prior.get_samples(n_samples)
        # prior_samples = tf.slice(prior_samples, [0, 0], [num_samples, -1])
        
        output_samples = self.decoder.decode_posterior_sample(prior_samples)
        # output_activations[0] = output_activations[0] + self.train_bias
        # output_dist = FactorialBernoulliUtil(output_activations)
        # output_samples = tf.nn.sigmoid(output_dist.logit_mu)
        # print("--- ","end VAE::generate_samples()")
        return output_samples

    def hierarchical_posterior(self,x):
        logger.debug("hierarchical_posterior")
        #dummy
        x_tilde=self.encoder.encode(x)
        mu, logvar=self.prior.reparameterize(x_tilde)
        return mu, logvar                     

    def forward(self, x):
        logger.debug("forward")
        #TODO this should yield posterior distribution and samples
        #this now (200806) gives back "smoother" and samples from smoother. Not
        #hierarchical yet.
        posterior_distributions, posterior_samples = self.encoder.hierarchical_posterior(x.view(-1, 784))
        posterior_samples_concat=torch.cat(posterior_samples,1)
        
        #take samples z and reconstruct output with decoder
        output_activations = self.decoder.decode(posterior_samples_concat)
        #TODO add bias to output_activations
        
        print(output_activations)
        import sys
        sys.exit()
        x_prime = self.decoder.decode_posterior_sample(posterior_samples[0])
        return x_prime, posterior_distribution, posterior_samples

if __name__=="__main__":
    logger.debug("Testing Model Setup") 
    model=VAE()
    # model=DiVAE()
    logger.debug("Success")
    pass