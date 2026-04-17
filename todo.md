# Things Remaining

## 1. Support for hifiasm, verkko, metaspades (if not included in spades), liftoff, comparative annotation toolkit (CAT), BUSCO, merqury (if needed) are should also be added.

## 2. Small ml model to predict time and price of pipelines with different length of data,tool should be trained. 

## open templates and customize shoudl be a bit seperate

## 6. Add meryl for merqury

## 7. Make it work on EC2

# Current Issues

## it waits files to be uploaded to notify the system that a pratition is filled. It should immediately change the number of available partition in the vm and the remaining number of jobs user can run at the same time. 

## If user hits the limit, it should immediately fail, not stay in pending

## Ready templates should be always available in community page

## move vm_partitions.json to /config