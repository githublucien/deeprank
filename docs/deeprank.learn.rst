Deep learning
=======================

.. automodule:: deeprank.learn

This module contains all the tools for deep learning in DeepRank. The two main modules are ``deeprank.learn.DataSet`` and ``deeprank.learn.NeuralNet``. The ``DataSet`` class allows to process several hdf5 files created by the ``deeprank.generate`` toolset for use by pyTorch. This is done by creating several ``torch.data_utils.DataLoader`` for the training, valiation and test of the model. Several options are possible to specify and filter which conformations should be used in the dataset. The ``NeuralNet`` class is in charge of the deep learning part.There as well several options are possible to specify the task to be performed, the architecture of the neural network etc ....

Example:

>>> from deeprank.learn import *
>>> from model3d import cnn
>>>
>>> database = '1ak4.hdf5'
>>>
>>> # declare the dataset instance
>>> data_set = DataSet(database,
>>>                    select_feature='all',
>>>                    select_target='IRMSD',
>>>                    dict_filter={'IRMSD':'<4. or >10.'})
>>>
>>>
>>> # create the network
>>> model = NeuralNet(data_set, cnn, model_type='3d', task='class')
>>>
>>> # start the training
>>> model.train(nepoch = 250,divide_trainset=0.8, train_batch_size = 50, num_workers=8)
>>>
>>> # save the model
>>> model.save_model()

The details of the submodules are presented here. The two main ones are ``deeprank.learn.DataSet`` and ``deeprank.learn.NeuralNet``.

:note: The module ``deeprank.learn.modelGenerator`` can automatically create the file defining the neural network architecture.

DataSet : Create a torch dataset
---------------------------------

.. automodule:: deeprank.learn.DataSet
    :members:
    :undoc-members:


NeuralNet : perform deep learning
----------------------------------

.. automodule:: deeprank.learn.NeuralNet
    :members:
    :undoc-members:

modelGenerator : automatically generate NN file
------------------------------------------------

.. automodule:: deeprank.learn.modelGenerator
    :members:
    :undoc-members:



