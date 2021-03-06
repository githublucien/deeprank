import os
import numpy as np

from time import time

from deeprank.tools import pdb2sql
from deeprank.features import FeatureClass

printif = lambda string,cond: print(string) if cond else None


#####################################################################################
#
#   Definition of the class
#
#####################################################################################

class PSSM_IC(FeatureClass):

    def __init__(self,mol_name=None,pdbfile=None,pssmic_path=None,debug=False):
        """Compute the information content of the PSSM.

        Args:
            mol_name (str): name of the molecule
            pdbfile (str): name of the dbfile
            pssmic_path (str): path to the pssm data
            debug (bool, optional): print debug info

        Example :

        >>> path = '/home/nico/Documents/projects/deeprank/data/HADDOCK/BM4_dimers/PSSM_IC/'
        >>> pssmic = PSSM_IC(mol_name = '1AK4', pdbfile='1AK4.pdb',pssmic_path=path)
        >>>
        >>> # get the pssm smoothed sum score
        >>> pssmic.read_PSSMIC_data()
        >>> pssmic.get_feature_value()
        """
        super().__init__("Residue")

        self.mol_name = mol_name
        self.pdbfile = pdbfile
        self.pssmic_path = pssmic_path
        self.molname = self.get_mol_name(mol_name)
        self.debug = debug

    @staticmethod
    def get_mol_name(mol_name):
        """Get bare mol name."""
        return mol_name.split('_')[0]

    def read_PSSMIC_data(self):
        """ Read the PSSM data."""

        names = os.listdir(self.pssmic_path)
        fname = [n for n in names if n.find(self.molname)==0]

        if len(fname)>1:
            raise ValueError('Multiple PSSM files found for %s in %s',self.pdbname,self.pssmic_path)
        if len(fname)==0:
            raise FileNotFoundError('No PSSM file found for %s in %s',self.pdbname,self.pssmic_path)
        else:
            fname = fname[0]

        f = open(self.pssmic_path + '/' + fname,'rb')
        data = f.readlines()
        f.close()
        raw_data = list( map(lambda x: x.decode('utf-8').split(),data))

        self.res_data  = np.array(raw_data)[:,:3]
        self.res_data = [  (r[0],int(r[1]),r[2]) for r in self.res_data ]
        self.pssmic_data = np.array(raw_data)[:,-1].astype(np.float)

    def get_feature_value(self,contact_only=True):
        """Compute the feature value."""

        sql = pdb2sql(self.pdbfile)
        xyz_info = sql.get('chainID,resSeq,resName',name='CB')
        xyz = sql.get('x,y,z',name='CB')

        xyz_dict = {}
        for pos,info in zip(xyz,xyz_info):
            xyz_dict[tuple(info)] = pos

        contact_residue = sql.get_contact_residue()
        contact_residue = contact_residue[0] + contact_residue[1]
        sql.close()

        pssm_data_xyz = {}
        pssm_data = {}
        for res,data in zip(self.res_data,self.pssmic_data):

            if contact_only and res not in contact_residue:
                continue

            if tuple(res) in xyz_dict:
                chain = {'A':0,'B':1}[res[0]]
                key = tuple([chain] + xyz_dict[tuple(res)])
                pssm_data[res] = [data]
                pssm_data_xyz[key] = [data]
            else:
                printif([tuple(res), ' not found in the pdbfile'],self.debug)

        # if we have no contact atoms
        if len(pssm_data_xyz) == 0:
            pssm_data_xyz[tuple([0,0.,0.,0.])] = [0.0]
            pssm_data_xyz[tuple([1,0.,0.,0.])] = [0.0]

        self.feature_data['pssm_ic'] = pssm_data
        self.feature_data_xyz['pssm_ic'] = pssm_data_xyz



#####################################################################################
#
#   THE MAIN FUNCTION CALLED IN THE INTERNAL FEATURE CALCULATOR
#
#####################################################################################

def __compute_feature__(pdb_data,featgrp,featgrp_raw):

    path = os.path.dirname(os.path.realpath(__file__))
    path = path + '/PSSM_IC/'

    mol_name = os.path.split(featgrp.name)[0]
    mol_name = mol_name.lstrip('/')

    pssmic = PSSM_IC(mol_name,pdb_data,path)

    # read the raw data
    pssmic.read_PSSMIC_data()

    # get the feature vales
    pssmic.get_feature_value()

    # export in the hdf5 file
    pssmic.export_dataxyz_hdf5(featgrp)
    pssmic.export_data_hdf5(featgrp_raw)


#####################################################################################
#
#   IF WE JUST TEST THE CLASS
#
#####################################################################################


if __name__ == '__main__':

    t0 = time()
    path = '/home/nico/Documents/projects/deeprank/data/HADDOCK/BM4_dimers/PSSM_IC/'
    pssmic = PSSM_IC(mol_name = '1AK4', pdbfile='1AK4.pdb',pssmic_path=path)

    # get the pssm smoothed sum score
    pssmic.read_PSSMIC_data()
    pssmic.get_feature_value()
    print(pssmic.feature_data_xyz)
    print(' Time %f ms' %((time()-t0)*1000))