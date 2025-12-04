#!/bin/bash


CUDA_VISIBLE_DEVICES=6 nohup boltzgen run example/gpr75/gpr75.yaml \
  --output workbench/gpr75_run2 \
  --protocol peptide-anything \
  --num_designs 10000 \
  --budget 20 > nohup_logs/gpr75_run2.log &