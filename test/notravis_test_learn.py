import os,sys

import torch.optim as optim
import torch
from torch.autograd import Variable
import torch.nn as nn
import torch.nn.functional as F
import torch.utils.data as data_utils

from deeprank.learn import *

###################################
# define the CNN
class ConvNet3D(nn.Module):

  def __init__(self,input_shape):
    super(ConvNet3D,self).__init__()

    self.conv1 = nn.Conv3d(input_shape[0],4,kernel_size=2)
    self.pool  = nn.MaxPool3d((2,2,2))
    self.conv2 = nn.Conv3d(4,5,kernel_size=2)
    
    size = self._get_conv_output(input_shape)

    self.fc1   = nn.Linear(size,84)
    self.fc2   = nn.Linear(84,1)

    self.sm = nn.Softmax()

  def _get_conv_output(self,shape):
    inp = Variable(torch.rand(1,*shape))
    out = self._forward_features(inp)
    return out.data.view(1,-1).size(1)

  def _forward_features(self,x):
    x = self.pool(F.relu(self.conv1(x)))
    x = self.pool(F.relu(self.conv2(x)))
    return x

  def forward(self,x):
    
    x = self._forward_features(x)
    x = x.view(x.size(0),-1)
    x = F.relu(self.fc1(x))
    x = self.fc2(x)
    return x

##################################


# all the import torch fails on TRAVIS
# so we can only exectute this test locally
def test_learn():

  #adress of the database
  database = '1ak4.hdf5'

  if not os.path.isfile(database):
    raise FileNotFoundError('Database %s not found. Make sure to run test_generate before')

  # declare the dataset instance
  data_set = DataSet(database,test_database = database,
                            select_feature = 'all',select_target='DOCKQ',tqdm=True,
                            normalize_features = True, normalize_targets=True)

  
  # create the network
  model = NeuralNet(data_set,ConvNet3D,model_type='3d',task='reg',
                    cuda=False,plot=True,outdir='./out/')

  # start the training
  model.train(nepoch = 50,divide_set=[0.8,0.1], train_batch_size = 5,num_workers=5)

  # save the model
  model.save_model()

  # reload the model and test it
  # declare the dataset instance
  #data_set = InMemoryDataSet(database,test_database = database,
  #                          select_feature = 'all',select_target='DOCKQ',tqdm=True,
  #                          normalize_features = False, normalize_targets=False)

  #model = NeuralNet(data_set,ConvNet3D,outdir='./out_reload/')
  #model.load_model('./out/model.pth.tar')
  #model.data_set.normalize_data()
  #model.test()

if __name__ == "__main__":
  test_learn()
