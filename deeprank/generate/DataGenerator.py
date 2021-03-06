
import os
import sys
import importlib
import numpy as np
import h5py
from collections import OrderedDict
import logging
from deeprank.tools import pdb2sql
from deeprank.generate import GridTools as gt

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(x):
        return x

try:
    from pycuda import driver, compiler, gpuarray, tools
    import pycuda.autoinit
except ImportError:
    pass

_printif = lambda string,cond: print(string) if cond else None

class DataGenerator(object):

    def __init__(self,pdb_select=None,pdb_source=None,pdb_native=None,
                 compute_targets = None, compute_features = None,
                 data_augmentation=None, hdf5='database.h5',logger=None,debug=True):
        """Generate the data (features/targets/maps) required for deeprank.

        Args:
            pdb_select (list(str), optional): List of individual conformation for mapping
            pdb_source (list(str), optional): List of folders where to find the pdbs for mapping
            pdb_native (list(str), optional): List of folders where to find the native comformations
            compute_targets (list(str), optional): List of python files computing the features
            compute_features (list(str), optional): List of python files computing the features
            data_augmentation (int, optional): Number of rotation performed one each complex
            hdf5 (str, optional): name of the hdf5 file where the data is saved
            logger (None, optional): logger file
            debug (bool, optional): print debuf info

        Raises:
            NotADirectoryError: if the source are not found

        Example :

        >>> from deeprank.generate import *
        >>> # sources to assemble the data base
        >>> pdb_source     = ['./1AK4/decoys/']
        >>> pdb_native     = ['./1AK4/native/']
        >>> h5file = '1ak4.hdf5'
        >>>
        >>> #init the data assembler
        >>> database = DataGenerator(pdb_source=pdb_source,pdb_native=pdb_native,data_augmentation=None,
        >>>                          compute_targets  = ['deeprank.targets.dockQ'],
        >>>                          compute_features = ['deeprank.features.AtomicFeature',
        >>>                                              'deeprank.features.NaivePSSM',
        >>>                                              'deeprank.features.PSSM_IC',
        >>>                                              'deeprank.features.BSA'],
        >>>                          hdf5=h5file)

        """
        self.pdb_select  = pdb_select
        self.pdb_source  = pdb_source or []
        self.pdb_native  = pdb_native or []

        self.data_augmentation = data_augmentation

        self.hdf5 = hdf5

        self.compute_targets  = compute_targets
        self.compute_features = compute_features

        self.all_pdb = []
        self.all_native = []
        self.pdb_path = []

        self.feature_error = []
        self.map_error = []

        self.logger = logger or logging.getLogger(__name__)
        self.debug = debug

        # check that a source was given
        if self.pdb_source is None:
            raise NotADirectoryError('You must provide one or several source directory where the pdbs are stored')

        # handle the sources
        if not isinstance(self.pdb_source,list):
            self.pdb_source = [self.pdb_source]

        # get all the conformation path
        for src in self.pdb_source:
            if os.path.isdir(src):
                self.all_pdb += [os.path.join(src,fname) for fname in os.listdir(src)]
            elif os.path.isfile(src):
                self.all_pdb.append(src)

        # handle the native
        if not isinstance(self.pdb_native,list):
            self.pdb_native = [self.pdb_native]

        for src in self.pdb_native:
            if os.path.isdir(src):
                self.all_native +=  [os.path.join(src,fname) for fname in os.listdir(src)]
            if os.path.isfile(src):
                self.all_native.append(src)

        # filter the cplx if required
        self.pdb_path = self.all_pdb
        if self.pdb_select is not None:
            self.pdb_path = list(filter(lambda x: self.pdb_select in x, self.all_pdb))

#====================================================================================
#
#       CREATE THE DATABASE ALL AT ONCE IF ALL OPTIONS ARE GIVEN
#
#====================================================================================

    def create_database(self,verbose=False,remove_error=True,prog_bar=False):

        '''Create the hdf5 file architecture and compute the features/targets.

        Args:
            verbose (bool, optional): Print creation details
            remove_error (bool, optional): remove the groups that errored
            prog_bar (bool, optional): use tqdm

        Raises:
            ValueError: If creation of the group errored.

        Example :

        >>> # sources to assemble the data base
        >>> pdb_source     = ['./1AK4/decoys/']
        >>> pdb_native     = ['./1AK4/native/']
        >>> h5file = '1ak4.hdf5'
        >>>
        >>> #init the data assembler
        >>> database = DataGenerator(pdb_source=pdb_source,pdb_native=pdb_native,data_augmentation=None,
        >>>                          compute_targets  = ['deeprank.targets.dockQ'],
        >>>                          compute_features = ['deeprank.features.AtomicFeature',
        >>>                                              'deeprank.features.NaivePSSM',
        >>>                                              'deeprank.features.PSSM_IC',
        >>>                                              'deeprank.features.BSA'],
        >>>                          hdf5=h5file)
        >>>
        >>> #create new files
        >>> database.create_database(prog_bar=True)
        >>> '''

        # open the file
        self.f5 = h5py.File(self.hdf5,'w')
        self.logger.info('Start Feature calculation')

        # get the local progress bar
        desc = '{:25s}'.format('Create database')
        cplx_tqdm = tqdm(self.pdb_path,desc=desc,disable = not prog_bar)

        if not prog_bar:
            print(desc, ':', self.hdf5)
            sys.stdout.flush()

        for cplx in cplx_tqdm:

            cplx_tqdm.set_postfix(mol=os.path.basename(cplx))
            self.logger.debug('MOLECULE %s' %(cplx))

            try:

                ################################################
                #   get the pdbs of the conformation and its ref
                #   for the original data (not augmetned one)
                ################################################

                # names of the molecule
                mol_aug_name_list = []
                mol_name = os.path.splitext(os.path.basename(cplx))[0]

                # get the bare name of the molecule
                # and define the name of the native
                # i.e. 1AK4_100w -> 1AK4
                bare_mol_name = mol_name.split('_')[0]
                ref_name = bare_mol_name + '.pdb'

                # check if we have a decoy or native
                # and find the reference
                if mol_name == bare_mol_name:
                    ref = cplx
                else:

                    if len(self.all_native)>0:

                        ref = list(filter(lambda x: ref_name in x,self.all_native))

                        if len(ref)>1:
                            raise ValueError('Multiple native nout found')
                        if len(ref) == 0:
                            raise ValueError('Native not found')
                        else:
                            ref = ref[0]

                        if ref == '':
                            ref = None

                    else:
                        ref = None

                # talk a bit
                if verbose:
                    print('\n: Process complex %s' %(mol_name))

                # crete a subgroup for the molecule
                molgrp = self.f5.require_group(mol_name)
                molgrp.attrs['type'] = 'molecule'

                # add the ref and the complex
                self._add_pdb(molgrp,cplx,'complex')
                if ref is not None:
                    self._add_pdb(molgrp,ref,'native')

                ################################################
                #   add the features
                ################################################

                # add the features
                molgrp.require_group('features')
                molgrp.require_group('features_raw')

                if self.compute_features is not None:
                    self._compute_features(self.compute_features, molgrp['complex'].value,molgrp['features'],molgrp['features_raw'] )

                ################################################
                #   add the targets
                ################################################

                # add the features
                molgrp.require_group('targets')
                if self.compute_targets is not None:
                    self._compute_targets(self.compute_targets, molgrp['complex'].value,molgrp['targets'])

                ################################################
                #   DATA AUGMENTATION
                ################################################

                # GET ALL THE NAMES
                if self.data_augmentation is not None:
                    mol_aug_name_list = [mol_name + '_r%03d' %(idir+1) for idir in range(self.data_augmentation)]
                else:
                    mol_aug_name_list = []

                # loop over the complexes
                for icplx, mol_aug_name in enumerate(mol_aug_name_list):

                    ################################################
                    #   get the pdbs of the conformation and its ref
                    ################################################

                    # crete a subgroup for the molecule
                    molgrp = self.f5.require_group(mol_aug_name)
                    molgrp.attrs['type'] = 'molecule'

                    # copy the ref into it
                    if ref is not None:
                        self._add_pdb(molgrp,ref,'native')

                    # get the rotation axis and angle
                    axis,angle = self._get_aug_rot()

                    # create the new pdb
                    center = self._add_aug_pdb(molgrp,cplx,'complex',axis,angle)

                    # copy the targets/features
                    self.f5.copy(mol_name+'/targets/', molgrp)
                    self.f5.copy(mol_name+'/features/', molgrp)

                    # rotate the feature
                    self._rotate_feature(molgrp,axis,angle,center)

                    # store the axis/angl/center as attriutes
                    # in case we need them later
                    molgrp.attrs['axis'] = axis
                    molgrp.attrs['angle'] = angle
                    molgrp.attrs['center'] = center

            except Exception as inst:

                self.feature_error += [mol_name] + mol_aug_name_list
                self.logger.warning('Error during the feature calculation of %s' %cplx,exc_info=True)
                _printif('Error during the feature calculation of %s' %cplx,self.debug)
                _printif(type(inst),self.debug)
                _printif(inst.args,self.debug)

        # remove the data where we had issues
        if remove_error:
            for mol in self.feature_error:
                self.logger.warning('Error during the feature calculation of %s' %cplx,exc_info=True)
                _printif('removing %s from %s' %(mol,self.hdf5),self.debug)
                del self.f5[mol]

        # close the file
        self.f5.close()


#====================================================================================
#
#       ADD FEATURES TO AN EXISTING DATASET
#
#====================================================================================


    def add_feature(self,prog_bar=True):

        ''' Add a feature to an existing hdf5 file

        Args:
            prog_bar (bool, optional): use tqdm

        Example:

        >>> h5file = '1ak4.hdf5'
        >>>
        >>> #init the data assembler
        >>> database = DataGenerator(compute_features  = ['deeprank.features.ResidueDensity'],
        >>>                          hdf5=h5file)
        >>>
        >>> database.add_feature(prog_bar=True)
        '''

        # check if file exists
        if not os.path.isfile(self.hdf5):
            raise FileNotFoundError('File %s does not exists' %self.hdf5)

        # get the folder names
        f5 = h5py.File(self.hdf5,'a')
        fnames = f5.keys()

        # get the non rotated ones
        fnames_original = list( filter(lambda x: '_r' not in x, fnames) )
        fnames_augmented = list( filter(lambda x: '_r' in x, fnames) )

        # computes the features of the original
        desc = '{:25s}'.format('Add features')
        for cplx_name in tqdm(fnames_original,desc=desc,ncols=100,disable = not prog_bar):

            # molgrp
            molgrp = f5[cplx_name]

            # the internal features
            molgrp.require_group('features')
            molgrp.require_group('features_raw')

            if self.compute_features is not None:
                self._compute_features(self.compute_features, molgrp['complex'].value,molgrp['features'],molgrp['features_raw'] )


        # copy the data from the original to the augmented
        for cplx_name in fnames_augmented:

            # group of the molecule
            aug_molgrp = f5[cplx_name]

            # get the source group
            mol_name = molgrp.name.split('_r')[0]
            src_molgrp = f5[mol_name]

            # get the rotation parameters
            axis = aug_molgrp.attrs['axis']
            angle = aug_molgrp.attrs['angle']
            center = aug_molgrp.attrs['center']

            # copy the features to the augmented
            for k in molgrp['features']:
                if k not in aug_molgrp['features']:

                    #copy
                    data = src_molgrp['features/'+k].value
                    aug_molgrp.require_group('features')
                    aug_molgrp.create_dataset("features/"+k,data=data)

                    #rotate
                    self._rotate_feature(aug_molgrp,axis,angle,center,feat_name=[k])


        # close the file
        f5.close()

#====================================================================================
#
#       ADD TARGETS TO AN EXISTING DATASET
#
#====================================================================================


    def add_unique_target(self,targdict):
        '''Add identical targets for all the complexes in the datafile.

        This is usefull if you want to add the binary class of all the complexes
        created from decoys or natives

        Args:
            targdict (dict): Example : {'DOCKQ':1.0}

        >>> database = DataGenerator(hdf5='1ak4.hdf5')
        >>> database.add_unique_target({'DOCKQ':1.0})
        '''

        # check if file exists
        if not os.path.isfile(self.hdf5):
            raise FileNotFoundError('File %s does not exists' %self.hdf5)

        f5 = h5py.File(self.hdf5,'a')
        for mol in list(f5.keys()):
            targrp = f5[mol].require_group('targets')
            for name,value in targdict.items():
                targrp.create_dataset(name,data=np.array([value]))
        f5.close()


    def add_target(self,prog_bar=False):

        ''' Add a target to an existing hdf5 file

        Args:
            prog_bar (bool, optional): Use tqdm

        Example :

        >>> h5file = '1ak4.hdf5'
        >>>
        >>> #init the data assembler
        >>> database = DataGenerator(compute_targets =['deeprank.targets.binary_class'],
        >>>                          hdf5=h5file)
        >>>
        >>> database.add_target(prog_bar=True)
        '''

        # check if file exists
        if not os.path.isfile(self.hdf5):
            raise FileNotFoundError('File %s does not exists' %self.hdf5)

        # name of the hdf5 file
        f5 = h5py.File(self.hdf5,'a')

        # get the folder names
        fnames = f5.keys()

        # get the non rotated ones
        fnames_original = list( filter(lambda x: '_r' not in x, fnames) )
        fnames_augmented = list( filter(lambda x: '_r' in x, fnames) )

        # compute the targets  of the original
        desc = '{:25s}'.format('Add targets')

        for cplx_name in tqdm(fnames_original,desc=desc,ncols=100,disable = not prog_bar):

            # group of the molecule
            molgrp = f5[cplx_name]

            # add the targets
            if self.compute_targets is not None:
                self._compute_targets(self.compute_targets, molgrp['complex'].value,molgrp['targets'])

        # copy the targets of the original to the rotated
        for cplx_name in fnames_augmented:

            # group of the molecule
            aug_molgrp = f5[cplx_name]

            # get the source group
            mol_name = molgrp.name.split('_r')[0]
            src_molgrp = f5[mol_name]

            # copy the targets to the augmented
            for k in molgrp['targets']:
                if k not in aug_molgrp['targets']:
                    data = src_molgrp['targets/'+k].value
                    aug_molgrp.require_group('targets')
                    aug_molgrp.create_dataset("targets/"+k,data=data)



        # close the file
        f5.close()


#====================================================================================
#
#       MAP THE FEATURES TO THE GRID
#
#====================================================================================


    def map_features(self,grid_info={},
                     cuda=False,gpu_block=None,
                     cuda_kernel='/kernel_map.c',
                     cuda_func_name = 'gaussian',
                     try_sparse=True,
                     reset=False,use_tmpdir=False,
                     time=False,
                     prog_bar=True,grid_prog_bar=False,
                     remove_error=True):

        ''' Map the feature on a grid of points centered at the interface

        Args:
            grid_info (dict): Informaton for the grid see deeprank.generate.GridTool.py for details
            cuda (bool, optional): Use CUDA
            gpu_block (None, optional): GPU block size to be used
            cuda_kernel (str, optional): filename containing CUDA kernel
            cuda_func_name (str, optional): The name of the function in the kernel
            try_sparse (bool, optional): Try to save the grids as sparse format
            reset (bool, optional): remove grids if some are already present
            use_tmpdir (bool, optional): use a scratch directory
            time (bool, optional): time the mapping process
            prog_bar (bool, optional): use tqdm for each molecule
            grid_prog_bar (bool, optional): use tqdm for each grid
            remove_error (bool, optional): remove the data that errored

        Example :

        >>> #init the data assembler
        >>> database = DataGenerator(hdf5='1ak4.hdf5')
        >>>
        >>> # map the features
        >>> grid_info = {
        >>>     'number_of_points' : [30,30,30],
        >>>     'resolution' : [1.,1.,1.],
        >>>     'atomic_densities' : {'CA':3.5,'N':3.5,'O':3.5,'C':3.5},
        >>> }
        >>>
        >>> database.map_features(grid_info,try_sparse=True,time=False,prog_bar=True)

        '''

        # default CUDA
        cuda_func = None
        cuda_atomic = None

        # name of the hdf5 file
        f5 = h5py.File(self.hdf5,'a')

        # check all the input PDB files
        mol_names = f5.keys()

        if len(mol_names) == 0:
            _printif('No molecules found in %s' %self.hdf5,self.debug)
            f5.close()
            return

        # fills in the grid data if not provided : default = NONE
        grinfo = ['number_of_points','resolution']
        for gr in grinfo:
            if gr not in grid_info:
                grid_info[gr] = None

        # Dtermine which feature to map
        if 'feature' not in grid_info:

            # get the mol group
            mol = list(f5.keys())[0]

            # if we havent mapped anything yet or if we reset
            if 'mapped_features' not in list(f5[mol].keys()) or reset:
                grid_info['feature'] = list(f5[mol+'/features'].keys())

            # if we have already mapped stuff
            elif 'mapped_features' in list(f5[mol].keys()):

                # feature name
                all_feat = list(f5[mol+'/features'].keys())

                # feature already mapped
                mapped_feat = list(f5[mol+'/mapped_features/Feature_ind'].keys())

                # we select only the feture that were not mapped yet
                grid_info['feature'] = []
                for feat_name in all_feat:
                    if not any(map(lambda x: x.startswith(feat_name+'_'), mapped_feat)):
                        grid_info['feature'].append(feat_name)

        # by default we do not map atomic densities
        if 'atomic_densities' not in grid_info:
            grid_info['atomic_densities'] = None

        # fills in the features mode if somes are missing : default = IND
        modes = ['atomic_densities_mode','feature_mode']
        for m in modes:
            if m not in grid_info:
                grid_info[m] = 'ind'

        # sanity check for cuda
        if cuda and gpu_block is None: # pragma: no cover
            print('Warning GPU block automatically set to 8 x 8 x 8')
            print('You can sepcify the block size with gpu_block=[n,m,k]')
            gpu_block = [8,8,8]

        # initialize cuda
        if cuda: # pragma: no cover

            # compile cuda module
            npts = grid_info['number_of_points']
            res = grid_info['resolution']
            module = self.compile_cuda_kernel(cuda_kernel,npts,res)

            # get the cuda function for the atomic/residue feature
            cuda_func = self.get_cuda_function(module,cuda_func_name)

            # get the cuda function for the atomic densties
            cuda_atomic_name = 'atomic_densities'
            cuda_atomic = self.get_cuda_function(module,cuda_atomic_name)

        # get the local progress bar
        desc = '{:25s}'.format('Map Features')
        mol_tqdm = tqdm(mol_names,desc=desc,disable = not prog_bar)

        if not prog_bar:
            print(desc, ':', self.hdf5)
            sys.stdout.flush()

        # loop over the data files
        for mol in mol_tqdm:

            mol_tqdm.set_postfix(mol=mol)

            try:

                # compute the data we want on the grid
                grid = gt.GridTools(molgrp=f5[mol],
                                 number_of_points = grid_info['number_of_points'],
                                 resolution = grid_info['resolution'],
                                 atomic_densities = grid_info['atomic_densities'],
                                 atomic_densities_mode = grid_info['atomic_densities_mode'],
                                 feature = grid_info['feature'],
                                 feature_mode = grid_info['feature_mode'],
                                 cuda = cuda,
                                 gpu_block = gpu_block,
                                 cuda_func = cuda_func,
                                 cuda_atomic = cuda_atomic,
                                 hdf5_file = f5,
                                 time=time,
                                 prog_bar=grid_prog_bar,
                                 try_sparse=try_sparse)

            except:

                self.map_error.append(mol)
                self.logger.warning('Error during the mapping of %s' %mol,exc_info=True)
                _printif('Error during the mapping of %s' %mol,self.debug)

        # remove the molecule with issues
        if remove_error:
            for mol in self.map_error:
                print('removing %s from %s' %(mol,self.hdf5))
                del f5[mol]

        # close he hdf5 file
        f5.close()


#====================================================================================
#
#       REMOVE DATA FROM THE DATA SET
#
#====================================================================================

    def remove(self,feature=True,pdb=True,points=True,grid=False):

        '''Remove data from the data set.

        Equivalent to the cleandata command line tool. Once the data has been
        removed from the file it is impossible to add new features/targets

        Args:
            feature (bool, optional): Remove the features
            pdb (bool, optional): Remove the pdbs
            points (bool, optional): remove teh grid points
            grid (bool, optional): remove the maps

        '''

        _printif('Remove features',self.debug)

        # name of the hdf5 file
        f5 = h5py.File(self.hdf5,'a')

        # get the folder names
        mol_names = f5.keys()

        for name in mol_names:

            mol_grp = f5[name]

            if feature and 'features' in mol_grp:
                del mol_grp['features']
            if pdb and 'complex' in mol_grp and 'native' in mol_grp:
                del mol_grp['complex']
                del mol_grp['native']
            if points and 'grid_points' in mol_grp:
                del mol_grp['grid_points']
            if grid and 'mapped_features' in mol_grp:
                del mol_grp['mapped_features']

        f5.close()

        # reclaim the space
        os.system('h5repack %s _tmp.h5py' %self.hdf5)
        os.system('mv _tmp.h5py %s' %self.hdf5)





#====================================================================================
#
#       Simply tune or test the kernel
#
#====================================================================================

    def _tune_cuda_kernel(self,grid_info,cuda_kernel='kernel_map.c',func='gaussian'): # pragma: no cover

        '''
        Tune the CUDA kernel using the kernel tuner
        http://benvanwerkhoven.github.io/kernel_tuner/

        Args:
            grid_info (dict): information for the grid definition
            cuda_kernel (str, optional): file containing the kernel
            func (str, optional): function in the kernel to be used

        Raises:
            ValueError: If the tuner has not been used
        '''


        try:
            from kernel_tuner import tune_kernel
        except:
            print('Install the Kernel Tuner : \n \t\t pip install kernel_tuner')
            print('http://benvanwerkhoven.github.io/kernel_tuner/')

        # fills in the grid data if not provided : default = NONE
        grinfo = ['number_of_points','resolution']
        for gr  in grinfo:
            if gr not in grid_info:
                raise ValueError('%s must be specified to tune the kernel')

        # define the grid
        center_contact = np.zeros(3)
        nx,ny,nz = grid_info['number_of_points']
        dx,dy,dz = grid_info['resolution']
        lx,ly,lz = nx*dx,ny*dy,nz*dz

        x = np.linspace(0,lx,nx)
        y = np.linspace(0,ly,ny)
        z = np.linspace(0,lz,nz)

        # create the dictionary containing the tune parameters
        tune_params = OrderedDict()
        tune_params['block_size_x'] = [2,4,8,16,32]
        tune_params['block_size_y'] = [2,4,8,16,32]
        tune_params['block_size_z'] = [2,4,8,16,32]

        # define the final grid
        grid = np.zeros(grid_info['number_of_points'])

        # arguments of the CUDA function
        x0,y0,z0 = np.float32(0),np.float32(0),np.float32(0)
        alpha = np.float32(0)
        args = [alpha,x0,y0,z0,x,y,z,grid]

        # dimensionality
        problem_size = grid_info['number_of_points']

        # get the kernel
        kernel = os.path.dirname(os.path.abspath(__file__)) + '/' + cuda_kernel
        kernel_code_template = open(kernel, 'r').read()

        npts = grid_info['number_of_points']
        res = grid_info['resolution']
        kernel_code = kernel_code_template % {'nx' : npts[0], 'ny': npts[1], 'nz' : npts[2], 'RES' : np.max(res)}
        tunable_kernel = self._tunable_kernel(kernel_code)

        # tune
        result = tune_kernel(func, tunable_kernel,problem_size,args,tune_params)


#====================================================================================
#
#       Simply test the kernel
#
#====================================================================================

    def _test_cuda(self,grid_info,gpu_block=8,cuda_kernel='kernel_map.c',func='gaussian'): # pragma: no cover

        '''
        Test the CUDA kernel

        Args:
            grid_info (dict): Information for the grid definition
            gpu_block (int, optional): GPU block size to be used
            cuda_kernel (str, optional): File containing the kernel
            func (str, optional): function in the kernel to be used

        Raises:
            ValueError: If the kernel has not been installed
        '''

        from time import time

        # fills in the grid data if not provided : default = NONE
        grinfo = ['number_of_points','resolution']
        for gr  in grinfo:
            if gr not in grid_info:
                raise ValueError('%s must be specified to tune the kernel')

        # get the cuda function
        npts = grid_info['number_of_points']
        res = grid_info['resolution']
        module = self._compile_cuda_kernel(cuda_kernel,npts,res)
        cuda_func = self._get_cuda_function(module,func)

        # define the grid
        center_contact = np.zeros(3)
        nx,ny,nz = grid_info['number_of_points']
        dx,dy,dz = grid_info['resolution']
        lx,ly,lz = nx*dx,ny*dy,nz*dz

        # create the coordinate
        x = np.linspace(0,lx,nx)
        y = np.linspace(0,ly,ny)
        z = np.linspace(0,lz,nz)

        # book memp on the gpu
        x_gpu = gpuarray.to_gpu(x.astype(np.float32))
        y_gpu = gpuarray.to_gpu(y.astype(np.float32))
        z_gpu = gpuarray.to_gpu(z.astype(np.float32))
        grid_gpu = gpuarray.zeros(grid_info['number_of_points'],np.float32)

        #  make sure we have three block value
        if not isinstance(gpu_block,list):
            gpu_block = [gpu_block]*3

        #  get the grid
        gpu_grid = [ int(np.ceil(n/b)) for b,n in zip(gpu_block,grid_info['number_of_points'])]
        print('GPU BLOCK :', gpu_block)
        print('GPU GRID  :', gpu_grid)

        xyz_center = np.random.rand(500,3).astype(np.float32)
        alpha = np.float32(1)
        t0 = time()
        for xyz in xyz_center:
            x0,y0,z0 = xyz
            cuda_func(alpha,x0,y0,z0,x_gpu,y_gpu,z_gpu,grid_gpu,
                    block=tuple(gpu_block),grid=tuple(gpu_grid))

        print('Done in : %f ms' %((time()-t0)*1000))

#====================================================================================
#
#       Routines needed to handle CUDA
#
#====================================================================================

    @staticmethod
    def _compile_cuda_kernel(cuda_kernel,npts,res): # pragma: no cover
        """Compile the cuda kernel

        Args:
            cuda_kernel (str): filename
            npts (tuple(int)): number of grid points in each direction
            res (tuple(float)): resolution in each direction

        Returns:
            compiler.SourceModule: compiled kernel
        """
        # get the cuda kernel path
        kernel = os.path.dirname(os.path.abspath(__file__)) + '/' + cuda_kernel
        kernel_code_template = open(kernel, 'r').read()
        kernel_code = kernel_code_template % {'nx' : npts[0], 'ny': npts[1], 'nz' : npts[2], 'RES' : np.max(res)}

        # compile the kernel
        mod = compiler.SourceModule(kernel_code)
        return mod

    @staticmethod
    def _get_cuda_function(module,func_name):  # pragma: no cover
        """Get a single function from the compiled kernel

        Args:
            module (compiler.SourceModule): compiled kernel module
            func_name (str): Name of the funtion

        Returns:
            func: cuda function
        """
        cuda_func = module.get_function(func_name)
        return cuda_func

    # tranform the kernel to a tunable one
    @staticmethod
    def _tunable_kernel(kernel): # pragma: no cover
        """Make a tunale kernel

        Args:
            kernel (str): String of the kernel

        Returns:
            TYPE: tunable kernel
        """
        switch_name = { 'blockDim.x' : 'block_size_x', 'blockDim.y' : 'block_size_y','blockDim.z' : 'block_size_z' }
        for old,new in switch_name.items():
            kernel = kernel.replace(old,new)
        return kernel


#====================================================================================
#
#       FILTER DATASET
#
#===================================================================================

    def _filter_cplx(self):
        """Filter the name of the complexes."""

        # read the class ID
        f = open(self.pdb_select)
        pdb_name = f.readlines()
        f.close()
        pdb_name = [name.split()[0]+'.pdb' for name in pdb_name]

        # create the filters
        tmp_path = []
        for name in pdb_name:
            tmp_path += list(filter(lambda x: name in x,self.pdb_path))

        # update the pdb_path
        self.pdb_path = tmp_path



#====================================================================================
#
#       FEATURES ROUTINES
#
#====================================================================================

    @staticmethod
    def _compute_features(feat_list,pdb_data,featgrp,featgrp_raw):
        """Compute the features

        Args:
            feat_list (list(str)): list of function name
            pdb_data (bytes): PDB translated in btes
            featgrp (str): name of the group where to store the xyz feature
            featgrp_raw (str): name of the group where to store the raw feature
        """
        for feat in feat_list:
            feat_module = importlib.import_module(feat,package=None)
            feat_module.__compute_feature__(pdb_data,featgrp,featgrp_raw)


#====================================================================================
#
#       TARGETS ROUTINES
#
#====================================================================================


    @staticmethod
    def _compute_targets(targ_list,pdb_data,targrp):
        """Compute the targets

        Args:
            targ_list (list(str)): list of function name
            pdb_data (bytes): PDB translated in btes
            targrp (str): name of the group where to store the targets
        """
        for targ in targ_list:
            targ_module = importlib.import_module(targ,package=None)
            targ_module.__compute_target__(pdb_data,targrp)


#====================================================================================
#
#       ADD PDB FILE
#
#====================================================================================
    @staticmethod
    def _add_pdb(molgrp,pdbfile,name):
        """ Add a pdb to a molgrp.

        Args:
            molgrp (str): mopl group where tp add the pdb
            pdbfile (str): psb file to add
            name (str): dataset name in the hdf5 molgroup
        """
        # read the pdb and extract the ATOM lines
        with open(pdbfile,'r') as fi:
            data = [line.split('\n')[0] for line in fi if line.startswith('ATOM')]
        data = np.array(data).astype('|S73')
        dataset = molgrp.create_dataset(name,data=data)


#====================================================================================
#
#       AUGMENTED DATA
#
#====================================================================================

    # add a rotated pdb structure to the database
    @staticmethod
    def _add_aug_pdb(molgrp,pdbfile,name,axis,angle):
        """Add augmented pdbs to the dataset

        Args:
            molgrp (str): name of the molgroup
            pdbfile (str): pdb file name
            name (str): name of the dataset
            axis (list(float)): axis of rotation
            angle (folat): angle of rotation

        Returns:
            list(float): center of the molecule
        """
        # create tthe sqldb and extract positions
        sqldb = pdb2sql(pdbfile)

        # rotate the positions
        center = sqldb.rotation_around_axis(axis,angle)

        # get the data
        sqldata = sqldb.get('*')

        # close the db
        sqldb.close()

        # export the data to h5
        data = []
        for d in sqldata:
            line = 'ATOM  '
            line += '{:>5}'.format(d[0])    # serial
            line += ' '
            line += '{:^4}'.format(d[1])    # name
            line += '{:>1}'.format(d[2])    # altLoc
            line += '{:>3}'.format(d[3])    #resname
            line += ' '
            line += '{:>1}'.format(d[4])    # chainID
            line += '{:>4}'.format(d[5])    # resSeq
            line += '{:>1}'.format(d[6])    # iCODE
            line += '   '
            line += '{: 8.3f}'.format(d[7]) #x
            line += '{: 8.3f}'.format(d[8]) #y
            line += '{: 8.3f}'.format(d[9]) #z
            line += '{: 6.2f}'.format(d[10])    # occ
            line += '{: 6.2f}'.format(d[11])    # temp
            data.append(line)

        data = np.array(data).astype('|S73')
        dataset = molgrp.create_dataset(name,data=data)

        return center

    # rotate th xyz-formatted feature in the database
    @staticmethod
    def _rotate_feature(molgrp,axis,angle,center,feat_name='all'):
        """Rotate the raw feature values

        Args:
            molgrp (str): name pf the molgrp
            axis (list(float)): axis of rotation
            angle (float): angle of rotation
            center (list(float)): center of rotation
            feat_name (str) : name of the feature to rotate or 'all'
        """
        if feat_name == 'all':
            feat = list(molgrp['features'].keys())
        else:
            feat = feat_name
            if not isinstance(feat,list):
                feat = list(feat)

        for fn in feat:

            # extract the data
            data = molgrp['features/'+fn].value

            # xyz
            xyz = data[:,1:4]

            # get the data
            ct,st = np.cos(angle),np.sin(angle)
            ux,uy,uz = axis

            # definition of the rotation matrix
            # see https://en.wikipedia.org/wiki/Rotation_matrix
            rot_mat = np.array([
            [ct + ux**2*(1-ct),         ux*uy*(1-ct) - uz*st,       ux*uz*(1-ct) + uy*st],
            [uy*ux*(1-ct) + uz*st,      ct + uy**2*(1-ct),          uy*uz*(1-ct) - ux*st],
            [uz*ux*(1-ct) - uy*st,      uz*uy*(1-ct) + ux*st,       ct + uz**2*(1-ct)   ]])

            # apply the rotation
            xyz = np.dot(rot_mat,(xyz-center).T).T + center

            # put back the data
            data[:,1:4] = xyz

    # get rotation axis and angle
    @staticmethod
    def _get_aug_rot():
        """Get the rotation angle/axis

        Returns:
            list(float): axis of rotation
            float: angle of rotation
        """
        # define the axis
        # uniform distribution on a sphere
        # http://mathworld.wolfram.com/SpherePointPicking.html
        u1,u2 = np.random.rand(),np.random.rand()
        teta,phi = np.arccos(2*u1-1),2*np.pi*u2
        axis = [np.sin(teta)*np.cos(phi),np.sin(teta)*np.sin(phi),np.cos(teta)]

        # and the rotation angle
        angle = -np.pi + np.pi*np.random.rand()

        return axis,angle