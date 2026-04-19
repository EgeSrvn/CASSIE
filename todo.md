# Things Remaining

## 1. Support for hifiasm, verkko, metaspades (if not included in spades), liftoff, comparative annotation toolkit (CAT), BUSCO, merqury (if needed) are should also be added. Length realted flags should be added to the tool blocks in pipeline builder.

## 2. Small ml model to predict time and price of pipelines with different length of data,tool should be trained. 

## 6. Add meryl for merqury

## 7. Make it work on EC2

# Current Issues

##  It should immediately change the remaining number of jobs user can run at the same time. 

## If user hits the limit, it should immediately fail, not stay in pending

## move vm_partitions.json to /config