from distutils.core import setup
#from setuptools import setup

setup(
    name='deeprank',
    description='Rank Protein-Protein Interactions using Deep Learning',
    version='0.1-dev',
    url='https://github.com/DeepRank',
    package_dir = {
    'deeprank' : './',
    'deeprank.assemble' : './assemble',
    'deeprank.map'      : './map',
    'deeprank.learn'    : './learn',
    'deeprank.tools'    : './tools'
    },
    
    packages=['deeprank',
              'deeprank.assemble',
              'deeprank.map',
              'deeprank.learn',
              'deeprank.tools']
)

# setup(
#     name = "deeprank",
#     version = "0.0.1",
#     author = "Nicolas Renaud, Lars Ridder, Li Xue",
#     author_email = "n.renaud@esciencecenter.nl",
#     description = ("Rank Protein-Protein Interactions using Deep Learning"),
#     license = "BSD",
#     keywords = "deeplearning, protein docking",
#     url = "https://github.com/DeepRank",
#     packages=['assemble', 'map','learn','tools'],
#     classifiers=[
#         "Development Status :: 3 - Alpha",
#         "Topic :: Utilities",
#         "License :: OSI Approved :: BSD License",
#     ],
# )