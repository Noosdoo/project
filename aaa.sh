#!/bin/bash
#SBATCH -p defq
#SBATCH --gres=gpu:1g.10gb:1
#SBATCH -J FMNIST
#SBATCH -o log.%J
#SBATCH --time 00-01:00:00
docker run \
--gpus device=$(mig-list) \
--shm-size=32g \
--ulimit memlock=-1 \
--ulimit stack=67108864 \
--rm \
-v ~:/workspace/mounted \
nvcr.io/nvidia/tensorflow:23.03-tf2-py3 \
python /workspace/mounted/fmnist/fmnist.py