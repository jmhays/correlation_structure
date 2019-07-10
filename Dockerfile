FROM nvidia/cuda:10.1-devel-ubuntu18.04

ARG BRANCH=master

ENV PATH=$PATH:/usr/local/gromacs/bin
ENV SHELL=/bin/bash

RUN apt-get update && apt-get -y install libopenmpi-dev \
    libfftw3-dev \
    cmake \
    make \
    git \
    locales \
    python3-dev \
    python3-pip

RUN pip3 install setuptools networkx cmake mpi4py numpy scipy

RUN mkdir builds && cd builds/

RUN git clone https://github.com/gromacs/gromacs.git && \
    cd gromacs && git checkout release-2019 && \
    mkdir build && \
    cd build && \
    cmake ../ -DGMX_MPI=OFF -DGMX_GPU=ON -DGMXAPI=ON && \ 
    make -j8 && make install

RUN cd /builds/

RUN git clone https://github.com/kassonlab/gmxapi.git && \
    cd gmxapi && git checkout release-0_0_7 && \
    mkdir build && \
    cd build && \
    cmake ../ && \
    make -j8 && make install

RUN cd /builds/

RUN git clone https://github.com/jmhays/sample_restraint.git && \
    cd sample_restraint && git checkout corr-struct && \ 
    mkdir build && cd build && \
    cmake ../ && \
    make -j8 *&& make install

RUN cd /builds/

RUN git clone https://github.com/jmhays/run_brer.git && \
    cd run_brer/ && \
    git checkout ${BRANCH} && \
    python3 setup.py install